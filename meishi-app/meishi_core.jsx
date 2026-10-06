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
        "デザイン番号": ["デザイン番号", "デザイン", "品番"],
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
        "URL":        ["URL", "ホームページ", "Webサイト"],
        // 以下は名刺に直接は入らない項目（処理結果の「要確認」に表示する）
        "モール":     ["モール"],
        "ふりがな":   ["ふりがな", "フリガナ"],
        "ロゴデータ": ["ロゴデータ", "ロゴ"],
        "自由行":     ["自由行", "行目"],
        "備考":       ["備考", "当店への備考"],
        "確認事項":   ["確認事項"],
        "注文者":     ["注文者", "注文者名"],
        // 注文通知アプリの［名刺を作成］から渡される指示
        "テンプレート": ["テンプレート"],
        "保存先":     ["保存先"]
    };

    // 名刺に差し込まない項目（「差し込み先がない」の警告から外す）
    var INFO_FIELDS = ["注文番号", "デザイン番号", "部署", "モール", "ふりがな", "ロゴデータ", "自由行", "備考", "確認事項",
                       "注文者", "テンプレート", "保存先"];

    // -----------------------------------------------------------------
    //  2. テンプレートに入っている「仮の文字」→ 項目名
    //     テンプレートの仮の文字が増えたら、ここに足していきます。
    //     ・空白（半角・全角）は無視して探します（鈴　木　太　郎 も鈴木太郎も同じ）
    //     ・spaced: true の項目は、仮の文字が1文字ずつ空けてあれば
    //       お客さんの名前も同じ空け方にそろえます
    //     ・wholeLine: true の項目は「その行がその文字だけ」のときだけ置き換えます
    // -----------------------------------------------------------------
    //     ・usedAs は「差し込み先あり」の判定に使う元の項目名
    //     ・○ と 〇 は同じ文字として探します。同じ項目の中では長い文字から先に探します
    var PLACEHOLDERS = [
        { field: "氏名",       spaced: true,
          texts: ["鈴木太郎", "鈴木花子", "鈴木一郎", "佐藤一郎", "海山川地", "中村絵美"] },
        // 「ロゴデータ」が無しなら LOGO の位置に会社名が入る（有りならロゴを手作業で配置）
        { field: "会社名",     wholeLine: true, logo: true,
          texts: ["LOGO", "Logo", "ROGO", "rogo", "L◉G◉"] },
        // 文字のロゴ（英語面では英字の会社名があればそちらを使う）
        { field: "会社名",     wholeLine: true, logo: true, altField: "会社名英字",
          texts: ["artcode", "アートコード"] },
        { field: "会社名",     wholeLine: true,
          texts: ["株式会社●●商事", "株式会社海山商事", "○○商事○○○企画課"] },
        // 「株式会社」と「○○商事」が別の行になっているデザイン
        { field: "会社名_前",  wholeLine: true, usedAs: "会社名", texts: ["株式会社"] },
        { field: "会社名_後",  wholeLine: true, usedAs: "会社名", texts: ["○○商事", "海山商事"] },
        { field: "肩書",       texts: ["代表取締役"], spaced: true },
        { field: "肩書",       wholeLine: true, spaced: true,
          texts: ["店長", "オーナー", "ショップオーナー", "取締役社長", "代表", "営業事務", "営業課長", "課長",
                  "保育士", "料理長", "料理研究家", "ライター", "シンガーソングライター", "スタイリスト",
                  "インストラクター", "司書補", "カメラマン", "バイヤー", "先生", "ボランティア"] },
        { field: "氏名英字",   texts: ["Ichiro Suzuki", "Taro Suzuki", "Hanako Suzuki", "Emi Nakamura"] },
        { field: "肩書英字",   texts: ["President"], wholeLine: true },
        { field: "住所1",
          texts: ["○○○県○○市○○町00-00-0", "○○○県○○市○○町0-00-0", "○○○県○○○○市○○○町1-1-1",
                  "○○○県○○○市○○○町1-2-3", "○○○県○○○市○○○町○○ー○ー○○", "○○県○○市○○町00-00-0",
                  "○○○○○○○○○○町000-0000", "○○○県○○市○○町"] },
        { field: "住所2",      texts: ["00-00-0○○○○000号", "○○○○○000号", "○○○000号"] },
        { field: "メール",     texts: ["ooooo@oooo.com"] },
        { field: "URL",        texts: ["http://www.0123456.jp/"] },
        { field: "英字住所1",  texts: ["6-1-1-3 Hirasaku,Yokosuka city,"] },
        { field: "英字住所2",  texts: ["Kanagawa 238-0032,Japan"] }
    ];

    // 会社名を「株式会社」と「残り」に分ける（「株式会社」の行が別になっているデザイン用）
    var COMPANY_PREFIX = /^(株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|公益社団法人|公益財団法人|医療法人社団|医療法人|社会福祉法人|学校法人|特定非営利活動法人|NPO法人)[ \t\u3000]*/;

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
        return String(s).replace(/^[ \t\u3000\r\n]+|[ \t\u3000\r\n]+$/g, "");
    }

    function escapeRegex(s) {
        return s.replace(/[\\^$.*+?()[\]{}|\/-]/g, "\\$&");
    }

    // "Tel" → /T[ \t　]*e[ \t　]*l/ のように、文字の間の空白を許す正規表現の文字列
    function looseSource(text) {
        var out = [];
        for (var i = 0; i < text.length; i++) {
            var c = text.charAt(i);
            if (/[ \t\u3000]/.test(c)) continue;
            out.push(c === "○" || c === "〇" ? "[○〇]" : escapeRegex(c));
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
        if (v["部署"]) v["肩書"] = v["肩書"] ? v["部署"] + "\u3000" + v["肩書"] : v["部署"];
        var company = v["会社名"] || "";
        var m = company.match(COMPANY_PREFIX);
        v["会社名_前"] = m ? m[1] : "";
        v["会社名_後"] = m ? company.substring(m[0].length) : company;
        return v;
    }

    // その文字が「LOGO」などロゴの仮の文字か（LOGO 横のマークを探すときに使う）
    function isLogoText(text) {
        var t = String(text).replace(/[ \t\u3000\r\n]/g, "");
        for (var k = 0; k < PLACEHOLDERS.length; k++) {
            if (!PLACEHOLDERS[k].logo) continue;
            for (var i = 0; i < PLACEHOLDERS[k].texts.length; i++) {
                if (PLACEHOLDERS[k].texts[i] === t) return true;
            }
        }
        return false;
    }

    // ロゴデータが「有り」の注文か
    function hasLogoData(rec) {
        return /^[ \t\u3000]*有/.test(rec["ロゴデータ"] || "");
    }

    // ===== 差し込み位置を探す =============================================

    // 文字列 contents（1つのテキストの中身）について、どこを何に置き換えるかを返す。
    //   edits:  [{ start, end, text, field }]   （start〜end を text に置き換える）
    //   used:   この中で見つかった項目名の一覧
    //   leftoverRemoved: 認識できない仮の文字（○○○・000- など）が残るため消した行
    //   opts.keepLeftover が true のときは、その行を消さずに leftover に入れる（検査ツール用）
    function planEdits(contents, rec, opts) {
        opts = opts || {};
        var values = prepareValues(rec);
        values.__logo = hasLogoData(rec);
        var edits = [], used = [], leftoverRemoved = [], leftover = [];

        // 行ごとに、置き換えるところと「行ごと消すか」を決める
        var lines = [];
        var lineStart = 0;
        while (lineStart <= contents.length) {
            var lineEnd = lineStart;
            while (lineEnd < contents.length && !LINE_BREAK.test(contents.charAt(lineEnd))) lineEnd++;
            var line = contents.substring(lineStart, lineEnd);
            var lineEdits = planLine(line, values, used);

            // テンプレートの文字のうち、置き換えなかった部分に仮の文字が残っているか
            // （お客さんの入力した値は数えない。「03-1000-2000」の「000-」などを誤って消さないため）
            var blanks = [];
            for (var b = 0; b < lineEdits.length; b++) {
                blanks.push({ start: lineEdits[b].start, end: lineEdits[b].end, text: "" });
            }
            var stillPlaceholder = hasLeftover(applyEditsToString(line, blanks));
            if (stillPlaceholder) {
                if (opts.keepLeftover) leftover.push(line);
                else leftoverRemoved.push(line);
            }
            // 消すものばかりで何も残らない、または未入力の仮の文字が残る → 行ごと消す
            var remove = (stillPlaceholder && !opts.keepLeftover) ||
                         (lineEdits.length > 0 && trim(applyEditsToString(line, lineEdits)) === "");
            lines.push({ start: lineStart, end: lineEnd, edits: lineEdits, remove: remove });
            if (lineEnd >= contents.length) break;
            lineStart = lineEnd + 1;
        }

        for (var i = 0; i < lines.length; i++) {
            var L = lines[i];
            if (!L.remove) {
                for (var k = 0; k < L.edits.length; k++) {
                    edits.push({ start: L.edits[k].start + L.start, end: L.edits[k].end + L.start,
                                 text: L.edits[k].text, field: L.edits[k].field });
                }
                continue;
            }
            // 後ろに残る行があれば「この行＋後ろの改行」を消す
            var keptAfter = false;
            for (var j = i + 1; j < lines.length; j++) if (!lines[j].remove) { keptAfter = true; break; }
            if (keptAfter) {
                edits.push({ start: L.start, end: L.end + 1, text: "", field: "(行削除)" });
            } else {
                // 最後まで消す行が続く → 前の改行からテキストの最後までをまとめて消す
                edits.push({ start: L.start > 0 ? L.start - 1 : 0, end: contents.length, text: "", field: "(行削除)" });
                break;
            }
        }
        edits.sort(function (a, b) { return a.start - b.start; });
        return { edits: edits, used: used, leftoverRemoved: leftoverRemoved, leftover: leftover };
    }

    // コロンのない見出しのときは、後ろが本当に電話番号などかを確かめる（「Web デザイン」などを避ける）
    function looksLikeValue(field, rest) {
        if (field === "メール") return /@/.test(rest);
        if (field === "URL") return /^(https?|www)/i.test(rest);
        return /^[0-9０-９○〇+(（]/.test(rest);
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
        function add(s, e, text, field, usedAs) {
            edits.push({ start: s, end: e, text: text, field: field });
            taken.push([s, e]);
            if (!inArray(used, usedAs || field)) used.push(usedAs || field);
        }
        function val(field) { return values[field] ? values[field] : ""; }

        // --- (a) 「Tel : 000-...」のような見出し付きの値 ---
        var found = [];
        for (var L = 0; L < LABELS.length; L++) {
            for (var w = 0; w < LABELS[L].words.length; w++) {
                // 「Tel :」のようにコロンがあるか、「電話 〇〇〇」のように空白のあとに値が続く
                var re = new RegExp("(^|" + WS + ")(" + looseSource(LABELS[L].words[w]) + ")(" + WS + "*[:：]" + WS + "*|" + WS + "+)", "g");
                var m;
                while ((m = re.exec(line)) !== null) {
                    if (!/[:：]/.test(m[3]) && !looksLikeValue(LABELS[L].field, line.substring(m.index + m[0].length))) continue;
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
            while (vEnd > found[i].valueStart && /[ \t\u3000]/.test(line.charAt(vEnd - 1))) vEnd--;
            if (vEnd <= found[i].valueStart) continue;  // 値がない見出しは触らない
            var v = val(found[i].field);
            if (v !== "") {
                add(found[i].valueStart, vEnd, v, found[i].field);
            } else {
                // 値が空 → 見出しごと消す（前の空白も消す）
                var s = found[i].labelStart;
                while (s > 0 && /[ \t\u3000]/.test(line.charAt(s - 1))) s--;
                add(s, vEnd, "", found[i].field);
            }
        }

        // --- (a2) 見出しだけの行（「E-mail」の値が別のテキストになっているデザイン）---
        //     値が空なら見出しも消す。値があれば見出しはそのまま
        if (found.length === 0) {
            for (var L2 = 0; L2 < LABELS.length; L2++) {
                for (var w2 = 0; w2 < LABELS[L2].words.length; w2++) {
                    var only = new RegExp("^" + WS + "*" + looseSource(LABELS[L2].words[w2]) + WS + "*[:：]?" + WS + "*$");
                    if (only.test(line) && val(LABELS[L2].field) === "" && isFree(0, line.length)) {
                        add(0, line.length, "", LABELS[L2].field);
                    }
                }
            }
            if (/^[ \t\u3000]*〒[ \t\u3000]*$/.test(line) && val("郵便番号") === "" && isFree(0, line.length)) {
                add(0, line.length, "", "郵便番号");
            }
        }

        // --- (b) 見出しのない URL・メール・郵便番号 ---
        var patterns = [
            { field: "URL", re: /https?:\/\/[^ \t\u3000]+/g },
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
                    while (ps > 0 && /[ \t\u3000:：]/.test(line.charAt(ps - 1))) ps--;
                }
                add(ps, pe, pv, patterns[p].field);
            }
        }
        var zipRe = new RegExp("〒" + WS + "*([0-9０-９○〇]" + WS + "*){3}[-‐－ー]" + WS + "*([0-9０-９○〇]" + WS + "*){3}[0-9０-９○〇]", "g");
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
            if (ph.logo && values.__logo) continue;   // ロゴ有り → LOGO はそのまま
            var texts = ph.texts.slice(0).sort(function (a, b) { return b.length - a.length; });
            for (var t = 0; t < texts.length; t++) {
                var src = looseSource(texts[t]);
                if (ph.wholeLine) src = "^" + WS + "*" + src + WS + "*$";
                var pre = new RegExp(src, "g");
                var mm;
                while ((mm = pre.exec(line)) !== null) {
                    if (mm[0].length === 0) { pre.lastIndex++; continue; }
                    var ms = mm.index, me = mm.index + mm[0].length;
                    if (ph.wholeLine) {   // 前後の空白は残す
                        while (ms < me && /[ \t\u3000]/.test(line.charAt(ms))) ms++;
                        while (me > ms && /[ \t\u3000]/.test(line.charAt(me - 1))) me--;
                    }
                    if (!isFree(ms, me)) continue;
                    var field = (ph.altField && val(ph.altField) !== "") ? ph.altField : ph.field;
                    var nv = val(field);
                    if (nv !== "" && ph.spaced) nv = matchSpacing(line.substring(ms, me), nv);
                    // 値が空のときは「  : ooooo@...」の「:」も一緒に消す
                    if (nv === "") while (ms > 0 && /[ \t\u3000:：]/.test(line.charAt(ms - 1))) ms--;
                    add(ms, me, nv, field, ph.usedAs);
                }
            }
        }
        return edits;
    }

    // 仮の文字が「鈴　木　太　郎」のように1文字ずつ空いていたら、
    // お客さんの名前「山田 花子」も「山　田　花　子」にそろえる
    function matchSpacing(placeholderText, value) {
        var m = placeholderText.match(/^[^ \t\u3000]([ \t\u3000]+)[^ \t\u3000]/);
        if (!m) return value;
        var chars = value.replace(/[ \t\u3000]+/g, "");
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
        var out = [];
        for (var k in rec) {
            if (!rec.hasOwnProperty(k) || inArray(INFO_FIELDS, k)) continue;
            if (k === "会社名" && hasLogoData(rec)) continue;
            if (rec[k] !== "" && !inArray(used, k)) out.push(k);
        }
        return out;
    }

    function hasLeftover(text) {
        for (var i = 0; i < LEFTOVER_PATTERNS.length; i++) if (LEFTOVER_PATTERNS[i].test(text)) return true;
        return false;
    }

    // ===== 注文通知アプリからの指示ファイル ================================
    //  文字コードの違いで化けないよう、英数字だけで書かれている。
    //    1行目: MEISHIJOB1
    //    「項目名<タブ>値」を1行ずつ（どちらも %E5%90%8D のような UTF-8 のパーセント表記）
    //    空の行で次の注文に区切る
    function parseJob(text) {
        var lines = String(text).replace(/^\uFEFF/, "").split(/\r\n|\r|\n/);
        if (trim(lines[0]) !== "MEISHIJOB1") return null;
        var records = [], rec = null;
        for (var i = 1; i < lines.length; i++) {
            var line = lines[i];
            if (trim(line) === "") { rec = null; continue; }
            var tab = line.indexOf("\t");
            if (tab < 0) continue;
            if (!rec) { rec = {}; records.push(rec); }
            rec[decodeURIComponent(line.substring(0, tab))] = decodeURIComponent(line.substring(tab + 1));
        }
        return records;
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
        return s.replace(/[ \t\u3000]+/g, "").replace(/\.ai$/i, "").toLowerCase();
    }

    // ===== ファイル名 =====================================================

    // 「注文番号_名前.ai」 ファイル名に使えない文字や空白は取り除く
    function makeFileName(rec) {
        function clean(s) {
            return String(s || "").replace(/[\\\/:*?"<>|\r\n\t]/g, "").replace(/[ \u3000]+/g, "");
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
        parseJob: parseJob,
        rowsToRecords: rowsToRecords,
        INFO_FIELDS: INFO_FIELDS,
        prepareValues: prepareValues,
        hasLogoData: hasLogoData,
        isLogoText: isLogoText,
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
