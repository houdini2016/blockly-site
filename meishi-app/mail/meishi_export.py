"""注文通知アプリの注文データから、名刺を作るための指示を作る部品。

注文通知アプリ（chumon_notifier.py）が整理した注文詳細（_parse_detail_items の結果）を
名刺の項目（氏名・肩書・住所・TEL…）に振り分け、Illustrator スクリプト
（meishi_job.jsx）が読む CSV（どのテンプレートに流し込み、どこへ保存するか）を書き出します。

この部品はメールにもインターネットにも接続しません（受け取った文字を整理するだけ）。
"""
import csv
import json
import os
import re
import subprocess

# 作った名刺の保存先
OUTPUT_DIR = os.path.expanduser("~/Library/CloudStorage/Dropbox/1名刺表札作業用/1_新規ai")

# meishi_job.jsx が読む指示ファイル（Illustrator の Folder.userData の中）
JOB_FILE = os.path.expanduser("~/Library/Application Support/meishi_job.csv")

# 前回テンプレートを選んだフォルダを覚えておくファイル
PREFS_FILE = os.path.expanduser("~/.chumon_notifier_meishi.json")

# 書き出す列（順番どおり）
CSV_COLUMNS = [
    "注文番号", "モール", "注文者", "テンプレート", "保存先",
    "会社名", "部署", "肩書", "氏名", "ふりがな", "氏名英字", "肩書英字",
    "郵便番号", "住所1", "住所2", "TEL", "FAX", "携帯", "メール", "URL",
    "ロゴデータ", "自由行", "備考", "確認事項",
]

# 注文通知アプリの項目名 → 名刺の項目名
LABEL_TO_FIELD = {
    "会社名": "会社名",
    "部署名": "部署",
    "肩書き": "肩書",
    "肩書き(英語)": "肩書英字",
    "氏名": "氏名",
    "ふりがな": "ふりがな",
    "当店への備考": "備考",
}

_COLON = "[：:]"
_CONTACT = [
    ("TEL", re.compile(r"^TEL" + _COLON + r"\s*(.+)", re.I)),
    ("FAX", re.compile(r"^FAX" + _COLON + r"\s*(.+)", re.I)),
    ("携帯", re.compile(r"^(?:Mobile|携帯)" + _COLON + r"\s*(.+)", re.I)),
    ("メール", re.compile(r"^E-?mail" + _COLON + r"\s*(.+)", re.I)),
    ("URL", re.compile(r"^(?:WEB|URL|HP)" + _COLON + r"\s*(.+)", re.I)),
]
_PHONE = re.compile(r"^\+?[\d\-()（） ]{10,16}$")


def _add_note(card, text):
    card["確認事項"] = (card["確認事項"] + " / " if card["確認事項"] else "") + text


def _split_address(card, lines):
    """住所の行を「住所1（都道府県〜番地）」「住所2（建物名など）」に分ける。"""
    if not lines:
        return
    if len(lines) >= 3 or (len(lines) == 2 and re.search(r"[都道府県市区町村郡]$", lines[0])):
        # 楽天の「都道府県・市区町村」＋「続き1」はつなげて1行目にする
        head, rest = lines[0] + lines[1], lines[2:]
    else:
        head, rest = lines[0], lines[1:]
    card["住所1"] = head
    card["住所2"] = "　".join(rest)
    if len(rest) > 1:
        _add_note(card, "住所が4行以上あります（住所2にまとめました）")


def _read_address_block(card, block):
    addr = []
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("〒"):
            card["郵便番号"] = line.lstrip("〒").strip()
            continue
        for field, pat in _CONTACT:
            m = pat.match(line)
            if m:
                card[field] = m.group(1).strip()
                if field == "URL":
                    card[field] = re.sub(r"^(https?):?//", r"\1://", card[field])
                break
        else:
            if re.match(r"^https?:?//", line):
                # 注文通知アプリの整形で「https//」になっていることがあるので戻す
                card["URL"] = re.sub(r"^(https?):?//", r"\1://", line)
            elif _PHONE.match(line):
                field = "携帯" if re.match(r"^0[789]0", line) else "TEL"
                card[field] = line
                _add_note(card, f"見出しのない電話番号を{field}にしました: {line}")
            else:
                addr.append(line)
    _split_address(card, addr)


def _option_value(line):
    """「項目名（説明）※説明。値」「項目名：値」のような商品オプション行から値の部分を取り出す。

    注文通知アプリの整形で「:」が消えている場合もあるので、
    最後の「:」の後ろと、最後の「）」「。」の後ろのうち短い方を値とする。
    """
    tails = [re.split(r"[:：]", line)[-1].strip(), re.split(r"[）)。]", line)[-1].strip()]
    tails = [t for t in tails if t and t != line.strip()]
    return min(tails, key=len) if tails else ""


def card_from_order(order, items):
    """1件の注文を名刺の項目に振り分ける。

    order: 注文通知アプリの注文（order_id, mall, customer, product, detail を持つ dict）
    items: _parse_detail_items(order["detail"]) の結果
    """
    card = {c: "" for c in CSV_COLUMNS}
    card["注文番号"] = order.get("order_id", "")
    card["モール"] = order.get("mall", "")
    if card["モール"] != "Yahoo!":   # Yahoo! の注文メールには注文者名がない
        card["注文者"] = order.get("customer", "")
    free_lines, notes = [], []

    for it in items:
        label, value, group = it.get("label", ""), it.get("value", ""), it.get("group")
        if group == "address":
            _read_address_block(card, value)
        elif group == "lines":
            free_lines.extend(v for v in value.split("\n") if v.strip())
        elif label in LABEL_TO_FIELD:
            field = LABEL_TO_FIELD[label]
            card[field] = (card[field] + "\n" + value) if (field == "備考" and card[field]) else value
        elif value.startswith("[備考]"):
            body = value[len("[備考]"):].strip()
            if body:
                notes.append(body)
        elif "ロゴデータ" in value:
            card["ロゴデータ"] = _option_value(value)

    # 氏名のあとに（ふりがな）が付いている場合は分ける
    m = re.match(r"^(.+?)\s*[（(]([^()（）]+)[)）]\s*$", card["氏名"])
    if m:
        card["氏名"] = m.group(1).strip()
        if not card["ふりがな"]:
            card["ふりがな"] = m.group(2).strip()
    # ふりがな欄がローマ字なら英字氏名として使う
    if re.fullmatch(r"[A-Za-z][A-Za-z .\-']*", card["ふりがな"]):
        card["氏名英字"], card["ふりがな"] = card["ふりがな"], ""

    if free_lines:
        card["自由行"] = " / ".join(free_lines)
    if notes:
        card["備考"] = "\n".join(filter(None, [card["備考"]] + notes))
    if not card["氏名"]:
        _add_note(card, "氏名が見つかりません")
    return card


def _clean_name(s):
    """ファイル名に使えない文字と空白を取り除く。"""
    return re.sub(r"[\\/:*?\"<>|\s\u3000]+", "", s or "")


