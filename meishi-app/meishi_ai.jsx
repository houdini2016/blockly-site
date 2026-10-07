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

    // 「E-mail  : ooooo」の空白にマイナスの文字間隔（カーニング・トラッキング）を付けて
    // コロンを見出しに寄せているデザインがある。空白を「：値」に置き換えると、その詰めが残って
    // 「：」が見出しに重なるので、置き換えた文字の間隔を見出しの最初の文字と同じに戻す。
    function resetSpacing(tf, baseIndex, start, len) {
        var base = 0;
        try { base = tf.characters[baseIndex].characterAttributes.tracking; } catch (e0) { base = 0; }
        // 見出しの最初の文字の前に余計なすき間を作らない（その文字と、ひとつ前の改行文字の間隔を 0 に）
        try { tf.characters[baseIndex].kerning = 0; } catch (e3) { /* そのまま */ }
        if (baseIndex > 0) {
            try {
                var prev = tf.characters[baseIndex - 1];
                if (/[\r\n\u0003]/.test(prev.contents)) {
                    prev.kerning = 0;
                    prev.characterAttributes.tracking = base;
                }
            } catch (e4) { /* そのまま */ }
        }
        for (var i = start - 1; i < start + len; i++) {
            if (i < 0) continue;
            try {
                var ch = tf.characters[i];
                ch.characterAttributes.tracking = base;
                try { ch.kerning = 0; } catch (e1) { /* カーニングを変えられないときはそのまま */ }
            } catch (e2) { /* その文字は飛ばす */ }
        }
    }

    // 確認用ログ（「E-mail」の行などの文字ごとの間隔を、直す前と後で記録する）
    var debugLog = [];

    function spacingDump(tf, from, to) {
        var out = [];
        for (var i = Math.max(0, from); i < to; i++) {
            try {
                var ch = tf.characters[i];
                out.push(ch.contents + "(k" + ch.kerning + ",t" + ch.characterAttributes.tracking + ")");
            } catch (e) { break; }
        }
        return out.join(" ");
    }

    // その行（段落）の字下げの設定（ログ用）
    function indentDump(tf, index) {
        try {
            var pa = tf.characters[index].paragraphAttributes;
            return "[字下げ 左" + pa.leftIndent + " 1行目" + pa.firstLineIndent + " そろえ" + pa.justification + "]";
        } catch (e) { return ""; }
    }

    // edits を当てはめたあとの、それぞれの置き換え部分の始まりの位置で resetSpacing する
    function fixSpacing(tf, edits) {
        var shift = 0;
        for (var e = 0; e < edits.length; e++) {
            var ed = edits[e];
            if (ed.hasOwnProperty("spacingFrom")) {
                var from = ed.spacingFrom + shift, st = ed.start + shift;
                var beforeDump = spacingDump(tf, from - 1, st + 3) + "  " + indentDump(tf, from);
                resetSpacing(tf, from, st, ed.text.length);
                debugLog.push(ed.field + "  直す前: " + beforeDump + "\n" + ed.field + "  直した後: " + spacingDump(tf, from - 1, st + 3));
            }
            shift += ed.text.length - (ed.end - ed.start);
        }
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
    var REMARK_OFFSET = 50 * MM;           // テンプレートの中心から 5cm 下
    var FALLBACK_OFFSET = 50 * MM;         // 置く場所が見つからないとき：中心から 5cm 上
    var REMARK_SIZE = 7;                   // 7pt
    var REMARK_FONTS = ["MS-Gothic", "MSGothic", "MS Gothic", "ＭＳゴシック", "ＭＳ ゴシック"];

    function findFont(names) {
        for (var i = 0; i < names.length; i++) {
            try { return app.textFonts.getByName(names[i]); } catch (e) { /* 次の名前を試す */ }
        }
        return null;
    }

    // アートボード（テンプレート）の中心 [x, y]
    function artboardCenter(doc) {
        var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;   // [左, 上, 右, 下]
        return [(ab[0] + ab[2]) / 2, (ab[1] + ab[3]) / 2];
    }

    // お客さんの備考を、テンプレートの中心から 5cm 下に 7pt の MSゴシックで入れる（中央揃え）
    function addRemarks(doc, text, warnings) {
        text = C.trim(text || "");
        if (!C.remarkHasContent(text)) return;   // お店の案内文だけ（お客さんが何も書いていない）なら入れない
        var c = artboardCenter(doc), cx = c[0], cy = c[1];

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
        warnings.push("備考を名刺の下（中心から5cm下）に入れました");
    }

    // ----- 見出しと値が別のテキストになっているデザイン -----
    //  「E-mail」と「  : ooooo@oooo.com」を重ねて置いているデザイン（372 個）は、
    //  そのままコロンを詰めると「：」が見出しに重なるので、見出しのテキストに1つにまとめる。
    //  （URL は対象外。まとめたあとの「：」は meishi_core.jsx の決まりでそろう）
    function mergeSplitLabels(doc) {
        var labels = [], values = [], removed = [];
        for (var i = 0; i < doc.textFrames.length; i++) {
            var tf = doc.textFrames[i], t = tf.contents;
            // 値のテキスト：「  : ooooo@…」のように 1 行でコロンから始まる
            if (!/[\r\n\u0003]/.test(t) && /^[ \t　]*[:：]/.test(t)) { values.push(tf); continue; }
            // 見出しの行：テキストの中の「E-mail」だけの行（「Mobile …」と同じテキストの2行目などでもよい）
            var lines = t.split(/[\r\n\u0003]/), pos = 0;
            for (var li = 0; li < lines.length; li++) {
                var field = C.labelOnlyField(lines[li]);
                if (field && field !== "URL" && C.trim(lines[li]) !== "") {
                    labels.push({ frame: tf, index: li, count: lines.length, start: pos, text: lines[li] });
                }
                pos += lines[li].length + 1;
            }
        }
        for (var l = 0; l < labels.length; l++) {
            var L = labels[l], fb = L.frame.geometricBounds;
            // その行のおおよその高さの範囲（複数行のテキストは行の数で等分して考える）
            var lineH = (fb[1] - fb[3]) / L.count;
            var top = fb[1] - lineH * L.index, bottom = top - lineH;
            var best = null, bestGap = 0;
            for (var v = 0; v < values.length; v++) {
                if (!values[v]) continue;
                var vb = values[v].geometricBounds;
                var vOverlap = Math.min(top, vb[1]) - Math.max(bottom, vb[3]);
                var gap = vb[0] - fb[0];                         // 値は見出しの右側（重なっていてもよい）
                if (vOverlap < Math.min(lineH, vb[1] - vb[3]) * 0.5 || gap < 0 || vb[0] > fb[2] + lineH * 3) continue;
                if (best === null || gap < bestGap) { best = v; bestGap = gap; }
            }
            if (best === null) continue;
            var valueFrame = values[best];
            var relock = unlockFor(L.frame);
            var relock2 = unlockFor(valueFrame);
            // 「E-mail」の行の最後に「:値」をつなげる（最後の文字の書式を引き継ぐ）
            var word = L.text.replace(/[ \t　:：]+$/, "");
            var wordEnd = L.start + L.text.search(/[ \t　:：]*$/);
            var lineEnd = L.start + L.text.length;
            var addText = ":" + valueFrame.contents.replace(/^[ \t　]*[:：]/, "");
            var before = L.frame.contents;
            var expected = before.substring(0, wordEnd) + addText + before.substring(lineEnd);
            try {
                replaceRange(L.frame, wordEnd - 1, lineEnd, word.charAt(word.length - 1) + addText);
            } catch (e) { /* 下で中身ごと入れ直す */ }
            if (L.frame.contents !== expected) L.frame.contents = expected;
            removed.push(valueFrame);
            valueFrame.remove();
            values[best] = null;
            relock();
            try { relock2(); } catch (e2) { /* 消したテキストのロックは戻さない */ }
        }
        return removed;
    }

    // ----- ふりがな・部署名（新しいテキストとして足す） -----

    var FURIGANA_SIZE = 5;     // ふりがな：氏名の上に 5pt
    var DEPARTMENT_SIZE = 8;   // 部署名：会社名と肩書の間（肩書の上）に 8pt
    var LABEL_GAP = 1;         // 元のテキストとのすき間（pt）

    // 書き換える前に、そのテキストの位置・フォント・そろえ方・縦書きかを覚えておく
    function captureInfo(tf, index, frameIndex) {
        var info = { frame: tf, frameIndex: frameIndex, removed: false, bounds: tf.geometricBounds,
                     font: null, align: "left", vertical: false };
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
    // （消したテキストに触ると Illustrator が「オブジェクトが無効です」になるので、消したものは覚えた位置を使う）
    function currentBounds(info) {
        if (info.removed) return info.bounds;
        try { return info.frame.geometricBounds; } catch (e) { return info.bounds; }
    }

    // 足すテキストは専用のレイヤー「追加テキスト」に入れる
    // （テンプレートのレイヤーがロック・非表示だと文字を足せずにエラーになるため）
    var ADDED_LAYER = "追加テキスト";

    function addedLayer(doc) {
        var layer = null;
        try { layer = doc.layers.getByName(ADDED_LAYER); } catch (e) { layer = null; }
        if (!layer) {
            layer = doc.layers.add();
            layer.name = ADDED_LAYER;
        }
        try { layer.locked = false; layer.visible = true; } catch (e2) { /* そのまま */ }
        return layer;
    }

    function newText(doc, text, size, font) {
        var tf = addedLayer(doc).textFrames.add();
        tf.contents = text;
        var attrs = tf.textRange.characterAttributes;
        attrs.size = size;
        if (font) {
            try { attrs.textFont = font; } catch (e) { /* フォントを変えられなければデフォルトのまま */ }
        }
        return tf;
    }

    // info のテキストのまわりに、小さな文字のテキストを足す。
    //   mode "above"   ：上（縦書きなら右どなり）
    //   mode "inPlace" ：info のテキストがあった場所（肩書が空で消えたとき）
    //   mode "below"   ：下（縦書きなら左どなり）
    function addLabelAbove(doc, info, text, size, align, mode) {
        var tf = newText(doc, text, size, info.font);
        if (info.vertical) {
            try { tf.orientation = TextOrientation.VERTICAL; } catch (e) { /* 横書きのまま */ }
        }
        var b = currentBounds(info);                  // [左, 上, 右, 下]（上の方が数字が大きい）
        var w = tf.width, h = tf.height;
        if (info.vertical) {                          // 縦書き：上をそろえる
            var x = mode === "inPlace" ? b[0] : mode === "below" ? b[0] - LABEL_GAP - w : b[2] + LABEL_GAP;
            tf.position = [x, b[1]];
        } else {
            var left = align === "center" ? (b[0] + b[2]) / 2 - w / 2 : align === "right" ? b[2] - w : b[0];
            var top = mode === "inPlace" ? b[1] : mode === "below" ? b[3] - LABEL_GAP : b[1] + LABEL_GAP + h;
            tf.position = [left, top];
        }
        return tf;
    }

    // 置く場所が見つからなかった項目を、まとめてテンプレートの中心から 5cm 上に入れる（デフォルトのフォント・8pt）
    var FALLBACK_SIZE = 8;

    function addFallbackBlock(doc, lines) {
        var tf = newText(doc, lines.join("\r"), FALLBACK_SIZE, null);
        try { tf.textRange.paragraphAttributes.justification = Justification.CENTER; } catch (e) { /* 左そろえのまま */ }
        var c = [0, 0];
        try { c = artboardCenter(doc); } catch (e2) { /* アートボードが分からなければ原点 */ }
        tf.position = [c[0] - tf.width / 2, c[1] + FALLBACK_OFFSET];
        return tf;
    }

    // 置き場所がなかった項目を、名刺での書き方にして1行にする
    var FALLBACK_ORDER = ["会社名", "会社名英字", "肩書", "肩書英字", "氏名", "氏名英字", "郵便番号",
                          "住所1", "住所2", "英字住所1", "英字住所2", "TEL", "FAX", "携帯", "メール", "URL"];
    var FALLBACK_PREFIX = { "郵便番号": "〒", "TEL": "TEL：", "FAX": "FAX：", "携帯": "Mobile：", "メール": "E-mail：" };

    function fallbackLine(field, value) {
        return (FALLBACK_PREFIX[field] || "") + value;
    }

    // ----- 書類全体の書き換え -----

    // 書類の文字を注文内容に書き換える。確認してほしいことを warnings に足す。
    function editDocument(doc, rec, warnings) {
        removeLogoMarks(doc, rec, warnings);   // LOGO の文字が会社名に変わる前に探す
        try { mergeSplitLabels(doc); }
        catch (mergeErr) { warnings.push("「E-mail」などの見出しをまとめられませんでした（" + mergeErr.message + "）"); }

        var used = [];
        var frames = [];
        // （まとめて消したテキストは、もう doc.textFrames に入っていない）
        for (var i = 0; i < doc.textFrames.length; i++) frames.push(doc.textFrames[i]);

        var values = C.prepareValues(rec);
        var nameInfo = null, titleInfo = null, companyInfo = null;   // ふりがな・部署名を置く場所の目印
        var COMPANY_KEYS = ["会社名", "会社名_後", "会社名_前", "会社名英字", "(そのまま)"];
        for (var f = 0; f < frames.length; f++) {
            var tf = frames[f];
            var frameBefore = tf.contents;
            var relock = unlockFor(tf);
            try {
                // テキストに項目名の名前（例:「氏名」）が付いていれば、中身を丸ごと置き換える
                if (tf.name && C.FIELD_ALIASES.hasOwnProperty(tf.name)) {
                    if (tf.name === "氏名" && !nameInfo) nameInfo = captureInfo(tf, 0, f);
                    if (tf.name === "肩書" && !titleInfo) titleInfo = captureInfo(tf, 0, f);
                    if (tf.contents !== "") replaceRange(tf, 0, tf.contents.length, values[tf.name] || "");
                    used.push(tf.name);
                } else {
                    var before = tf.contents;
                    var plan = C.planEdits(before, rec);
                    for (var u = 0; u < plan.used.length; u++) used.push(plan.used[u]);
                    if (!nameInfo && plan.fieldPos.hasOwnProperty("氏名")) nameInfo = captureInfo(tf, plan.fieldPos["氏名"], f);
                    if (!titleInfo && plan.fieldPos.hasOwnProperty("肩書")) titleInfo = captureInfo(tf, plan.fieldPos["肩書"], f);
                    for (var ck = 0; !companyInfo && ck < COMPANY_KEYS.length; ck++) {
                        if (plan.fieldPos.hasOwnProperty(COMPANY_KEYS[ck])) companyInfo = captureInfo(tf, plan.fieldPos[COMPANY_KEYS[ck]], f);
                    }
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
                        fixSpacing(tf, plan.edits);   // 「：」が見出しに重ならないよう文字の間隔をそろえる
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
                if (frameBefore !== "" && C.trim(tf.contents) === "") {
                    // 消す前に（まだ有効なうちに）目印のテキストかどうかを記録する
                    var infos = [nameInfo, titleInfo, companyInfo];
                    for (var ii = 0; ii < infos.length; ii++) {
                        if (infos[ii] && infos[ii].frameIndex === f) infos[ii].removed = true;   // 番号で比べる（消したものとは比べない）
                    }
                    tf.remove();
                    emptied = true;
                }
            } catch (removeErr) { /* 消せなくても空なので見た目は同じ */ }
            if (!emptied) relock();
        }
        // 置き場所が見つからなかった項目は fallback に集めて、最後にまとめて中心から 5cm 上に入れる
        var fallback = [], fallbackNames = [];
        function toFallback(name, line) { fallback.push(line); fallbackNames.push(name); }

        // ふりがな：氏名の上に、氏名と同じフォントで 5pt（中央そろえ）
        if (rec["ふりがな"]) {
            var furiDone = false;
            if (nameInfo) {
                try { addLabelAbove(doc, nameInfo, rec["ふりがな"], FURIGANA_SIZE, "center", "above"); furiDone = true; }
                catch (furiErr) { /* 下でまとめて入れる */ }
            }
            if (!furiDone) toFallback("ふりがな", rec["ふりがな"]);
        }
        // 部署名：8pt。置く場所は上から順に
        //   1. 肩書の上（会社名と肩書の間）… 肩書と同じフォント・そろえ方
        //   2. 肩書が空で消えたときは、肩書があった場所
        //   3. 肩書の場所がないデザインは、氏名の上
        //   4. 肩書も氏名も場所がなければ、会社名の下
        //   5. どれも見つからない・入れられなければ、中心から 5cm 上（まとめて）
        if (rec["部署"]) {
            var titleGone = !!(titleInfo && titleInfo.removed);
            var tries = [];
            if (titleInfo) tries.push([titleInfo, titleGone ? "inPlace" : "above", titleGone ? "肩書の場所" : "肩書の上"]);
            if (nameInfo) tries.push([nameInfo, "above", "氏名の上"]);
            if (companyInfo) tries.push([companyInfo, "below", "会社名の下"]);
            var deptWhere = null;
            for (var tr = 0; tr < tries.length && !deptWhere; tr++) {
                try {
                    addLabelAbove(doc, tries[tr][0], rec["部署"], DEPARTMENT_SIZE, tries[tr][0].align, tries[tr][1]);
                    deptWhere = tries[tr][2];
                } catch (deptErr) { /* 次の場所を試す */ }
            }
            if (deptWhere) warnings.push("部署名を" + deptWhere + "に入れました（位置を確認してください）");
            else toFallback("部署名", rec["部署"]);
        }

        // テンプレートに差し込み先がなかった項目も、流し込み漏れがないように打ち込む
        var unused = C.unusedFields(rec, used);
        for (var fo = 0; fo < FALLBACK_ORDER.length; fo++) {
            for (var un = 0; un < unused.length; un++) {
                if (unused[un] === FALLBACK_ORDER[fo]) toFallback(unused[un], fallbackLine(unused[un], rec[unused[un]]));
            }
        }
        if (rec["自由行"]) toFallback("自由記入（行目）", rec["自由行"].split(" / ").join("\r"));

        if (fallback.length > 0) {
            try {
                addFallbackBlock(doc, fallback);
                warnings.push("置き場所が見つからなかった項目を中心から5cm上に入れました（移動してください）: " + fallbackNames.join("、"));
            } catch (fbErr) {
                warnings.push("項目を入れられませんでした（" + fbErr.message + "）: " + oneLine(fallback.join(" / "), 120));
            }
        }

        // 名刺には入れていないが、目で確認してほしい情報
        if (C.hasLogoData(rec)) warnings.push("ロゴデータ有り: LOGO の位置にロゴを配置してください");
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
        fallbackLine: fallbackLine,
        mergeSplitLabels: mergeSplitLabels,
        fixSpacing: fixSpacing,
        debugLog: debugLog,
        REMARK_OFFSET: REMARK_OFFSET,
        FALLBACK_OFFSET: FALLBACK_OFFSET,
        editDocument: editDocument
    };
})();
