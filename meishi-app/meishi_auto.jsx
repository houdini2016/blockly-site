// =====================================================================
//  名刺自動作成・CSV一括版（Adobe Illustrator 用スクリプト）
//  ※ふだんは注文通知アプリの［名刺を作成］ボタン（meishi_job.jsx）を使います。
//    こちらは、デザイン番号入りのCSVからまとめて作りたいとき用です。
//
//  使い方：Illustrator のメニュー［ファイル］→［スクリプト］→［その他のスクリプト...］
//          でこのファイルを選びます。（meishi_core.jsx・meishi_ai.jsx を同じフォルダに置いてください）
//
//  1. 注文CSV・テンプレートフォルダ・保存先フォルダを選ぶ
//  2. CSVの1行ごとに、デザイン番号と同じ名前の .ai を開く
//  3. 名前・肩書・住所などを書き換えて「注文番号_名前.ai」で保存する
//  4. 結果（警告つき）を保存先フォルダの「処理結果_日時.txt」に書き出す
// =====================================================================

#target illustrator
#include "meishi_core.jsx"
#include "meishi_ai.jsx"

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

    // ----- ファイル -----

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
            MeishiAI.editDocument(doc, rec, result.warnings);
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

        var parsed = C.rowsToRecords(C.parseCSV(MeishiAI.readTextFile(csvFile)));
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
