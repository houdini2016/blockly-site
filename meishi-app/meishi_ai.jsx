// =====================================================================
//  名刺自動作成 — Illustrator の書類を書き換える部分
//  （meishi_job.jsx と meishi_auto.jsx から #include して使います）
//  先に meishi_core.jsx を #include しておく必要があります。
// =====================================================================

var MeishiAI = (function () {
    var C = MeishiCore;

    // 文字コードを判定してテキストファイルを読む（UTF-8 / Shift_JIS）
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

    function oneLine(s, max) {
        max = max || 40;
        s = String(s).replace(/[\r\n\u0003]+/g, " / ");
        return s.length > max ? s.substring(0, max) + "…" : s;
    }

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
    function unlockFor(item) {
        var restore = [];
        while (item && item.typename !== "Document") {
            if (item.locked) { item.locked = false; restore.push(item); }
            item = item.parent;
        }
        return function () {
            for (var i = 0; i < restore.length; i++) restore[i].locked = true;
        };
    }

    // ----- LOGO 横のマーク -----

    // geometricBounds は [左, 上, 右, 下]（上の方が数字が大きい）
    // 「LOGO の左右すぐ横にあり、LOGO と同じくらいの大きさで、LOGO に重なっていない」ものをマークとみなす
    // （463 個のテンプレートで確認。背景の絵や大きな飾りは対象外になる）
    function isNextToLogo(b, logo) {
        var h = logo[1] - logo[3];
        var ih = b[1] - b[3], iw = b[2] - b[0];
        if (ih <= 0 || iw <= 0 || ih > h * 3 || iw > h * 3) return false;  // LOGO の3倍より大きいものは背景
        var vOverlap = Math.min(logo[1], b[1]) - Math.max(logo[3], b[3]);
        if (vOverlap < ih * 0.5) return false;                             // 半分以上が LOGO と同じ高さにある
        var gap;
        if (b[2] <= logo[0] + 1) gap = logo[0] - b[2];                     // 左側
        else if (b[0] >= logo[2] - 1) gap = b[0] - logo[2];                // 右側
        else return false;                                                  // LOGO に重なっている（背景）
        return gap <= h;
    }

    function overlaps(a, b) {
        return Math.min(a[2], b[2]) > Math.max(a[0], b[0]) && Math.min(a[1], b[1]) > Math.max(a[3], b[3]);
    }

    // 画像の範囲の一覧から、LOGO 横のマークだけを選ぶ（番号の一覧を返す）
    // ・他の画像に重なっているもの（背景の絵の一部）は選ばない
    // ・候補が2つ以上あるときは、どれがマークか分からないので何も選ばない（ambiguous に印を付ける）
    function pickMarks(boundsList, logo, info) {
        var out = [];
        for (var i = 0; i < boundsList.length; i++) {
            if (!isNextToLogo(boundsList[i], logo)) continue;
            var alone = true;
            for (var j = 0; j < boundsList.length; j++) {
                if (j !== i && overlaps(boundsList[i], boundsList[j])) { alone = false; break; }
            }
            if (alone) out.push(i);
        }
        if (out.length > 1) {
            if (info) info.ambiguous = true;
            return [];
        }
        return out;
    }

    function contains(group, item) {
        for (var p = item.parent; p && p.typename !== "Document"; p = p.parent) if (p === group) return true;
        return false;
    }

    // LOGO の文字の横にあるロゴマークを探す
    //  ① LOGO の文字とグループになっている図形・画像（LOGO のすぐ横にあるもの）
    //  ② LOGO のすぐ横（上下）にある画像
    function findLogoMarks(doc, logoFrame) {
        var marks = [];
        var parent = logoFrame.parent;
        if (parent.typename === "GroupItem") {
            for (var i = 0; i < parent.pageItems.length; i++) {
                var it = parent.pageItems[i];
                if (it !== logoFrame && it.typename !== "TextFrame" &&
                    isNextToLogo(it.geometricBounds, logoFrame.geometricBounds)) marks.push(it);
            }
            if (marks.length > 0) return marks;
        }
        var logo = logoFrame.geometricBounds;
        var lists = [doc.rasterItems, doc.placedItems], items = [], bounds = [];
        for (var l = 0; l < lists.length; l++) {
            for (var k = 0; k < lists[l].length; k++) {
                var item = lists[l][k];
                // マスクで切り抜かれている画像はマスクのグループごと消す
                while (item.parent.typename === "GroupItem" && item.parent.clipped &&
                       !contains(item.parent, logoFrame)) item = item.parent;
                items.push(item);
                bounds.push(item.geometricBounds);
            }
        }
        var info = {};
        var picked = pickMarks(bounds, logo, info);
        if (info.ambiguous) marks.ambiguous = true;
        for (var p = 0; p < picked.length; p++) marks.push(items[picked[p]]);
        return marks;
    }

    function removeLogoMarks(doc, rec, warnings) {
        if (C.hasLogoData(rec)) return;    // ロゴ有り → マークはそのまま（あとで差し替え）
        var count = 0;
        for (var i = 0; i < doc.textFrames.length; i++) {
            var tf = doc.textFrames[i];
            if (!C.isLogoText(tf.contents)) continue;
            var marks = findLogoMarks(doc, tf);
            if (marks.ambiguous) warnings.push("LOGO 横に画像が複数あり、マークか分からないため消していません");
            for (var m = 0; m < marks.length; m++) {
                try {
                    var relock = unlockFor(marks[m]);
                    marks[m].remove();
                    count++;
                    relock();
                } catch (e) {
                    warnings.push("LOGO 横のマークを消せませんでした（" + e.message + "）");
                }
            }
        }
        if (count > 0) warnings.push("LOGO 横のマークを " + count + " 個消しました（位置を確認してください）");
    }

    // ----- 書類全体の書き換え -----

    // 書類の文字を注文内容に書き換える。確認してほしいことを warnings に足す。
    function editDocument(doc, rec, warnings) {
        removeLogoMarks(doc, rec, warnings);   // LOGO の文字が会社名に変わる前に探す

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
        if (rec["自由行"]) warnings.push("自由記入（行目）: " + oneLine(rec["自由行"], 80));
        if (rec["備考"]) warnings.push("備考: " + oneLine(rec["備考"], 80));
        if (rec["確認事項"]) warnings.push(rec["確認事項"]);
    }

    return {
        readTextFile: readTextFile,
        oneLine: oneLine,
        isNextToLogo: isNextToLogo,
        pickMarks: pickMarks,
        editDocument: editDocument
    };
})();
