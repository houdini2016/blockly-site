// =====================================================================
//  名刺自動作成（Adobe Illustrator 用スクリプト）
//
//  使い方：Illustrator のメニュー［ファイル］→［スクリプト］→［その他のスクリプト...］
//          でこのファイルを選びます。（meishi_core.jsx を同じフォルダに置いてください）
//
//  1. 注文CSV・テンプレートフォルダ・保存先フォルダを選ぶ
//  2. CSVの1行ごとに、デザイン番号と同じ名前の .ai を開く
//  3. 名前・肩書・住所などを書き換えて「注文番号_名前.ai」で保存する
//  4. 結果（警告つき）を保存先フォルダの「処理結果_日時.txt」に書き出す
// =====================================================================

#target illustrator
#include "meishi_core.jsx"

(function () {
    var C = MeishiCore;
    var SETTINGS_FILE = new File(Folder.userData + "/meishi_auto_settings.txt");

    // ----- 設定の保存・読み込み（前回選んだフォルダを覚えておく） -----

    function loadSettings() {
        var s = { csv: "", templates: "", output: "", overwrite: "0" };
        if (SETTINGS_FILE.exists) {
            SETTINGS_FILE.encoding = "UTF-8";
            SETTINGS_FILE.open("r");
            while (!SETTINGS_FILE.eof) {
                var line = SETTINGS_FILE.readln();
                var i = line.indexOf("=");
                if (i > 0) s[line.substring(0, i)] = line.substring(i + 1);
            }
            SETTINGS_FILE.close();
        }
        return s;
    }

    function saveSettings(s) {
        SETTINGS_FILE.encoding = "UTF-8";
        SETTINGS_FILE.open("w");
        for (var k in s) if (s.hasOwnProperty(k)) SETTINGS_FILE.writeln(k + "=" + s[k]);
        SETTINGS_FILE.close();
    }

    // ----- 最初の画面 -----

    function showDialog(s) {
        var w = new Window("dialog", "名刺自動作成");
        w.alignChildren = "fill";

        function row(label, value, pick) {
            var g = w.add("group");
            g.add("statictext", undefined, label).preferredSize.width = 130;
            var t = g.add("edittext", undefined, value);
            t.preferredSize.width = 360;
            var b = g.add("button", undefined, "選ぶ...");
            b.onClick = function () {
                var r = pick(t.text);
                if (r) t.text = r.fsName;
            };
            return t;
        }

        // Mac では関数、Windows では "*.csv" の形でファイルの種類をしぼる
        var csvFilter = ($.os.indexOf("Windows") >= 0) ? "CSV:*.csv" :
            function (f) { return (f instanceof Folder) || /\.csv$/i.test(f.name); };
        function pickFolder(cur, prompt) {
            var start = cur ? new Folder(cur) : null;
            return (start && start.exists) ? start.selectDlg(prompt) : Folder.selectDialog(prompt);
        }

        var csv = row("注文CSV", s.csv, function (cur) {
            var start = cur ? new File(cur) : null;
            return (start && start.exists) ? start.openDlg("注文CSVを選んでください", csvFilter) :
                File.openDialog("注文CSVを選んでください", csvFilter);
        });
        var tpl = row("テンプレートフォルダ", s.templates, function (cur) {
            return pickFolder(cur, "デザインの .ai が入ったフォルダを選んでください");
        });
        var out = row("保存先フォルダ", s.output, function (cur) {
            return pickFolder(cur, "作った名刺を保存するフォルダを選んでください");
        });
        var ow = w.add("checkbox", undefined, "同じ名前のファイルがあれば上書きする（オフなら _2 を付けて別名保存）");
        ow.value = s.overwrite === "1";

        var btns = w.add("group");
        btns.alignment = "right";
        btns.add("button", undefined, "キャンセル", { name: "cancel" });
        btns.add("button", undefined, "作成開始", { name: "ok" });

        if (w.show() !== 1) return null;
        return { csv: csv.text, templates: tpl.text, output: out.text, overwrite: ow.value ? "1" : "0" };
    }

    // ----- ファイル読み込み -----

    function readTextFile(file) {
        file.encoding = "BINARY";
        file.open("r");
        var bytes = file.read();
        file.close();
        file.encoding = C.detectEncoding(bytes);
        file.open("r");
        var text = file.read();
        file.close();
        return text;
    }

    // テンプレートフォルダ（中のフォルダも含む）の .ai を「デザイン番号 → ファイル」の表にする
    function indexTemplates(folder, index, dupes) {
        var items = folder.getFiles();
        for (var i = 0; i < items.length; i++) {
            if (items[i] instanceof Folder) {
                indexTemplates(items[i], index, dupes);
            } else if (/\.ai$/i.test(items[i].name)) {
                var key = C.normalizeKey(decodeURI(items[i].name));
                if (index[key]) dupes.push(decodeURI(items[i].name));
                else index[key] = items[i];
            }
        }
    }

    function uniqueFile(folder, name, overwrite) {
        var f = new File(folder.fsName + "/" + name);
        if (overwrite || !f.exists) return f;
        var base = name.replace(/\.ai$/i, "");
        for (var n = 2; ; n++) {
            f = new File(folder.fsName + "/" + base + "_" + n + ".ai");
            if (!f.exists) return f;
        }
    }

    // ----- テキストの書き換え -----

    // テキストフレームの start〜end 文字目を text に置き換える（最初の文字の書式を引き継ぐ）
    function replaceRange(tf, start, end, text) {
        var len = end - start;
        if (len <= 0) return;
        var r = tf.characters[start];
        try {
            if (len > 1) r.length = len;
        } catch (e) {
            // length が変えられない場合は1文字ずつ消す
            for (var i = end - 1; i > start; i--) tf.characters[i].remove();
            r = tf.characters[start];
        }
        if (text === "") r.remove();
        else r.contents = text;
    }

    // 書き換えのじゃまになるロックを一時的に外す
    function unlockFor(tf) {
        var restore = [];
        var item = tf;
        while (item && item.typename !== "Document") {
            if (item.typename === "Layer") {
                if (item.locked) { item.locked = false; restore.push(item); }
            } else if (item.locked) { item.locked = false; restore.push(item); }
            item = item.parent;
        }
        return function () {
            for (var i = 0; i < restore.length; i++) restore[i].locked = true;
        };
    }

    function editDocument(doc, rec, warnings) {
        var used = [];
        var frames = [];
        for (var i = 0; i < doc.textFrames.length; i++) frames.push(doc.textFrames[i]);

        var values = C.prepareValues(rec);
        for (var f = 0; f < frames.length; f++) {
            var tf = frames[f];
            var relock = unlockFor(tf);
            try {
                // テキストに項目名の名前（例:「氏名」）が付いていれば、中身を丸ごと置き換える
                if (tf.name && C.FIELD_ALIASES.hasOwnProperty(tf.name)) {
                    if (tf.contents !== "") replaceRange(tf, 0, tf.contents.length, values[tf.name] || "");
                    used.push(tf.name);
                } else {
                    var before = tf.contents;
                    var plan = C.planEdits(before, rec);
                    for (var u = 0; u < plan.used.length; u++) used.push(plan.used[u]);
                    if (plan.edits.length > 0) {
                        var expected = C.applyEditsToString(before, plan.edits);
                        for (var e = plan.edits.length - 1; e >= 0; e--) {
                            replaceRange(tf, plan.edits[e].start, plan.edits[e].end, plan.edits[e].text);
                        }
                        if (tf.contents !== expected) {
                            // 念のための安全策：うまく置き換わらなかったら中身ごと入れ直す
                            tf.contents = expected;
                            warnings.push("文字の書式が一部くずれたかもしれません: 「" + oneLine(expected) + "」");
                        }
                    }
                }
                if (C.hasLeftover(tf.contents)) {
                    warnings.push("仮の文字が残っています: 「" + oneLine(tf.contents) + "」");
                }
            } catch (err) {
                warnings.push("テキストを書き換えられませんでした（" + err.message + "）: 「" + oneLine(tf.contents) + "」");
            }
            relock();
        }
        var unused = C.unusedFields(rec, used);
        if (unused.length > 0) {
            warnings.push("テンプレートに差し込み先がない項目: " + unused.join("、"));
        }
        // 名刺には入れていないが、目で確認してほしい情報
        if (C.hasLogoData(rec)) warnings.push("ロゴデータ有り: LOGO の位置にロゴを配置してください");
        if (rec["自由行"]) warnings.push("自由記入（行目）: " + oneLine(rec["自由行"]));
        if (rec["備考"]) warnings.push("備考: " + oneLine(rec["備考"]));
        if (rec["確認事項"]) warnings.push(rec["確認事項"]);
    }

    function oneLine(s) {
        s = String(s).replace(/[\r\n\u0003]+/g, " / ");
        return s.length > 40 ? s.substring(0, 40) + "…" : s;
    }

    // ----- 1件分の処理 -----

    function processRecord(rec, index, outFolder, overwrite) {
        var result = { ok: false, file: "", warnings: [] };
        var key = C.normalizeKey(rec["デザイン番号"]);
        if (!key) {
            result.warnings.push("デザイン番号が空です");
            if (rec["確認事項"]) result.warnings.push(rec["確認事項"]);
            return result;
        }
        var tplFile = index[key];
        if (!tplFile) { result.warnings.push("テンプレートが見つかりません: " + rec["デザイン番号"]); return result; }

        var doc = app.open(tplFile);
        try {
            editDocument(doc, rec, result.warnings);
            var outFile = uniqueFile(outFolder, C.makeFileName(rec), overwrite);
            var opts = new IllustratorSaveOptions();
            opts.pdfCompatible = true;
            doc.saveAs(outFile, opts);
            result.ok = true;
            result.file = decodeURI(outFile.name);
        } finally {
            doc.close(SaveOptions.DONOTSAVECHANGES);
        }
        return result;
    }

    // ----- メイン -----

    function pad(n) { return (n < 10 ? "0" : "") + n; }

    function main() {
        var s = showDialog(loadSettings());
        if (!s) return;
        saveSettings(s);

        var csvFile = new File(s.csv), tplFolder = new Folder(s.templates), outFolder = new Folder(s.output);
        if (!csvFile.exists) { alert("注文CSVが見つかりません:\n" + s.csv); return; }
        if (!tplFolder.exists) { alert("テンプレートフォルダが見つかりません:\n" + s.templates); return; }
        if (!outFolder.exists && !outFolder.create()) { alert("保存先フォルダを作れません:\n" + s.output); return; }

        var parsed = C.rowsToRecords(C.parseCSV(readTextFile(csvFile)));
        var records = parsed.records;
        if (records.length === 0) { alert("CSVに注文が1件もありません。1行目は見出し（注文番号,デザイン番号,氏名...）にしてください。"); return; }

        var index = {}, dupes = [];
        indexTemplates(tplFolder, index, dupes);

        var now = new Date();
        var stamp = now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) + "_" +
                    pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
        var log = ["名刺自動作成 " + stamp, "CSV: " + csvFile.fsName, ""];
        if (parsed.unknownHeaders.length > 0) log.push("※ 使っていない列: " + parsed.unknownHeaders.join("、"), "");
        if (dupes.length > 0) log.push("※ 同じデザイン番号のファイルが複数あります（最初の1つを使用）: " + dupes.join("、"), "");

        // 進み具合を表示する小さな窓
        var progress = new Window("palette", "名刺自動作成");
        var label = progress.add("statictext", undefined, "準備中...");
        label.preferredSize.width = 400;
        var bar = progress.add("progressbar", undefined, 0, records.length);
        bar.preferredSize.width = 400;
        progress.show();

        var oldLevel = app.userInteractionLevel;
        app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;  // フォント不足などの確認を出さない
        var okCount = 0, warnCount = 0, ngCount = 0;
        try {
            for (var i = 0; i < records.length; i++) {
                var rec = records[i];
                label.text = (i + 1) + " / " + records.length + "  " + (rec["注文番号"] || "") + " " + (rec["氏名"] || "");
                bar.value = i;
                progress.update();

                var res;
                try {
                    res = processRecord(rec, index, outFolder, s.overwrite === "1");
                } catch (err) {
                    res = { ok: false, file: "", warnings: ["エラー: " + err.message] };
                }
                var head = (i + 2) + "行目 " + (rec["注文番号"] || "") + " " + (rec["デザイン番号"] || "") + " → ";
                if (!res.ok) { ngCount++; log.push("[失敗] " + head + "作成できませんでした"); }
                else if (res.warnings.length > 0) { warnCount++; log.push("[要確認] " + head + res.file); }
                else { okCount++; log.push("[OK] " + head + res.file); }
                for (var w = 0; w < res.warnings.length; w++) log.push("        - " + res.warnings[w]);
            }
        } finally {
            app.userInteractionLevel = oldLevel;
            progress.close();
        }

        var summary = "OK: " + okCount + " 件 / 要確認: " + warnCount + " 件 / 失敗: " + ngCount + " 件";
        log.push("", summary);
        var logFile = new File(outFolder.fsName + "/処理結果_" + stamp + ".txt");
        logFile.encoding = "UTF-8";
        logFile.lineFeed = "Windows";
        logFile.open("w");
        logFile.write("\uFEFF" + log.join("\n"));
        logFile.close();

        alert("完了しました。\n" + summary + "\n\n詳しくは保存先フォルダの\n" + decodeURI(logFile.name) + "\nを見てください。");
    }

    main();
})();