def output_path(card, folder=OUTPUT_DIR):
    """保存先: 注文番号_名刺の氏名（なければ会社名）_注文者氏名.ai

    Yahoo! は注文者名がないので「注文番号_氏名.ai」。同じ名前があれば _2, _3 … を付ける。
    """
    parts = [_clean_name(card.get("注文番号")) or "注文番号なし",
             _clean_name(card.get("氏名")) or _clean_name(card.get("会社名")) or "名前なし"]
    if _clean_name(card.get("注文者")):
        parts.append(_clean_name(card["注文者"]))
    base = os.path.join(folder, "_".join(parts))
    path, n = base + ".ai", 2
    while os.path.exists(path):
        path, n = f"{base}_{n}.ai", n + 1
    return path


def write_csv(path, cards):
    """CSV を書き出す（Excel でも文字化けしない UTF-8 BOM 付き）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
        w.writeheader()
        for card in cards:
            w.writerow({c: card.get(c, "") for c in CSV_COLUMNS})


def load_prefs():
    try:
        with open(PREFS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_prefs(prefs):
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False)
    except OSError:
        pass


# ----------------------------------------------------------------------
#  Illustrator を呼び出す（Mac 用）
# ----------------------------------------------------------------------

# 埋め込んだスクリプトを書き出す場所
JOB_SCRIPT = os.path.expanduser("~/Library/Application Support/meishi_job_run.jsx")


def install_job_script(path=JOB_SCRIPT):
    """埋め込んである Illustrator 用スクリプトを書き出して、その場所を返す。

    アプリの中の .jsx ファイルを探さないので、アプリをどこに置いても動く。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig") as f:   # BOM 付き（Illustrator が日本語を正しく読むため）
        f.write(JOB_JSX)
    return path


