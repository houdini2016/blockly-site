// =====================================================================
//  名刺自動作成 — 共通ロジック（Illustrator に依存しない部分）
//
//  Illustrator CS6 の ExtendScript でも動くように、古い JavaScript (ES3)
//  の書き方だけを使っています（let / const / => / forEach / JSON は不可）。
//  同じファイルを Node.js のテスト (test/test_core.js) からも読み込みます。
// =====================================================================

var MeishiCore = (function () {

    // -----------------------------------------------------------------
    //  1. 注文CSVの列名 → このアプリ内の項目名
    //     楽天・Yahoo! のCSVや手作りのCSVで列名が違っても、ここに
    //     別名を足せば読めるようになります。
    // -----------------------------------------------------------------
    var FIELD_ALIASES = {
        "注文番号":   ["注文番号", "受注番号", "注文ID", "OrderId"],
        "デザイン番号": ["デザイン番号", "デザイン", "テンプレート", "品番"],
        "会社名":     ["会社名", "社名", "屋号"],
        "部署":       ["部署", "部署名"],
        "肩書":       ["肩書", "肩書き", "役職"],
        "氏名":       ["氏名", "名前", "お名前", "名刺の名前"],
        "氏名英字":   ["氏名英字", "ローマ字", "氏名ローマ字", "英字氏名"],
        "肩書英字":   ["肩書英字", "英字肩書", "役職英字"],
        "会社名英字": ["会社名英字", "英字会社名"],
        "郵便番号":   ["郵便番号", "〒"],
        "住所1":      ["住所1", "住所", "住所１"],
        "住所2":      ["住所2", "住所２", "建物名"],
        "英字住所1":  ["英字住所1", "英字住所", "英字住所１"],
        "英字住所2":  ["英字住所2", "英字住所２"],
        "TEL":        ["TEL", "Tel", "電話", "電話番号"],
        "FAX":        ["FAX", "Fax", "ファックス"],
        "携帯":       ["携帯", "携帯電話", "Mobile"],
        "メール":     ["メール", "メールアドレス", "E-mail", "Email"],
        "URL":        ["URL", "ホームページ", "Webサイト"]
    };

    // -----------------------------------------------------------------
    //  2. テンプレートに入っている「仮の文字」→ 項目名
    //     テンプレートの仮の文字が増えたら、ここに足していきます。
    //     ・空白（半角・全角）は無視して探します（鈴　木　太　郎 も鈴木太郎も同じ）
    //     ・spaced: true の項目は、仮の文字が1文字ずつ空けてあれば
    //       お客さんの名前も同じ空け方にそろえます
    //     ・wholeLine: true の項目は「その行がその文字だけ」のときだけ置き換えます
    // -----------------------------------------------------------------
    var PLACEHOLDERS = [
        { field: "氏名",       texts: ["鈴木太郎", "鈴木花子", "鈴木一郎"], spaced: true },
        { field: "肩書",       texts: ["代表取締役"] },
        { field: "氏名英字",   texts: ["Ichiro Suzuki", "Taro Suzuki", "Hanako Suzuki"] },
        { field: "肩書英字",   texts: ["President"], wholeLine: true },
        { field: "会社名英字", texts: ["artcode"], wholeLine: true },
        { field: "住所1",      texts: ["○○○県○○市○○町00-00-0"] },
        { field: "住所2",      texts: ["○○○○○000号"] },
        { field: "英字住所1",  texts: ["6-1-1-3 Hirasaku,Yokosuka city,"] },
        { field: "英字住所2",  texts: ["Kanagawa 238-0032,Japan"] }
    ];

    // -----------------------------------------------------------------
    //  3. 「Tel :」「Fax :」などの見出しの後ろにある値を置き換える項目
    // -----------------------------------------------------------------
    var LABELS = [
        { field: "TEL",    words: ["Tel", "TEL", "電話", "ＴＥＬ"] },
        { field: "FAX",    words: ["Fax", "FAX", "ＦＡＸ"] },
        { field: "携帯",   words: ["Mobile", "Mob", "Cell", "携帯"] },
        { field: "メール", words: ["E-mail", "Email", "Mail"] },
        { field: "URL",    words: ["URL", "Web", "HP"] }
    ];

    // 置き換え後に、この文字が残っていたら「置き換え漏れかも」と警告する
    var LEFTOVER_PATTERNS = [/[○〇]/, /000-/, /ooooo@/, /0123456/];

    var WS = "[ \\t\\u3000]";           // 空白（半角・全角・タブ）
    var LINE_BREAK = /[\r\n\u0003]/;   // Illustrator の改行（\r）と強制改行（\u0003）

    // ===== 小さな道具 =====================================================

    function trim(s) {
        return String(s).replace(/^[ \t　\r\n]+|[ \t　\r\n]+$/g, "");
    }

    function escapeRegex(s) {
        return s.replace(/[\\^$.*+?()[\]{}|\/-]/g, "\\$&");
    }

    // "Tel" → /T[ \t　]*e[ \t　]*l/ のように、文字の間の空白を許す正規表現の文字列
    function looseSource(text) {
        var out = [];
        for (var i = 0; i < text.length; i++) {
            var c = text.charAt(i);
            if (/[ \t　]/.test(c)) continue;
            out.push(escapeRegex(c));
        }
        return out.join(WS + "*");
    }

    function inArray(arr, v) {
        for (var i = 0; i < arr.length; i++) if (arr[i] === v) return true;
        return false;
    }

    // ===== CSV ============================================================

    // CSVの文字列 → 行の配列（各行は列の配列）。"..." で囲んだ値、値の中の改行・カンマにも対応。
    function parseCSV(text) {
        if (text.charCodeAt(0) === 0xFEFF) text = text.substring(1);
        var rows = [], row = [], field = "", inQuotes = false;
        for (var i = 0; i < text.length; i++) {
            var c = text.charAt(i);
            if (inQuotes) {
                if (c === '"') {
                    if (text.charAt(i + 1) === '"') { field += '"'; i++; }
                    else inQuotes = false;
                } else field += c;
            } else if (c === '"') {
                inQuotes = true;
            } else if (c === ",") {
                row.push(field); field = "";
            } else if (c === "\r" || c === "\n") {
                if (c === "\r" && text.charAt(i + 1) === "\n") i++;
                row.push(field); field = "";
                rows.push(row); row = [];
            } else field += c;
        }
        if (field !== "" || row.length > 0) { row.push(field); rows.push(row); }
        // 空行を捨てる
        var out = [];
        for (var r = 0; r < rows.length; r++) {
            if (trim(rows[r].join("")) !== "") out.push(rows[r]);
        }
        return out;
    }

    // 1行目を見出しとして、各行を { 項目名: 値 } に変える
    function rowsToRecords(rows) {
        if (rows.length === 0) return { records: [], unknownHeaders: [] };
        var header = rows[0], colField = [], unknown = [];
        for (var c = 0; c < header.length; c++) {
            var h = trim(header[c]), found = null;
            for (var f in FIELD_ALIASES) {
                if (FIELD_ALIASES.hasOwnProperty(f) && inArray(FIELD_ALIASES[f], h)) { found = f; break; }
            }
            colField.push(found);
            if (!found && h !== "") unknown.push(h);
        }
        var records = [];
        for (var r = 1; r < rows.length; r++) {
            var rec = {};
            for (var k = 0; k < colField.length; k++) {
                if (colField[k] && rows[r][k] !== undefined) rec[colField[k]] = trim(rows[r][k]);
            }
            records.push(rec);
        }
        return { records: records, unknownHeaders: unknown };
    }

    // 部署は肩書の前に付ける（例: 営業部　部長）
    function prepareValues(rec) {
        var v = {};
        for (var k in rec) if (rec.hasOwnProperty(k)) v[k] = rec[k];
        if (v["部署"]) v["肩書"] = v["肩書"] ? v["部署"] + "　" + v["肩書"] : v["部署"];
        return v;
    }

    // ===== 差し込み位置を探す =============================================

    // 文字列 contents（1つのテキストの中身）について、どこを何に置き換えるかを返す。
    //   edits:  [{ start, end, text, field }]   （start〜end を text に置き換える）
    //   used:   この中で見つかった項目名の一覧
    function planEdits(contents, rec) {
        var values = prepareValues(rec);
        var edits = [], used = [];

        // 行ごとに処理する
        var lineStart = 0;
        while (lineStart <= contents.length) {
            var lineEnd = lineStart;
            while (lineEnd < contents.length && !LINE_BREAK.test(contents.charAt(lineEnd))) lineEnd++;
            var line = contents.substring(lineStart, lineEnd);
            var lineEdits = planLine(line, values, used);

            // その行で消すものばかりで、何も残らない → 行ごと消す（改行も一緒に）
            if (lineEdits.length > 0 && trim(applyEditsToString(line, lineEdits)) === "") {
                var delStart = lineStart, delEnd = lineEnd;
                if (lineEnd < contents.length) delEnd = lineEnd + 1;          // 後ろの改行
                else if (lineStart > 0) delStart = lineStart - 1;            // 最後の行なら前の改行
                edits.push({ start: delStart, end: delEnd, text: "", field: "(行削除)" });
            } else {
                for (var i = 0; i < lineEdits.length; i++) {
                    edits.push({
                        start: lineEdits[i].start + lineStart,
                        end: lineEdits[i].end + lineStart,
                        text: lineEdits[i].text,
                        field: lineEdits[i].field
                    });
                }
            }
            if (lineEnd >= contents.length) break;
            lineStart = lineEnd + 1;
        }
        edits.sort(function (a, b) { return a.start - b.start; });
        return { edits: edits, used: used };
    }

    function planLine(line, values, used) {
        var edits = [];
        var taken = [];  // すでに置き換え対象になった範囲（二重に置き換えないため）

        function isFree(s, e) {
            for (var i = 0; i < taken.length; i++) {
                if (s < taken[i][1] && e > taken[i][0]) return false;
            }
            return true;
        }
        function add(s, e, text, field) {
            edits.push({ start: s, end: e, text: text, field: field });
            taken.push([s, e]);
            if (!inArray(used, field)) used.push(field);
        }
        function val(field) { return values[field] ? values[field] : ""; }

        // --- (a) 「Tel : 000-...」のような見出し付きの値 ---
        var found = [];
        for (var L = 0; L < LABELS.length; L++) {
            for (var w = 0; w < LABELS[L].words.length; w++) {
                var re = new RegExp("(^|" + WS + ")(" + looseSource(LABELS[L].words[w]) + ")" + WS + "*[:：]" + WS + "*", "g");
                var m;
                while ((m = re.exec(line)) !== null) {
                    var labelStart = m.index + m[1].length;
                    var dup = false;
                    for (var d = 0; d < found.length; d++) if (found[d].labelStart === labelStart) dup = true;
                    if (!dup) found.push({ field: LABELS[L].field, labelStart: labelStart, valueStart: m.index + m[0].length });
                }
            }
        }
        found.sort(function (a, b) { return a.labelStart - b.labelStart; });
        for (var i = 0; i < found.length; i++) {
            var vEnd = (i + 1 < found.length) ? found[i + 1].labelStart : line.length;
            while (vEnd > found[i].valueStart && /[ \t　]/.test(line.charAt(vEnd - 1))) vEnd--;
            if (vEnd <= found[i].valueStart) continue;  // 値がない見出しは触らない
            var v = val(found[i].field);
            if (v !== "") {
                add(found[i].valueStart, vEnd, v, found[i].field);
            } else {
                // 値が空 → 見出しごと消す（前の空白も消す）
                var s = found[i].labelStart;
                while (s > 0 && /[ \t　]/.test(line.charAt(s - 1))) s--;
                add(s, vEnd, "", found[i].field);
            }
        }

        // --- (b) 見出しのない URL・メール・郵便番号 ---
        var patterns = [
            { field: "URL", re: /https?:\/\/[^ \t　]+/g },
            { field: "メール", re: /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g }
        ];
        for (var p = 0; p < patterns.length; p++) {
            var pm;
            patterns[p].re.lastIndex = 0;
            while ((pm = patterns[p].re.exec(line)) !== null) {
                var ps = pm.index, pe = pm.index + pm[0].length;
                if (!isFree(ps, pe)) continue;
                var pv = val(patterns[p].field);
                if (pv === "") {
                    // 「  : ooooo@...」のように前に「:」だけ残る場合も一緒に消す
                    while (ps > 0 && /[ \t　:：]/.test(line.charAt(ps - 1))) ps--;
                }
                add(ps, pe, pv, patterns[p].field);
            }
        }
        var zipRe = new RegExp("〒" + WS + "*([0-9０-９]" + WS + "*){3}[-‐－ー]" + WS + "*([0-9０-９]" + WS + "*){3}[0-9０-９]", "g");
        var zm;
        while ((zm = zipRe.exec(line)) !== null) {
            var zs = zm.index, ze = zm.index + zm[0].length;
            if (!isFree(zs, ze)) continue;
            var zv = val("郵便番号");
            if (zv === "") add(zs, ze, "", "郵便番号");
            else add(zs + 1, ze, zv.replace(/^〒/, ""), "郵便番号");   // 〒 は残す
        }

        // --- (c) テンプレートの仮の文字 ---
        for (var k = 0; k < PLACEHOLDERS.length; k++) {
            var ph = PLACEHOLDERS[k];
            for (var t = 0; t < ph.texts.length; t++) {
                var src = looseSource(ph.texts[t]);
                if (ph.wholeLine) src = "^" + WS + "*" + src + WS + "*$";
                var pre = new RegExp(src, "g");
                var mm;
                while ((mm = pre.exec(line)) !== null) {
                    if (mm[0].length === 0) { pre.lastIndex++; continue; }
                    var ms = mm.index, me = mm.index + mm[0].length;
                    if (ph.wholeLine) {   // 前後の空白は残す
                        while (ms < me && /[ \t　]/.test(line.charAt(ms))) ms++;
                        while (me > ms && /[ \t　]/.test(line.charAt(me - 1))) me--;
                    }
                    if (!isFree(ms, me)) continue;
                    var nv = val(ph.field);
                    if (nv !== "" && ph.spaced) nv = matchSpacing(line.substring(ms, me), nv);
                    add(ms, me, nv, ph.field);
                }
            }
        }
        return edits;
    }

    // 仮の文字が「鈴　木　太　郎」のように1文字ずつ空いていたら、
    // お客さんの名前「山田 花子」も「山　田　花　子」にそろえる
    function matchSpacing(placeholderText, value) {
        var m = placeholderText.match(/^[^ \t　]([ \t　]+)[^ \t　]/);
        if (!m) return value;
        var chars = value.replace(/[ \t　]+/g, "");
        var out = [];
        for (var i = 0; i < chars.length; i++) out.push(chars.charAt(i));
        return out.join(m[1]);
    }

    // edits を文字列に当てはめた結果を返す（後ろから置き換える）
    function applyEditsToString(s, edits) {
        var sorted = edits.slice(0).sort(function (a, b) { return b.start - a.start; });
        for (var i = 0; i < sorted.length; i++) {
            s = s.substring(0, sorted[i].start) + sorted[i].text + s.substring(sorted[i].end);
        }
        return s;
    }

    // ===== チェック =======================================================

    // 値が入っているのに、テンプレートに差し込み先がなかった項目
    function unusedFields(rec, used) {
        var skip = ["注文番号", "デザイン番号", "部署"];
        var out = [];
        for (var k in rec) {
            if (!rec.hasOwnProperty(k) || inArray(skip, k)) continue;
            if (rec[k] !== "" && !inArray(used, k)) out.push(k);
        }
        return out;
    }

    function hasLeftover(text) {
        for (var i = 0; i < LEFTOVER_PATTERNS.length; i++) if (LEFTOVER_PATTERNS[i].test(text)) return true;
        return false;
    }

    // ===== 文字コード・デザイン番号 ========================================

    // バイト列（1文字=1バイトの文字列）が UTF-8 か Shift_JIS かを判定する。
    // Excel で保存した日本語CSVは Shift_JIS、「CSV UTF-8」で保存すると UTF-8 になります。
    function detectEncoding(bytes) {
        if (bytes.charCodeAt(0) === 0xEF && bytes.charCodeAt(1) === 0xBB && bytes.charCodeAt(2) === 0xBF) return "UTF-8";
        var i = 0, n = bytes.length, sawMultiByte = false;
        while (i < n) {
            var b = bytes.charCodeAt(i);
            var extra = b < 0x80 ? 0 : (b >= 0xC2 && b <= 0xDF) ? 1 : (b >= 0xE0 && b <= 0xEF) ? 2 : (b >= 0xF0 && b <= 0xF4) ? 3 : -1;
            if (extra < 0) return "Shift_JIS";
            for (var k = 1; k <= extra; k++) {
                var c = bytes.charCodeAt(i + k);
                if (i + k >= n || c < 0x80 || c > 0xBF) return "Shift_JIS";
            }
            if (extra > 0) sawMultiByte = true;
            i += extra + 1;
        }
        return sawMultiByte ? "UTF-8" : "Shift_JIS";
    }

    // デザイン番号やファイル名を比べやすい形にする（全角英数→半角、小文字、空白なし、.ai なし）
    function normalizeKey(s) {
        s = String(s || "").replace(/[！-～]/g, function (c) {
            return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
        });
        return s.replace(/[ \t　]+/g, "").replace(/\.ai$/i, "").toLowerCase();
    }

    // ===== ファイル名 =====================================================

    // 「注文番号_名前.ai」 ファイル名に使えない文字や空白は取り除く
    function makeFileName(rec) {
        function clean(s) {
            return String(s || "").replace(/[\\\/:*?"<>|\r\n\t]/g, "").replace(/[ 　]+/g, "");
        }
        var order = clean(rec["注文番号"]) || "注文番号なし";
        var name = clean(rec["氏名"]) || clean(rec["氏名英字"]) || "名前なし";
        return order + "_" + name + ".ai";
    }

    return {
        FIELD_ALIASES: FIELD_ALIASES,
        PLACEHOLDERS: PLACEHOLDERS,
        LABELS: LABELS,
        trim: trim,
        parseCSV: parseCSV,
        rowsToRecords: rowsToRecords,
        prepareValues: prepareValues,
        planEdits: planEdits,
        applyEditsToString: applyEditsToString,
        matchSpacing: matchSpacing,
        unusedFields: unusedFields,
        hasLeftover: hasLeftover,
        detectEncoding: detectEncoding,
        normalizeKey: normalizeKey,
        makeFileName: makeFileName
    };
})();

// Node.js のテストから読み込むとき用
if (typeof module !== "undefined" && module.exports) module.exports = MeishiCore;
