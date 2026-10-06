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

    // ----- 備考 -----

    var MM = 72 / 25.4;                    // 1mm = 約2.83pt
    var REMARK_OFFSET = 80 * MM;           // テンプレートの中心から 8cm 下
    var REMARK_SIZE = 7;                   // 7pt
    var REMARK_FONTS = ["MS-Gothic", "MSGothic", "MS Gothic", "ＭＳゴシック", "ＭＳ ゴシック"];

    function findFont(names) {
        for (var i = 0; i < names.length; i++) {
            try { return app.textFonts.getByName(names[i]); } catch (e) { /* 次の名前を試す */ }
        }
        return null;
    }

    // お客さんの備考を、テンプレートの中心から 8cm 下に 7pt の MSゴシックで入れる（中央揃え）
    function addRemarks(doc, text, warnings) {
        text = C.trim(text || "");
        if (!C.remarkHasContent(text)) return;   // お店の案内文だけ（お客さんが何も書いていない）なら入れない
        var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;   // [左, 上, 右, 下]
        var cx = (ab[0] + ab[2]) / 2, cy = (ab[1] + ab[3]) / 2;

        var layer = doc.layers.add();
        layer.name = "備考";
        var tf = layer.textFrames.add();
        tf.contents = text.replace(/\r\n|\n/g, "\r");
        var range = tf.textRange;
        range.characterAttributes.size = REMARK_SIZE;
        var font = findFont(REMARK_FONTS);
        if (font) range.characterAttributes.textFont = font;
        else warnings.push("MSゴシックが見つからないため、備考は標準のフォントで入れました");
        range.paragraphAttributes.justification = Justification.CENTER;
        // 文字のかたまりの「上の中央」を、中心から 8cm 下にそろえる
        tf.position = [cx - tf.width / 2, cy - REMARK_OFFSET];
        warnings.push("備考を名刺の下（中心から8cm下）に入れました");
    }

    // ----- 見出しと値が別のテキストになっているデザイン -----
    //  「E-mail」と「  : ooooo@oooo.com」を重ねて置いているデザイン（372 個）は、
    //  そのままコロンを詰めると「：」が見出しに重なるので、見出しのテキストに1つにまとめる。
    //  （URL は対象外。まとめたあとの「：」は meishi_core.jsx の決まりでそろう）
    function mergeSplitLabels(doc) {
        var labels = [], values = [], removed = [];
        for (var i = 0; i < doc.textFrames.length; i++) {
            var tf = doc.textFrames[i], t = tf.contents;
            if (/[\r\n\u0003]/.test(t)) continue;
            var field = C.labelOnlyField(t);
            if (field && field !== "URL") labels.push(tf);
            else if (/^[ \t\u3000]*[:：]/.test(t)) values.push(tf);
        }
        for (var l = 0; l < labels.length; l++) {
            var lb = labels[l].geometricBounds, h = lb[1] - lb[3];
            var best = null, bestGap = 0;
            for (var v = 0; v < values.length; v++) {
                if (!values[v]) continue;
                var vb = values[v].geometricBounds;
                var vOverlap = Math.min(lb[1], vb[1]) - Math.max(lb[3], vb[3]);
                var gap = vb[0] - lb[0];                          // 値は見出しの右側（重なっていてもよい）
                if (vOverlap < Math.min(h, vb[1] - vb[3]) * 0.5 || gap < 0 || vb[0] > lb[2] + h * 3) continue;
                if (!best || gap < bestGap) { best = v; bestGap = gap; }
            }
            if (best === null) continue;
            var valueFrame = values[best];
            var relock = unlockFor(labels[l]);
            var relock2 = unlockFor(valueFrame);
            labels[l].contents = labels[l].contents.replace(/[ \t\u3000:：]+$/, "") + ":" +
                                 valueFrame.contents.replace(/^[ \t\u3000]*[:：]/, "");
            removed.push(valueFrame);
            valueFrame.remove();
            values[best] = null;
            relock();
            try { relock2(); } catch (e) { /* 消したテキストのロックは戻さない */ }
        }
        return removed;
    }

    // ----- ふりがな・部署名（新しいテキストとして足す） -----

    var FURIGANA_SIZE = 5;     // ふりがな：氏名の上に 5pt
    var DEPARTMENT_SIZE = 8;   // 部署名：会社名と肩書の間（肩書の上）に 8pt
    var LABEL_GAP = 1;         // 元のテキストとのすき間（pt）

    // 書き換える前に、そのテキストの位置・フォント・そろえ方・縦書きかを覚えておく
    function captureInfo(tf, index) {
        var info = { frame: tf, bounds: tf.geometricBounds, font: null, align: "left", vertical: false };
        try { info.font = tf.characters[index].characterAttributes.textFont; } catch (e1) { /* フォントは標準のまま */ }
        try { info.vertical = tf.orientation === TextOrientation.VERTICAL; } catch (e2) { /* 横書き */ }
        try {
            var j = tf.characters[index].paragraphAttributes.justification;
            if (j === Justification.CENTER) info.align = "center";
            else if (j === Justification.RIGHT) info.align = "right";
        } catch (e3) { /* 左そろえ */ }
        return info;
    }

    // 元のテキストがまだあればその今の位置、消えていれば書き換える前の位置
    function currentBounds(info) {
        try { return info.frame.geometricBounds; } catch (e) { return info.bounds; }
    }

    // info のテキストの上（縦書きなら右）に、小さな文字のテキストを足す。
    // inPlace が true なら、上ではなく info のテキストがあった場所に入れる（肩書が空で消えたとき）
    function addLabelAbove(doc, info, text, size, align, inPlace) {
        var tf = doc.textFrames.add();
        tf.contents = text;
        var attrs = tf.textRange.characterAttributes;
        attrs.size = size;
        if (info.font) attrs.textFont = info.font;
        if (info.vertical) tf.orientation = TextOrientation.VERTICAL;
        var b = currentBounds(info);                  // [左, 上, 右, 下]（上の方が数字が大きい）
        var w = tf.width, h = tf.height;
        if (info.vertical) {
            tf.position = [inPlace ? b[0] : b[2] + LABEL_GAP, b[1]];     // 縦書き：右どなり、上をそろえる
        } else {
            var left = align === "center" ? (b[0] + b[2]) / 2 - w / 2 : align === "right" ? b[2] - w : b[0];
            tf.position = [left, inPlace ? b[1] : b[1] + LABEL_GAP + h];
        }
        try { tf.move(info.frame, ElementPlacement.PLACEBEFORE); } catch (e) { /* 元のテキストが消えていたらそのまま */ }
        return tf;
    }

    // ----- 書類全体の書き換え -----

    // 書類の文字を注文内容に書き換える。確認してほしいことを warnings に足す。
    function editDocument(doc, rec, warnings) {
        removeLogoMarks(doc, rec, warnings);   // LOGO の文字が会社名に変わる前に探す
        var merged = [];
        try { merged = mergeSplitLabels(doc); }
        catch (mergeErr) { warnings.push("「E-mail」などの見出しをまとめられませんでした（" + mergeErr.message + "）"); }

        var used = [];
        var frames = [];
        for (var i = 0; i < doc.textFrames.length; i++) {
            var skip = false;
            for (var mg = 0; mg < merged.length; mg++) if (merged[mg] === doc.textFrames[i]) skip = true;
            if (!skip) frames.push(doc.textFrames[i]);
        }

        var values = C.prepareValues(rec);
        var nameInfo = null, titleInfo = null;   // ふりがな・部署名を置く場所の目印
        var removedFrames = [];                  // 未入力で消したテキスト
        for (var f = 0; f < frames.length; f++) {
            var tf = frames[f];
            var frameBefore = tf.contents;
            var relock = unlockFor(tf);
            try {
                // テキストに項目名の名前（例:「氏名」）が付いていれば、中身を丸ごと置き換える
                if (tf.name && C.FIELD_ALIASES.hasOwnProperty(tf.name)) {
                    if (tf.name === "氏名" && !nameInfo) nameInfo = captureInfo(tf, 0);
                    if (tf.name === "肩書" && !titleInfo) titleInfo = captureInfo(tf, 0);
                    if (tf.contents !== "") replaceRange(tf, 0, tf.contents.length, values[tf.name] || "");
                    used.push(tf.name);
                } else {
                    var before = tf.contents;
                    var plan = C.planEdits(before, rec);
                    for (var u = 0; u < plan.used.length; u++) used.push(plan.used[u]);
                    if (!nameInfo && plan.fieldPos.hasOwnProperty("氏名")) nameInfo = captureInfo(tf, plan.fieldPos["氏名"]);
                    if (!titleInfo && plan.fieldPos.hasOwnProperty("肩書")) titleInfo = captureInfo(tf, plan.fieldPos["肩書"]);
                    if (plan.edits.length > 0) {
                        var expected = C.applyEditsToString(before, plan.edits);
                        try {
                            // 後ろから1か所ずつ置き換える（文字ごとの書式を残すため）
                            for (var e = plan.edits.length - 1; e >= 0; e--) {
                                replaceRange(tf, plan.edits[e].start, plan.edits[e].end, plan.edits[e].text);
                            }
                        } catch (rangeErr) {
                            // 改行をまたぐ削除などで Illustrator がエラーを出したときは、下で中身ごと入れ直す
                        }
                        if (tf.contents !== expected) {
                            // 安全策：うまく置き換わらなかったら中身ごと入れ直す
                            tf.contents = expected;
                            warnings.push("文字の書式が一部くずれたかもしれません: 「" + oneLine(expected) + "」");
                        }
                    }
                    for (var nt = 0; nt < plan.notes.length; nt++) warnings.push(plan.notes[nt]);
                    for (var r = 0; r < plan.leftoverRemoved.length; r++) {
                        warnings.push("見つからない仮の文字が残っていたので行を消しました: 「" + oneLine(plan.leftoverRemoved[r]) + "」");
                    }
                }
            } catch (err) {
                warnings.push("テキストを書き換えられませんでした（" + err.message + "）: 「" + oneLine(tf.contents) + "」");
            }
            // 未入力で中身が空になったテキストは、テキストごと消す
            var emptied = false;
            try {
                if (frameBefore !== "" && C.trim(tf.contents) === "") { removedFrames.push(tf); tf.remove(); emptied = true; }
            } catch (removeErr) { /* 消せなくても空なので見た目は同じ */ }
            if (!emptied) relock();
        }
        // ふりがな：氏名の上に、氏名と同じフォントで 5pt（中央そろえ）
        if (rec["ふりがな"]) {
            if (!nameInfo) warnings.push("氏名の場所が見つからないため、ふりがなを入れていません: " + rec["ふりがな"]);
            else {
                try { addLabelAbove(doc, nameInfo, rec["ふりがな"], FURIGANA_SIZE, "center"); used.push("ふりがな"); }
                catch (furiErr) { warnings.push("ふりがなを入れられませんでした（" + furiErr.message + "）"); }
            }
        }
        // 部署名：会社名と肩書の間（肩書の上）に、肩書と同じフォントで 8pt。
        // 肩書が空で消えたときは肩書があった場所に、肩書の場所がないデザインは氏名の上に入れる
        if (rec["部署"]) {
            var deptInfo = titleInfo || nameInfo;
            var titleGone = false;
            for (var rf = 0; titleInfo && rf < removedFrames.length; rf++) if (removedFrames[rf] === titleInfo.frame) titleGone = true;
            if (!deptInfo) warnings.push("肩書・氏名の場所が見つからないため、部署名を入れていません: " + rec["部署"]);
            else {
                try {
                    addLabelAbove(doc, deptInfo, rec["部署"], DEPARTMENT_SIZE, deptInfo.align, titleGone);
                    warnings.push(titleGone ? "部署名を肩書の場所に入れました（位置を確認してください）"
                                            : "部署名を肩書の上に入れました（位置を確認してください）");
                } catch (deptErr) { warnings.push("部署名を入れられませんでした（" + deptErr.message + "）"); }
            }
        }

        var unused = C.unusedFields(rec, used);
        if (unused.length > 0) {
            warnings.push("テンプレートに差し込み先がない項目: " + unused.join("、"));
        }
        // 名刺には入れていないが、目で確認してほしい情報
        if (C.hasLogoData(rec)) warnings.push("ロゴデータ有り: LOGO の位置にロゴを配置してください");
        if (rec["自由行"]) warnings.push("自由記入（行目）: " + oneLine(rec["自由行"], 80));
        if (rec["備考"]) {
            try { addRemarks(doc, rec["備考"], warnings); }
            catch (remarkErr) { warnings.push("備考を入れられませんでした（" + remarkErr.message + "）: " + oneLine(rec["備考"], 80)); }
        }
        if (rec["確認事項"]) warnings.push(rec["確認事項"]);
    }

    return {
        readTextFile: readTextFile,
        oneLine: oneLine,
        isNextToLogo: isNextToLogo,
        pickMarks: pickMarks,
        addRemarks: addRemarks,
        addLabelAbove: addLabelAbove,
        mergeSplitLabels: mergeSplitLabels,
        REMARK_OFFSET: REMARK_OFFSET,
        editDocument: editDocument
    };
})();