def run_illustrator_script(jsx_path):
    """Illustrator を前面に出して jsx を実行する（終わるのは待たない）。"""
    jsx_path = os.path.abspath(jsx_path).replace("\\", "\\\\").replace('"', '\\"')
    script = (
        'tell application id "com.adobe.illustrator"\n'
        "  activate\n"
        "  with timeout of 3600 seconds\n"
        f'    do javascript ((POSIX file "{jsx_path}") as alias)\n'
        "  end timeout\n"
        "end tell"
    )
    return subprocess.Popen(["osascript", "-e", script],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---- ここから自動生成（tools/bundle_jsx.py）。手で書き換えないでください ----
JOB_JSX = (
    '// =====================================================================\n'
    '//  名刺自動作成（注文通知アプリの［名刺を作成］ボタンから呼ばれるスクリプト）\n'
    '//\n'
    '//  注文通知アプリが書き出した「meishi_job.csv」を読み、1行ごとに\n'
    '//    1. 指定されたテンプレート(.ai)を開く\n'
    '//    2. 注文内容を流し込む\n'
    '//    3. 指定された名前で別名保存する\n'
    '//    4. そのまま Illustrator で開いておく\n'
    '//  最後に、確認してほしいこと（要確認）があれば表示します。\n'
    '//\n'
    '//  meishi_core.jsx・meishi_ai.jsx を同じフォルダに置いてください。\n'
    '// =====================================================================\n'
    '\n'
    '#target illustrator\n'
    '// =====================================================================\n'
    '//  名刺自動作成 — 共通ロジック（Illustrator に依存しない部分）\n'
    '//\n'
    '//  Illustrator CS6 の ExtendScript でも動くように、古い JavaScript (ES3)\n'
    '//  の書き方だけを使っています（let / const / => / forEach / JSON は不可）。\n'
    '//  同じファイルを Node.js のテスト (test/test_core.js) からも読み込みます。\n'
    '// =====================================================================\n'
    '\n'
    'var MeishiCore = (function () {\n'
    '\n'
    '    // -----------------------------------------------------------------\n'
    '    //  1. 注文CSVの列名 → このアプリ内の項目名\n'
    '    //     楽天・Yahoo! のCSVや手作りのCSVで列名が違っても、ここに\n'
    '    //     別名を足せば読めるようになります。\n'
    '    // -----------------------------------------------------------------\n'
    '    var FIELD_ALIASES = {\n'
    '        "注文番号":   ["注文番号", "受注番号", "注文ID", "OrderId"],\n'
    '        "デザイン番号": ["デザイン番号", "デザイン", "品番"],\n'
    '        "会社名":     ["会社名", "社名", "屋号"],\n'
    '        "部署":       ["部署", "部署名"],\n'
    '        "肩書":       ["肩書", "肩書き", "役職"],\n'
    '        "氏名":       ["氏名", "名前", "お名前", "名刺の名前"],\n'
    '        "氏名英字":   ["氏名英字", "ローマ字", "氏名ローマ字", "英字氏名"],\n'
    '        "肩書英字":   ["肩書英字", "英字肩書", "役職英字"],\n'
    '        "会社名英字": ["会社名英字", "英字会社名"],\n'
    '        "郵便番号":   ["郵便番号", "〒"],\n'
    '        "住所1":      ["住所1", "住所", "住所１"],\n'
    '        "住所2":      ["住所2", "住所２", "建物名"],\n'
    '        "英字住所1":  ["英字住所1", "英字住所", "英字住所１"],\n'
    '        "英字住所2":  ["英字住所2", "英字住所２"],\n'
    '        "TEL":        ["TEL", "Tel", "電話", "電話番号"],\n'
    '        "FAX":        ["FAX", "Fax", "ファックス"],\n'
    '        "携帯":       ["携帯", "携帯電話", "Mobile"],\n'
    '        "メール":     ["メール", "メールアドレス", "E-mail", "Email"],\n'
    '        "URL":        ["URL", "ホームページ", "Webサイト"],\n'
    '        // 以下は名刺に直接は入らない項目（処理結果の「要確認」に表示する）\n'
    '        "モール":     ["モール"],\n'
    '        "ふりがな":   ["ふりがな", "フリガナ"],\n'
    '        "ロゴデータ": ["ロゴデータ", "ロゴ"],\n'
    '        "自由行":     ["自由行", "行目"],\n'
    '        "備考":       ["備考", "当店への備考"],\n'
    '        "確認事項":   ["確認事項"],\n'
    '        "注文者":     ["注文者", "注文者名"],\n'
    '        // 注文通知アプリの［名刺を作成］から渡される指示\n'
    '        "テンプレート": ["テンプレート"],\n'
    '        "保存先":     ["保存先"]\n'
    '    };\n'
    '\n'
    '    // 名刺に差し込まない項目（「差し込み先がない」の警告から外す）\n'
    '    var INFO_FIELDS = ["注文番号", "デザイン番号", "部署", "モール", "ふりがな", "ロゴデータ", "自由行", "備考", "確認事項",\n'
    '                       "注文者", "テンプレート", "保存先"];\n'
    '\n'
    '    // -----------------------------------------------------------------\n'
    '    //  2. テンプレートに入っている「仮の文字」→ 項目名\n'
    '    //     テンプレートの仮の文字が増えたら、ここに足していきます。\n'
    '    //     ・空白（半角・全角）は無視して探します（鈴\u3000木\u3000太\u3000郎 も鈴木太郎も同じ）\n'
    '    //     ・spaced: true の項目は、仮の文字が1文字ずつ空けてあれば\n'
    '    //       お客さんの名前も同じ空け方にそろえます\n'
    '    //     ・wholeLine: true の項目は「その行がその文字だけ」のときだけ置き換えます\n'
    '    // -----------------------------------------------------------------\n'
    '    //     ・usedAs は「差し込み先あり」の判定に使う元の項目名\n'
    '    //     ・○ と 〇 は同じ文字として探します。同じ項目の中では長い文字から先に探します\n'
    '    var PLACEHOLDERS = [\n'
    '        { field: "氏名",       spaced: true,\n'
    '          texts: ["鈴木太郎", "鈴木花子", "鈴木一郎", "佐藤一郎", "海山川地", "中村絵美"] },\n'
    '        // 「ロゴデータ」が無しなら LOGO の位置に会社名が入る（有りならロゴを手作業で配置）\n'
    '        { field: "会社名",     wholeLine: true, logo: true,\n'
    '          texts: ["LOGO", "Logo", "ROGO", "rogo", "L◉G◉"] },\n'
    '        // 文字のロゴ（英語面では英字の会社名があればそちらを使う）\n'
    '        { field: "会社名",     wholeLine: true, logo: true, altField: "会社名英字",\n'
    '          texts: ["artcode", "アートコード"] },\n'
    '        { field: "会社名",     wholeLine: true,\n'
    '          texts: ["株式会社●●商事", "株式会社海山商事", "○○商事○○○企画課"] },\n'
    '        // 「株式会社」と「○○商事」が別の行になっているデザイン\n'
    '        { field: "会社名_前",  wholeLine: true, usedAs: "会社名", texts: ["株式会社"] },\n'
    '        { field: "会社名_後",  wholeLine: true, usedAs: "会社名", texts: ["○○商事", "海山商事"] },\n'
    '        { field: "肩書",       texts: ["代表取締役"], spaced: true },\n'
    '        { field: "肩書",       wholeLine: true, spaced: true,\n'
    '          texts: ["店長", "オーナー", "ショップオーナー", "取締役社長", "代表", "営業事務", "営業課長", "課長",\n'
    '                  "保育士", "料理長", "料理研究家", "ライター", "シンガーソングライター", "スタイリスト",\n'
    '                  "インストラクター", "司書補", "カメラマン", "バイヤー", "先生", "ボランティア"] },\n'
    '        { field: "氏名英字",   texts: ["Ichiro Suzuki", "Taro Suzuki", "Hanako Suzuki", "Emi Nakamura"] },\n'
    '        { field: "肩書英字",   texts: ["President"], wholeLine: true },\n'
    '        { field: "住所1",\n'
    '          texts: ["○○○県○○市○○町00-00-0", "○○○県○○市○○町0-00-0", "○○○県○○○○市○○○町1-1-1",\n'
    '                  "○○○県○○○市○○○町1-2-3", "○○○県○○○市○○○町○○ー○ー○○", "○○県○○市○○町00-00-0",\n'
    '                  "○○○○○○○○○○町000-0000", "○○○県○○市○○町"] },\n'
    '        { field: "住所2",      texts: ["00-00-0○○○○000号", "○○○○○000号", "○○○000号"] },\n'
    '        { field: "メール",     texts: ["ooooo@oooo.com"] },\n'
    '        { field: "URL",        texts: ["http://www.0123456.jp/"] },\n'
    '        { field: "英字住所1",  texts: ["6-1-1-3 Hirasaku,Yokosuka city,"] },\n'
    '        { field: "英字住所2",  texts: ["Kanagawa 238-0032,Japan"] }\n'
    '    ];\n'
    '\n'
    '    // 会社名を「株式会社」と「残り」に分ける（「株式会社」の行が別になっているデザイン用）\n'
    '    var COMPANY_PREFIX = /^(株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|公益社団法人|公益財団法人|医療法人社団|医療法人|社会福祉法人|学校法人|特定非営利活動法人|NPO法人)[ \\t\\u3000]*/;\n'
    '\n'
    '    // -----------------------------------------------------------------\n'
    '    //  3. 「Tel :」「Fax :」などの見出しの後ろにある値を置き換える項目\n'
    '    // -----------------------------------------------------------------\n'
    '    var LABELS = [\n'
    '        { field: "TEL",    words: ["Tel", "TEL", "電話", "ＴＥＬ"] },\n'
    '        { field: "FAX",    words: ["Fax", "FAX", "ＦＡＸ"] },\n'
    '        { field: "携帯",   words: ["Mobile", "Mob", "Cell", "携帯"] },\n'
    '        { field: "メール", words: ["E-mail", "Email", "Mail"] },\n'
    '        { field: "URL",    words: ["URL", "Web", "HP"] }\n'
    '    ];\n'
    '\n'
    '    // 置き換え後に、この文字が残っていたら「置き換え漏れかも」と警告する\n'
    '    var LEFTOVER_PATTERNS = [/[○〇]/, /000-/, /ooooo@/, /0123456/];\n'
    '\n'
    '    var WS = "[ \\\\t\\\\u3000]";           // 空白（半角・全角・タブ）\n'
    '    var LINE_BREAK = /[\\r\\n\\u0003]/;   // Illustrator の改行（\\r）と強制改行（\\u0003）\n'
    '\n'
    '    // ===== 小さな道具 =====================================================\n'
    '\n'
    '    function trim(s) {\n'
    '        return String(s).replace(/^[ \\t\\u3000\\r\\n]+|[ \\t\\u3000\\r\\n]+$/g, "");\n'
    '    }\n'
    '\n'
    '    function escapeRegex(s) {\n'
    '        return s.replace(/[\\\\^$.*+?()[\\]{}|\\/-]/g, "\\\\$&");\n'
    '    }\n'
    '\n'
    '    // "Tel" → /T[ \\t\u3000]*e[ \\t\u3000]*l/ のように、文字の間の空白を許す正規表現の文字列\n'
    '    function looseSource(text) {\n'
    '        var out = [];\n'
    '        for (var i = 0; i < text.length; i++) {\n'
    '            var c = text.charAt(i);\n'
    '            if (/[ \\t\\u3000]/.test(c)) continue;\n'
    '            out.push(c === "○" || c === "〇" ? "[○〇]" : escapeRegex(c));\n'
    '        }\n'
    '        return out.join(WS + "*");\n'
    '    }\n'
    '\n'
    '    function inArray(arr, v) {\n'
    '        for (var i = 0; i < arr.length; i++) if (arr[i] === v) return true;\n'
    '        return false;\n'
    '    }\n'
    '\n'
    '    // ===== CSV ============================================================\n'
    '\n'
    '    // CSVの文字列 → 行の配列（各行は列の配列）。"..." で囲んだ値、値の中の改行・カンマにも対応。\n'
    '    function parseCSV(text) {\n'
    '        if (text.charCodeAt(0) === 0xFEFF) text = text.substring(1);\n'
    '        var rows = [], row = [], field = "", inQuotes = false;\n'
    '        for (var i = 0; i < text.length; i++) {\n'
    '            var c = text.charAt(i);\n'
    '            if (inQuotes) {\n'
    '                if (c === \'"\') {\n'
    '                    if (text.charAt(i + 1) === \'"\') { field += \'"\'; i++; }\n'
    '                    else inQuotes = false;\n'
    '                } else field += c;\n'
    '            } else if (c === \'"\') {\n'
    '                inQuotes = true;\n'
    '            } else if (c === ",") {\n'
    '                row.push(field); field = "";\n'
    '            } else if (c === "\\r" || c === "\\n") {\n'
    '                if (c === "\\r" && text.charAt(i + 1) === "\\n") i++;\n'
    '                row.push(field); field = "";\n'
    '                rows.push(row); row = [];\n'
    '            } else field += c;\n'
    '        }\n'
    '        if (field !== "" || row.length > 0) { row.push(field); rows.push(row); }\n'
    '        // 空行を捨てる\n'
    '        var out = [];\n'
    '        for (var r = 0; r < rows.length; r++) {\n'
    '            if (trim(rows[r].join("")) !== "") out.push(rows[r]);\n'
    '        }\n'
    '        return out;\n'
    '    }\n'
    '\n'
    '    // 1行目を見出しとして、各行を { 項目名: 値 } に変える\n'
    '    function rowsToRecords(rows) {\n'
    '        if (rows.length === 0) return { records: [], unknownHeaders: [] };\n'
    '        var header = rows[0], colField = [], unknown = [];\n'
    '        for (var c = 0; c < header.length; c++) {\n'
    '            var h = trim(header[c]), found = null;\n'
    '            for (var f in FIELD_ALIASES) {\n'
    '                if (FIELD_ALIASES.hasOwnProperty(f) && inArray(FIELD_ALIASES[f], h)) { found = f; break; }\n'
    '            }\n'
    '            colField.push(found);\n'
    '            if (!found && h !== "") unknown.push(h);\n'
    '        }\n'
    '        var records = [];\n'
    '        for (var r = 1; r < rows.length; r++) {\n'
    '            var rec = {};\n'
    '            for (var k = 0; k < colField.length; k++) {\n'
    '                if (colField[k] && rows[r][k] !== undefined) rec[colField[k]] = trim(rows[r][k]);\n'
    '            }\n'
    '            records.push(rec);\n'
    '        }\n'
    '        return { records: records, unknownHeaders: unknown };\n'
    '    }\n'
    '\n'
    '    // 部署は肩書の前に付ける（例: 営業部\u3000部長）\n'
    '    function prepareValues(rec) {\n'
    '        var v = {};\n'
    '        for (var k in rec) if (rec.hasOwnProperty(k)) v[k] = rec[k];\n'
    '        if (v["部署"]) v["肩書"] = v["肩書"] ? v["部署"] + "\\u3000" + v["肩書"] : v["部署"];\n'
    '        var company = v["会社名"] || "";\n'
    '        var m = company.match(COMPANY_PREFIX);\n'
    '        v["会社名_前"] = m ? m[1] : "";\n'
    '        v["会社名_後"] = m ? company.substring(m[0].length) : company;\n'
    '        return v;\n'
    '    }\n'
    '\n'
    '    // その文字が「LOGO」などロゴの仮の文字か（LOGO 横のマークを探すときに使う）\n'
    '    function isLogoText(text) {\n'
    '        var t = String(text).replace(/[ \\t\\u3000\\r\\n]/g, "");\n'
    '        for (var k = 0; k < PLACEHOLDERS.length; k++) {\n'
    '            if (!PLACEHOLDERS[k].logo) continue;\n'
    '            for (var i = 0; i < PLACEHOLDERS[k].texts.length; i++) {\n'
    '                if (PLACEHOLDERS[k].texts[i] === t) return true;\n'
    '            }\n'
    '        }\n'
    '        return false;\n'
    '    }\n'
    '\n'
    '    // ロゴデータが「有り」の注文か\n'
    '    function hasLogoData(rec) {\n'
    '        return /^[ \\t\\u3000]*有/.test(rec["ロゴデータ"] || "");\n'
    '    }\n'
    '\n'
    '    // ===== 差し込み位置を探す =============================================\n'
    '\n'
    '    // 文字列 contents（1つのテキストの中身）について、どこを何に置き換えるかを返す。\n'
    '    //   edits:  [{ start, end, text, field }]   （start〜end を text に置き換える）\n'
    '    //   used:   この中で見つかった項目名の一覧\n'
    '    function planEdits(contents, rec) {\n'
    '        var values = prepareValues(rec);\n'
    '        values.__logo = hasLogoData(rec);\n'
    '        var edits = [], used = [];\n'
    '\n'
    '        // 行ごとに処理する\n'
    '        var lineStart = 0;\n'
    '        while (lineStart <= contents.length) {\n'
    '            var lineEnd = lineStart;\n'
    '            while (lineEnd < contents.length && !LINE_BREAK.test(contents.charAt(lineEnd))) lineEnd++;\n'
    '            var line = contents.substring(lineStart, lineEnd);\n'
    '            var lineEdits = planLine(line, values, used);\n'
    '\n'
    '            // その行で消すものばかりで、何も残らない → 行ごと消す（改行も一緒に）\n'
    '            if (lineEdits.length > 0 && trim(applyEditsToString(line, lineEdits)) === "") {\n'
    '                var delStart = lineStart, delEnd = lineEnd;\n'
    '                if (lineEnd < contents.length) delEnd = lineEnd + 1;          // 後ろの改行\n'
    '                else if (lineStart > 0) delStart = lineStart - 1;            // 最後の行なら前の改行\n'
    '                edits.push({ start: delStart, end: delEnd, text: "", field: "(行削除)" });\n'
    '            } else {\n'
    '                for (var i = 0; i < lineEdits.length; i++) {\n'
    '                    edits.push({\n'
    '                        start: lineEdits[i].start + lineStart,\n'
    '                        end: lineEdits[i].end + lineStart,\n'
    '                        text: lineEdits[i].text,\n'
    '                        field: lineEdits[i].field\n'
    '                    });\n'
    '                }\n'
    '            }\n'
    '            if (lineEnd >= contents.length) break;\n'
    '            lineStart = lineEnd + 1;\n'
    '        }\n'
    '        edits.sort(function (a, b) { return a.start - b.start; });\n'
    '        return { edits: edits, used: used };\n'
    '    }\n'
    '\n'
    '    // コロンのない見出しのときは、後ろが本当に電話番号などかを確かめる（「Web デザイン」などを避ける）\n'
    '    function looksLikeValue(field, rest) {\n'
    '        if (field === "メール") return /@/.test(rest);\n'
    '        if (field === "URL") return /^(https?|www)/i.test(rest);\n'
    '        return /^[0-9０-９○〇+(（]/.test(rest);\n'
    '    }\n'
    '\n'
    '    function planLine(line, values, used) {\n'
    '        var edits = [];\n'
    '        var taken = [];  // すでに置き換え対象になった範囲（二重に置き換えないため）\n'
    '\n'
    '        function isFree(s, e) {\n'
    '            for (var i = 0; i < taken.length; i++) {\n'
    '                if (s < taken[i][1] && e > taken[i][0]) return false;\n'
    '            }\n'
    '            return true;\n'
    '        }\n'
    '        function add(s, e, text, field, usedAs) {\n'
    '            edits.push({ start: s, end: e, text: text, field: field });\n'
    '            taken.push([s, e]);\n'
    '            if (!inArray(used, usedAs || field)) used.push(usedAs || field);\n'
    '        }\n'
    '        function val(field) { return values[field] ? values[field] : ""; }\n'
    '\n'
    '        // --- (a) 「Tel : 000-...」のような見出し付きの値 ---\n'
    '        var found = [];\n'
    '        for (var L = 0; L < LABELS.length; L++) {\n'
    '            for (var w = 0; w < LABELS[L].words.length; w++) {\n'
    '                // 「Tel :」のようにコロンがあるか、「電話 〇〇〇」のように空白のあとに値が続く\n'
    '                var re = new RegExp("(^|" + WS + ")(" + looseSource(LABELS[L].words[w]) + ")(" + WS + "*[:：]" + WS + "*|" + WS + "+)", "g");\n'
    '                var m;\n'
    '                while ((m = re.exec(line)) !== null) {\n'
    '                    if (!/[:：]/.test(m[3]) && !looksLikeValue(LABELS[L].field, line.substring(m.index + m[0].length))) continue;\n'
    '                    var labelStart = m.index + m[1].length;\n'
    '                    var dup = false;\n'
    '                    for (var d = 0; d < found.length; d++) if (found[d].labelStart === labelStart) dup = true;\n'
    '                    if (!dup) found.push({ field: LABELS[L].field, labelStart: labelStart, valueStart: m.index + m[0].length });\n'
    '                }\n'
    '            }\n'
    '        }\n'
    '        found.sort(function (a, b) { return a.labelStart - b.labelStart; });\n'
    '        for (var i = 0; i < found.length; i++) {\n'
    '            var vEnd = (i + 1 < found.length) ? found[i + 1].labelStart : line.length;\n'
    '            while (vEnd > found[i].valueStart && /[ \\t\\u3000]/.test(line.charAt(vEnd - 1))) vEnd--;\n'
    '            if (vEnd <= found[i].valueStart) continue;  // 値がない見出しは触らない\n'
    '            var v = val(found[i].field);\n'
    '            if (v !== "") {\n'
    '                add(found[i].valueStart, vEnd, v, found[i].field);\n'
    '            } else {\n'
    '                // 値が空 → 見出しごと消す（前の空白も消す）\n'
    '                var s = found[i].labelStart;\n'
    '                while (s > 0 && /[ \\t\\u3000]/.test(line.charAt(s - 1))) s--;\n'
    '                add(s, vEnd, "", found[i].field);\n'
    '            }\n'
    '        }\n'
    '\n'
    '        // --- (a2) 見出しだけの行（「E-mail」の値が別のテキストになっているデザイン）---\n'
    '        //     値が空なら見出しも消す。値があれば見出しはそのまま\n'
    '        if (found.length === 0) {\n'
    '            for (var L2 = 0; L2 < LABELS.length; L2++) {\n'
    '                for (var w2 = 0; w2 < LABELS[L2].words.length; w2++) {\n'
    '                    var only = new RegExp("^" + WS + "*" + looseSource(LABELS[L2].words[w2]) + WS + "*[:：]?" + WS + "*$");\n'
    '                    if (only.test(line) && val(LABELS[L2].field) === "" && isFree(0, line.length)) {\n'
    '                        add(0, line.length, "", LABELS[L2].field);\n'
    '                    }\n'
    '                }\n'
    '            }\n'
    '            if (/^[ \\t\\u3000]*〒[ \\t\\u3000]*$/.test(line) && val("郵便番号") === "" && isFree(0, line.length)) {\n'
    '                add(0, line.length, "", "郵便番号");\n'
    '            }\n'
    '        }\n'
    '\n'
    '        // --- (b) 見出しのない URL・メール・郵便番号 ---\n'
    '        var patterns = [\n'
    '            { field: "URL", re: /https?:\\/\\/[^ \\t\\u3000]+/g },\n'
    '            { field: "メール", re: /[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/g }\n'
    '        ];\n'
    '        for (var p = 0; p < patterns.length; p++) {\n'
    '            var pm;\n'
    '            patterns[p].re.lastIndex = 0;\n'
    '            while ((pm = patterns[p].re.exec(line)) !== null) {\n'
    '                var ps = pm.index, pe = pm.index + pm[0].length;\n'
    '                if (!isFree(ps, pe)) continue;\n'
    '                var pv = val(patterns[p].field);\n'
    '                if (pv === "") {\n'
    '                    // 「  : ooooo@...」のように前に「:」だけ残る場合も一緒に消す\n'
    '                    while (ps > 0 && /[ \\t\\u3000:：]/.test(line.charAt(ps - 1))) ps--;\n'
    '                }\n'
    '                add(ps, pe, pv, patterns[p].field);\n'
    '            }\n'
    '        }\n'
    '        var zipRe = new RegExp("〒" + WS + "*([0-9０-９○〇]" + WS + "*){3}[-‐－ー]" + WS + "*([0-9０-９○〇]" + WS + "*){3}[0-9０-９○〇]", "g");\n'
    '        var zm;\n'
    '        while ((zm = zipRe.exec(line)) !== null) {\n'
    '            var zs = zm.index, ze = zm.index + zm[0].length;\n'
    '            if (!isFree(zs, ze)) continue;\n'
    '            var zv = val("郵便番号");\n'
    '            if (zv === "") add(zs, ze, "", "郵便番号");\n'
    '            else add(zs + 1, ze, zv.replace(/^〒/, ""), "郵便番号");   // 〒 は残す\n'
    '        }\n'
    '\n'
    '        // --- (c) テンプレートの仮の文字 ---\n'
    '        for (var k = 0; k < PLACEHOLDERS.length; k++) {\n'
    '            var ph = PLACEHOLDERS[k];\n'
    '            if (ph.logo && values.__logo) continue;   // ロゴ有り → LOGO はそのまま\n'
    '            var texts = ph.texts.slice(0).sort(function (a, b) { return b.length - a.length; });\n'
    '            for (var t = 0; t < texts.length; t++) {\n'
    '                var src = looseSource(texts[t]);\n'
    '                if (ph.wholeLine) src = "^" + WS + "*" + src + WS + "*$";\n'
    '                var pre = new RegExp(src, "g");\n'
    '                var mm;\n'
    '                while ((mm = pre.exec(line)) !== null) {\n'
    '                    if (mm[0].length === 0) { pre.lastIndex++; continue; }\n'
    '                    var ms = mm.index, me = mm.index + mm[0].length;\n'
    '                    if (ph.wholeLine) {   // 前後の空白は残す\n'
    '                        while (ms < me && /[ \\t\\u3000]/.test(line.charAt(ms))) ms++;\n'
    '                        while (me > ms && /[ \\t\\u3000]/.test(line.charAt(me - 1))) me--;\n'
    '                    }\n'
    '                    if (!isFree(ms, me)) continue;\n'
    '                    var field = (ph.altField && val(ph.altField) !== "") ? ph.altField : ph.field;\n'
    '                    var nv = val(field);\n'
    '                    if (nv !== "" && ph.spaced) nv = matchSpacing(line.substring(ms, me), nv);\n'
    '                    // 値が空のときは「  : ooooo@...」の「:」も一緒に消す\n'
    '                    if (nv === "") while (ms > 0 && /[ \\t\\u3000:：]/.test(line.charAt(ms - 1))) ms--;\n'
    '                    add(ms, me, nv, field, ph.usedAs);\n'
    '                }\n'
    '            }\n'
    '        }\n'
    '        return edits;\n'
    '    }\n'
    '\n'
    '    // 仮の文字が「鈴\u3000木\u3000太\u3000郎」のように1文字ずつ空いていたら、\n'
    '    // お客さんの名前「山田 花子」も「山\u3000田\u3000花\u3000子」にそろえる\n'
    '    function matchSpacing(placeholderText, value) {\n'
    '        var m = placeholderText.match(/^[^ \\t\\u3000]([ \\t\\u3000]+)[^ \\t\\u3000]/);\n'
    '        if (!m) return value;\n'
    '        var chars = value.replace(/[ \\t\\u3000]+/g, "");\n'
    '        var out = [];\n'
    '        for (var i = 0; i < chars.length; i++) out.push(chars.charAt(i));\n'
    '        return out.join(m[1]);\n'
    '    }\n'
    '\n'
    '    // edits を文字列に当てはめた結果を返す（後ろから置き換える）\n'
    '    function applyEditsToString(s, edits) {\n'
    '        var sorted = edits.slice(0).sort(function (a, b) { return b.start - a.start; });\n'
    '        for (var i = 0; i < sorted.length; i++) {\n'
    '            s = s.substring(0, sorted[i].start) + sorted[i].text + s.substring(sorted[i].end);\n'
    '        }\n'
    '        return s;\n'
    '    }\n'
    '\n'
    '    // ===== チェック =======================================================\n'
    '\n'
    '    // 値が入っているのに、テンプレートに差し込み先がなかった項目\n'
    '    function unusedFields(rec, used) {\n'
    '        var out = [];\n'
    '        for (var k in rec) {\n'
    '            if (!rec.hasOwnProperty(k) || inArray(INFO_FIELDS, k)) continue;\n'
    '            if (k === "会社名" && hasLogoData(rec)) continue;\n'
    '            if (rec[k] !== "" && !inArray(used, k)) out.push(k);\n'
    '        }\n'
    '        return out;\n'
    '    }\n'
    '\n'
    '    function hasLeftover(text) {\n'
    '        for (var i = 0; i < LEFTOVER_PATTERNS.length; i++) if (LEFTOVER_PATTERNS[i].test(text)) return true;\n'
    '        return false;\n'
    '    }\n'
    '\n'
    '    // ===== 文字コード・デザイン番号 ========================================\n'
    '\n'
    '    // バイト列（1文字=1バイトの文字列）が UTF-8 か Shift_JIS かを判定する。\n'
    '    // Excel で保存した日本語CSVは Shift_JIS、「CSV UTF-8」で保存すると UTF-8 になります。\n'
    '    function detectEncoding(bytes) {\n'
    '        if (bytes.charCodeAt(0) === 0xEF && bytes.charCodeAt(1) === 0xBB && bytes.charCodeAt(2) === 0xBF) return "UTF-8";\n'
    '        var i = 0, n = bytes.length, sawMultiByte = false;\n'
    '        while (i < n) {\n'
    '            var b = bytes.charCodeAt(i);\n'
    '            var extra = b < 0x80 ? 0 : (b >= 0xC2 && b <= 0xDF) ? 1 : (b >= 0xE0 && b <= 0xEF) ? 2 : (b >= 0xF0 && b <= 0xF4) ? 3 : -1;\n'
    '            if (extra < 0) return "Shift_JIS";\n'
    '            for (var k = 1; k <= extra; k++) {\n'
    '                var c = bytes.charCodeAt(i + k);\n'
    '                if (i + k >= n || c < 0x80 || c > 0xBF) return "Shift_JIS";\n'
    '            }\n'
    '            if (extra > 0) sawMultiByte = true;\n'
    '            i += extra + 1;\n'
    '        }\n'
    '        return sawMultiByte ? "UTF-8" : "Shift_JIS";\n'
    '    }\n'
    '\n'
    '    // デザイン番号やファイル名を比べやすい形にする（全角英数→半角、小文字、空白なし、.ai なし）\n'
    '    function normalizeKey(s) {\n'
    '        s = String(s || "").replace(/[！-～]/g, function (c) {\n'
    '            return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);\n'
    '        });\n'
    '        return s.replace(/[ \\t\\u3000]+/g, "").replace(/\\.ai$/i, "").toLowerCase();\n'
    '    }\n'
    '\n'
    '    // ===== ファイル名 =====================================================\n'
    '\n'
    '    // 「注文番号_名前.ai」 ファイル名に使えない文字や空白は取り除く\n'
    '    function makeFileName(rec) {\n'
    '        function clean(s) {\n'
    '            return String(s || "").replace(/[\\\\\\/:*?"<>|\\r\\n\\t]/g, "").replace(/[ \\u3000]+/g, "");\n'
    '        }\n'
    '        var order = clean(rec["注文番号"]) || "注文番号なし";\n'
    '        var name = clean(rec["氏名"]) || clean(rec["氏名英字"]) || "名前なし";\n'
    '        return order + "_" + name + ".ai";\n'
    '    }\n'
    '\n'
    '    return {\n'
    '        FIELD_ALIASES: FIELD_ALIASES,\n'
    '        PLACEHOLDERS: PLACEHOLDERS,\n'
    '        LABELS: LABELS,\n'
    '        trim: trim,\n'
    '        parseCSV: parseCSV,\n'
    '        rowsToRecords: rowsToRecords,\n'
    '        INFO_FIELDS: INFO_FIELDS,\n'
    '        prepareValues: prepareValues,\n'
    '        hasLogoData: hasLogoData,\n'
    '        isLogoText: isLogoText,\n'
    '        planEdits: planEdits,\n'
    '        applyEditsToString: applyEditsToString,\n'
    '        matchSpacing: matchSpacing,\n'
    '        unusedFields: unusedFields,\n'
    '        hasLeftover: hasLeftover,\n'
    '        detectEncoding: detectEncoding,\n'
    '        normalizeKey: normalizeKey,\n'
    '        makeFileName: makeFileName\n'
    '    };\n'
    '})();\n'
    '\n'
    '// Node.js のテストから読み込むとき用\n'
    'if (typeof module !== "undefined" && module.exports) module.exports = MeishiCore;\n'
    '\n'
    '// =====================================================================\n'
    '//  名刺自動作成 — Illustrator の書類を書き換える部分\n'
    '//  （meishi_job.jsx と meishi_auto.jsx から #include して使います）\n'
    '//  先に meishi_core.jsx を #include しておく必要があります。\n'
    '// =====================================================================\n'
    '\n'
    'var MeishiAI = (function () {\n'
    '    var C = MeishiCore;\n'
    '\n'
    '    // 文字コードを判定してテキストファイルを読む（UTF-8 / Shift_JIS）\n'
    '    function readTextFile(file) {\n'
    '        file.encoding = "BINARY";\n'
    '        file.open("r");\n'
    '        var bytes = file.read();\n'
    '        file.close();\n'
    '        file.encoding = C.detectEncoding(bytes);\n'
    '        file.open("r");\n'
    '        var text = file.read();\n'
    '        file.close();\n'
    '        return text;\n'
    '    }\n'
    '\n'
    '    function oneLine(s, max) {\n'
    '        max = max || 40;\n'
    '        s = String(s).replace(/[\\r\\n\\u0003]+/g, " / ");\n'
    '        return s.length > max ? s.substring(0, max) + "…" : s;\n'
    '    }\n'
    '\n'
    '    // テキストフレームの start〜end 文字目を text に置き換える（最初の文字の書式を引き継ぐ）\n'
    '    function replaceRange(tf, start, end, text) {\n'
    '        var len = end - start;\n'
    '        if (len <= 0) return;\n'
    '        var r = tf.characters[start];\n'
    '        try {\n'
    '            if (len > 1) r.length = len;\n'
    '        } catch (e) {\n'
    '            // length が変えられない場合は1文字ずつ消す\n'
    '            for (var i = end - 1; i > start; i--) tf.characters[i].remove();\n'
    '            r = tf.characters[start];\n'
    '        }\n'
    '        if (text === "") r.remove();\n'
    '        else r.contents = text;\n'
    '    }\n'
    '\n'
    '    // 書き換えのじゃまになるロックを一時的に外す\n'
    '    function unlockFor(item) {\n'
    '        var restore = [];\n'
    '        while (item && item.typename !== "Document") {\n'
    '            if (item.locked) { item.locked = false; restore.push(item); }\n'
    '            item = item.parent;\n'
    '        }\n'
    '        return function () {\n'
    '            for (var i = 0; i < restore.length; i++) restore[i].locked = true;\n'
    '        };\n'
    '    }\n'
    '\n'
    '    // ----- LOGO 横のマーク -----\n'
    '\n'
    '    // geometricBounds は [左, 上, 右, 下]（上の方が数字が大きい）\n'
    '    // 「LOGO の左右すぐ横にあり、LOGO と同じくらいの大きさで、LOGO に重なっていない」ものをマークとみなす\n'
    '    // （463 個のテンプレートで確認。背景の絵や大きな飾りは対象外になる）\n'
    '    function isNextToLogo(b, logo) {\n'
    '        var h = logo[1] - logo[3];\n'
    '        var ih = b[1] - b[3], iw = b[2] - b[0];\n'
    '        if (ih <= 0 || iw <= 0 || ih > h * 3 || iw > h * 3) return false;  // LOGO の3倍より大きいものは背景\n'
    '        var vOverlap = Math.min(logo[1], b[1]) - Math.max(logo[3], b[3]);\n'
    '        if (vOverlap < ih * 0.5) return false;                             // 半分以上が LOGO と同じ高さにある\n'
    '        var gap;\n'
    '        if (b[2] <= logo[0] + 1) gap = logo[0] - b[2];                     // 左側\n'
    '        else if (b[0] >= logo[2] - 1) gap = b[0] - logo[2];                // 右側\n'
    '        else return false;                                                  // LOGO に重なっている（背景）\n'
    '        return gap <= h;\n'
    '    }\n'
    '\n'
    '    function overlaps(a, b) {\n'
    '        return Math.min(a[2], b[2]) > Math.max(a[0], b[0]) && Math.min(a[1], b[1]) > Math.max(a[3], b[3]);\n'
    '    }\n'
    '\n'
    '    // 画像の範囲の一覧から、LOGO 横のマークだけを選ぶ（番号の一覧を返す）\n'
    '    // ・他の画像に重なっているもの（背景の絵の一部）は選ばない\n'
    '    // ・候補が2つ以上あるときは、どれがマークか分からないので何も選ばない（ambiguous に印を付ける）\n'
    '    function pickMarks(boundsList, logo, info) {\n'
    '        var out = [];\n'
    '        for (var i = 0; i < boundsList.length; i++) {\n'
    '            if (!isNextToLogo(boundsList[i], logo)) continue;\n'
    '            var alone = true;\n'
    '            for (var j = 0; j < boundsList.length; j++) {\n'
    '                if (j !== i && overlaps(boundsList[i], boundsList[j])) { alone = false; break; }\n'
    '            }\n'
    '            if (alone) out.push(i);\n'
    '        }\n'
    '        if (out.length > 1) {\n'
    '            if (info) info.ambiguous = true;\n'
    '            return [];\n'
    '        }\n'
    '        return out;\n'
    '    }\n'
    '\n'
    '    function contains(group, item) {\n'
    '        for (var p = item.parent; p && p.typename !== "Document"; p = p.parent) if (p === group) return true;\n'
    '        return false;\n'
    '    }\n'
    '\n'
    '    // LOGO の文字の横にあるロゴマークを探す\n'
    '    //  ① LOGO の文字とグループになっている図形・画像（LOGO のすぐ横にあるもの）\n'
    '    //  ② LOGO のすぐ横（上下）にある画像\n'
    '    function findLogoMarks(doc, logoFrame) {\n'
    '        var marks = [];\n'
    '        var parent = logoFrame.parent;\n'
    '        if (parent.typename === "GroupItem") {\n'
    '            for (var i = 0; i < parent.pageItems.length; i++) {\n'
    '                var it = parent.pageItems[i];\n'
    '                if (it !== logoFrame && it.typename !== "TextFrame" &&\n'
    '                    isNextToLogo(it.geometricBounds, logoFrame.geometricBounds)) marks.push(it);\n'
    '            }\n'
    '            if (marks.length > 0) return marks;\n'
    '        }\n'
    '        var logo = logoFrame.geometricBounds;\n'
    '        var lists = [doc.rasterItems, doc.placedItems], items = [], bounds = [];\n'
    '        for (var l = 0; l < lists.length; l++) {\n'
    '            for (var k = 0; k < lists[l].length; k++) {\n'
    '                var item = lists[l][k];\n'
    '                // マスクで切り抜かれている画像はマスクのグループごと消す\n'
    '                while (item.parent.typename === "GroupItem" && item.parent.clipped &&\n'
    '                       !contains(item.parent, logoFrame)) item = item.parent;\n'
    '                items.push(item);\n'
    '                bounds.push(item.geometricBounds);\n'
    '            }\n'
    '        }\n'
    '        var info = {};\n'
    '        var picked = pickMarks(bounds, logo, info);\n'
    '        if (info.ambiguous) marks.ambiguous = true;\n'
    '        for (var p = 0; p < picked.length; p++) marks.push(items[picked[p]]);\n'
    '        return marks;\n'
    '    }\n'
    '\n'
    '    function removeLogoMarks(doc, rec, warnings) {\n'
    '        if (C.hasLogoData(rec)) return;    // ロゴ有り → マークはそのまま（あとで差し替え）\n'
    '        var count = 0;\n'
    '        for (var i = 0; i < doc.textFrames.length; i++) {\n'
    '            var tf = doc.textFrames[i];\n'
    '            if (!C.isLogoText(tf.contents)) continue;\n'
    '            var marks = findLogoMarks(doc, tf);\n'
    '            if (marks.ambiguous) warnings.push("LOGO 横に画像が複数あり、マークか分からないため消していません");\n'
    '            for (var m = 0; m < marks.length; m++) {\n'
    '                try {\n'
    '                    var relock = unlockFor(marks[m]);\n'
    '                    marks[m].remove();\n'
    '                    count++;\n'
    '                    relock();\n'
    '                } catch (e) {\n'
    '                    warnings.push("LOGO 横のマークを消せませんでした（" + e.message + "）");\n'
    '                }\n'
    '            }\n'
    '        }\n'
    '        if (count > 0) warnings.push("LOGO 横のマークを " + count + " 個消しました（位置を確認してください）");\n'
    '    }\n'
    '\n'
    '    // ----- 書類全体の書き換え -----\n'
    '\n'
    '    // 書類の文字を注文内容に書き換える。確認してほしいことを warnings に足す。\n'
    '    function editDocument(doc, rec, warnings) {\n'
    '        removeLogoMarks(doc, rec, warnings);   // LOGO の文字が会社名に変わる前に探す\n'
    '\n'
    '        var used = [];\n'
    '        var frames = [];\n'
    '        for (var i = 0; i < doc.textFrames.length; i++) frames.push(doc.textFrames[i]);\n'
    '\n'
    '        var values = C.prepareValues(rec);\n'
    '        for (var f = 0; f < frames.length; f++) {\n'
    '            var tf = frames[f];\n'
    '            var relock = unlockFor(tf);\n'
    '            try {\n'
    '                // テキストに項目名の名前（例:「氏名」）が付いていれば、中身を丸ごと置き換える\n'
    '                if (tf.name && C.FIELD_ALIASES.hasOwnProperty(tf.name)) {\n'
    '                    if (tf.contents !== "") replaceRange(tf, 0, tf.contents.length, values[tf.name] || "");\n'
    '                    used.push(tf.name);\n'
    '                } else {\n'
    '                    var before = tf.contents;\n'
    '                    var plan = C.planEdits(before, rec);\n'
    '                    for (var u = 0; u < plan.used.length; u++) used.push(plan.used[u]);\n'
    '                    if (plan.edits.length > 0) {\n'
    '                        var expected = C.applyEditsToString(before, plan.edits);\n'
    '                        for (var e = plan.edits.length - 1; e >= 0; e--) {\n'
    '                            replaceRange(tf, plan.edits[e].start, plan.edits[e].end, plan.edits[e].text);\n'
    '                        }\n'
    '                        if (tf.contents !== expected) {\n'
    '                            // 念のための安全策：うまく置き換わらなかったら中身ごと入れ直す\n'
    '                            tf.contents = expected;\n'
    '                            warnings.push("文字の書式が一部くずれたかもしれません: 「" + oneLine(expected) + "」");\n'
    '                        }\n'
    '                    }\n'
    '                }\n'
    '                if (C.hasLeftover(tf.contents)) {\n'
    '                    warnings.push("仮の文字が残っています: 「" + oneLine(tf.contents) + "」");\n'
    '                }\n'
    '            } catch (err) {\n'
    '                warnings.push("テキストを書き換えられませんでした（" + err.message + "）: 「" + oneLine(tf.contents) + "」");\n'
    '            }\n'
    '            relock();\n'
    '        }\n'
    '        var unused = C.unusedFields(rec, used);\n'
    '        if (unused.length > 0) {\n'
    '            warnings.push("テンプレートに差し込み先がない項目: " + unused.join("、"));\n'
    '        }\n'
    '        // 名刺には入れていないが、目で確認してほしい情報\n'
    '        if (C.hasLogoData(rec)) warnings.push("ロゴデータ有り: LOGO の位置にロゴを配置してください");\n'
    '        if (rec["自由行"]) warnings.push("自由記入（行目）: " + oneLine(rec["自由行"], 80));\n'
    '        if (rec["備考"]) warnings.push("備考: " + oneLine(rec["備考"], 80));\n'
    '        if (rec["確認事項"]) warnings.push(rec["確認事項"]);\n'
    '    }\n'
    '\n'
    '    return {\n'
    '        readTextFile: readTextFile,\n'
    '        oneLine: oneLine,\n'
    '        isNextToLogo: isNextToLogo,\n'
    '        pickMarks: pickMarks,\n'
    '        editDocument: editDocument\n'
    '    };\n'
    '})();\n'
    '\n'
    '\n'
    '(function () {\n'
    '    var C = MeishiCore;\n'
    '    var JOB_FILE = new File(Folder.userData + "/meishi_job.csv");\n'
    '\n'
    '    if (!JOB_FILE.exists) {\n'
    '        alert("名刺作成の指示ファイルが見つかりません。\\n注文通知アプリの［名刺を作成］ボタンから実行してください。");\n'
    '        return;\n'
    '    }\n'
    '    var records = C.rowsToRecords(C.parseCSV(MeishiAI.readTextFile(JOB_FILE))).records;\n'
    '    JOB_FILE.remove();   // 同じ指示で二度作らないように消す\n'
    '\n'
    '    var report = [];\n'
    '    var oldLevel = app.userInteractionLevel;\n'
    '    app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;   // フォント不足などの確認を出さない\n'
    '    try {\n'
    '        for (var i = 0; i < records.length; i++) {\n'
    '            var rec = records[i];\n'
    '            var warnings = [];\n'
    '            var tpl = new File(rec["テンプレート"] || "");\n'
    '            var out = new File(rec["保存先"] || "");\n'
    '            var title = (rec["注文番号"] || "") + "  " + decodeURI(out.name);\n'
    '            if (!tpl.exists) {\n'
    '                report.push("✕ " + (rec["注文番号"] || "") + "\\n   テンプレートが見つかりません: " + tpl.fsName);\n'
    '                continue;\n'
    '            }\n'
    '            try {\n'
    '                var doc = app.open(tpl);\n'
    '                MeishiAI.editDocument(doc, rec, warnings);\n'
    '                if (!out.parent.exists) out.parent.create();\n'
    '                var opts = new IllustratorSaveOptions();\n'
    '                opts.pdfCompatible = true;\n'
    '                doc.saveAs(out, opts);       // 別名保存。書類は開いたままにする\n'
    '            } catch (err) {\n'
    '                report.push("✕ " + title + "\\n   エラー: " + err.message);\n'
    '                continue;\n'
    '            }\n'
    '            if (warnings.length > 0) {\n'
    '                report.push("△ " + title + "\\n   - " + warnings.join("\\n   - "));\n'
    '            }\n'
    '        }\n'
    '    } finally {\n'
    '        app.userInteractionLevel = oldLevel;\n'
    '    }\n'
    '\n'
    '    if (report.length > 0) {\n'
    '        alert("名刺を作成しました。次の点を確認してください。\\n\\n" + report.join("\\n\\n"));\n'
    '    }\n'
    '})();\n'
)
# ---- ここまで自動生成 ----
