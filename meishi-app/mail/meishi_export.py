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
import urllib.parse

# 作った名刺の保存先
OUTPUT_DIR = os.path.expanduser("~/Library/CloudStorage/Dropbox/1名刺表札作業用/1_新規ai")

# meishi_job.jsx が読む指示ファイル（Illustrator の Folder.userData の中）
JOB_FILE = os.path.expanduser("~/Library/Application Support/meishi_job.txt")

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


def remark_has_content(text):
    """備考にお客さんが何か書いていれば True（お店の案内文・区切り線・空白だけなら False）。

    meishi_core.jsx の remarkHasContent と同じ判定。
    """
    t = re.sub(r"[\s\u3000\u00a0\u200b-\u200d\ufeff]", "", text or "")
    t = re.sub(r"[【\[［(（]?不明点など確認時のご連絡先[^】\]］)）]*[】\]］)）]?", "", t)
    t = re.sub(r"[★☆*＊]?商品ページで入力できなかった項目やご要望等ございましたら[、,，]?こちらにご入力(下|くだ)さい[。.．]?", "", t)
    t = re.sub(r"[-‐‑‒–—―−－ー─━ｰ_＿~〜～=＝・･.。]", "", t)
    return t != ""


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


# 「01 sample」「02 gmail.com」のように、E-mail01（@の前）／E-mail02（@の後ろ）の番号が残っている値
_MAIL_PART = re.compile(r"^0?([12])(?:[\s\u3000:：]+(.*))?$")


def _set_mail(card, parts, value):
    """メールの値を入れる。E-mail01/02 の番号が残っていたら取り除き、あとで「@」でつなぐ。"""
    m = _MAIL_PART.match(value)
    if m and "@" not in value[:3]:
        parts[m.group(1)] = (m.group(2) or "").strip()
    else:
        card["メール"] = value


def _join_mail(card, parts):
    """E-mail01 と E-mail02 をつなぐ。E-mail02 がなければ E-mail01 をそのまま使う。"""
    local = parts.get("1", "").replace("＠", "@")
    domain = parts.get("2", "").replace("＠", "@")
    if local and domain:
        card["メール"] = local.rstrip("@") + "@" + domain.lstrip("@") if "@" not in local.rstrip("@") else local + domain
    elif local or domain:
        card["メール"] = local or domain


def _read_address_block(card, block):
    addr = []
    mail_parts = {}
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
                if field == "メール":
                    _set_mail(card, mail_parts, m.group(1).strip())
                    break
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
    _join_mail(card, mail_parts)
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
    if not remark_has_content(card["備考"]):
        card["備考"] = ""   # お店の案内文だけなら流し込まない
    if not card["氏名"]:
        _add_note(card, "氏名が見つかりません")
    return card


# 名刺1枚ごとに1回ずつ出てくる項目（2回目が出てきたら次の名刺とみなす）
_CARD_LABELS = {"会社名", "部署名", "肩書き", "肩書き(英語)", "氏名", "ふりがな"}


def _card_key(it):
    """名刺ごとの項目なら、その種類を返す（注文全体の項目なら None）。"""
    label, value, group = it.get("label", ""), it.get("value", ""), it.get("group")
    if group in ("address", "lines"):
        return group
    if label in _CARD_LABELS:
        return label
    if "ロゴデータ" in value:
        return "ロゴデータ"
    return None


def cards_from_order(order, items):
    """1つの注文に名刺が2枚以上（商品が2つ以上）あるとき、名刺ごとに分ける。

    メールでは商品ごとに「会社名・氏名・住所…」が続けて書かれているので、
    同じ項目が2回目に出てきたところで次の名刺に切り替える。
    備考など注文全体の項目は、すべての名刺に付ける。
    """
    common, groups, seen = [], [], set()
    for it in items:
        key = _card_key(it)
        is_note = it.get("label") == "当店への備考" or it.get("value", "").startswith("[備考]")
        if is_note:
            common.append(it)
        elif key is None:
            (groups[-1] if groups else common).append(it)
        else:
            if not groups or key in seen:
                groups.append([])
                seen = set()
            seen.add(key)
            groups[-1].append(it)
    if not groups:
        return [card_from_order(order, items)]
    head = [it for it in common if not (it.get("label") == "当店への備考" or it.get("value", "").startswith("[備考]"))]
    notes = [it for it in common if it not in head]
    return [card_from_order(order, head + g + notes) for g in groups]


def card_title(card, number):
    """「注文1：山田 太郎（株式会社サンプル）」のような、選ぶときの表示。"""
    who = card.get("氏名") or card.get("会社名") or "名前なし"
    extra = card.get("会社名") if card.get("氏名") and card.get("会社名") else ""
    return f"注文{number}：{who}" + (f"（{extra}）" if extra else "")


def _clean_name(s):
    """ファイル名に使えない文字と空白を取り除く。"""
    return re.sub(r"[\\/:*?\"<>|\s\u3000]+", "", s or "")


def output_path(card, folder=OUTPUT_DIR, taken=None):
    """保存先: 注文番号_名刺の氏名（なければ会社名）_注文者氏名.ai

    Yahoo! は注文者名がないので「注文番号_氏名.ai」。同じ名前があれば _2, _3 … を付ける。
    taken: 今回まとめて作るほかの名刺の保存先（まだファイルがないので、ここで重ならないようにする）
    """
    taken = taken if taken is not None else set()
    parts = [_clean_name(card.get("注文番号")) or "注文番号なし",
             _clean_name(card.get("氏名")) or _clean_name(card.get("会社名")) or "名前なし"]
    if _clean_name(card.get("注文者")):
        parts.append(_clean_name(card["注文者"]))
    base = os.path.join(folder, "_".join(parts))
    path, n = base + ".ai", 2
    while os.path.exists(path) or path in taken:
        path, n = f"{base}_{n}.ai", n + 1
    taken.add(path)
    return path


def write_csv(path, cards):
    """CSV を書き出す（Excel でも文字化けしない UTF-8 BOM 付き）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
        w.writeheader()
        for card in cards:
            w.writerow({c: card.get(c, "") for c in CSV_COLUMNS})


def write_job(path, cards):
    """Illustrator への指示ファイルを書く。

    文字コードの違いで化けないよう、項目名も値も UTF-8 のパーセント表記（英数字だけ）にする。
    形式は meishi_core.jsx の parseJob を参照。
    """
    def enc(s):
        return urllib.parse.quote(str(s), safe="")
    lines = ["MEISHIJOB1"]
    for card in cards:
        lines += [enc(c) + "\t" + enc(card.get(c, "")) for c in CSV_COLUMNS if card.get(c, "") != ""]
        lines.append("")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


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
    '//  \\u540D\\u523A\\u81EA\\u52D5\\u4F5C\\u6210\\uFF08\\u6CE8\\u6587\\u901A\\u77E5\\u30A2\\u30D7\\u30EA\\u306E\\uFF3B\\u540D\\u523A\\u3092\\u4F5C\\u6210\\uFF3D\\u30DC\\u30BF\\u30F3\\u304B\\u3089\\u547C\\u3070\\u308C\\u308B\\u30B9\\u30AF\\u30EA\\u30D7\\u30C8\\uFF09\n'
    '//\n'
    '//  \\u6CE8\\u6587\\u901A\\u77E5\\u30A2\\u30D7\\u30EA\\u304C\\u66F8\\u304D\\u51FA\\u3057\\u305F\\u300Cmeishi_job.txt\\u300D\\u3092\\u8AAD\\u307F\\u3001\\u6CE8\\u6587\\u3054\\u3068\\u306B\n'
    '//    1. \\u6307\\u5B9A\\u3055\\u308C\\u305F\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8(.ai)\\u3092\\u958B\\u304F\n'
    '//    2. \\u6CE8\\u6587\\u5185\\u5BB9\\u3092\\u6D41\\u3057\\u8FBC\\u3080\n'
    '//    3. \\u6307\\u5B9A\\u3055\\u308C\\u305F\\u540D\\u524D\\u3067\\u5225\\u540D\\u4FDD\\u5B58\\u3059\\u308B\n'
    '//    4. \\u305D\\u306E\\u307E\\u307E Illustrator \\u3067\\u958B\\u3044\\u3066\\u304A\\u304F\n'
    '//  \\u6700\\u5F8C\\u306B\\u3001\\u78BA\\u8A8D\\u3057\\u3066\\u307B\\u3057\\u3044\\u3053\\u3068\\uFF08\\u8981\\u78BA\\u8A8D\\uFF09\\u304C\\u3042\\u308C\\u3070\\u8868\\u793A\\u3057\\u307E\\u3059\\u3002\n'
    '//\n'
    '//  meishi_core.jsx\\u30FBmeishi_ai.jsx \\u3092\\u540C\\u3058\\u30D5\\u30A9\\u30EB\\u30C0\\u306B\\u7F6E\\u3044\\u3066\\u304F\\u3060\\u3055\\u3044\\u3002\n'
    '// =====================================================================\n'
    '\n'
    '#target illustrator\n'
    '// =====================================================================\n'
    '//  \\u540D\\u523A\\u81EA\\u52D5\\u4F5C\\u6210 \\u2014 \\u5171\\u901A\\u30ED\\u30B8\\u30C3\\u30AF\\uFF08Illustrator \\u306B\\u4F9D\\u5B58\\u3057\\u306A\\u3044\\u90E8\\u5206\\uFF09\n'
    '//\n'
    '//  Illustrator CS6 \\u306E ExtendScript \\u3067\\u3082\\u52D5\\u304F\\u3088\\u3046\\u306B\\u3001\\u53E4\\u3044 JavaScript (ES3)\n'
    '//  \\u306E\\u66F8\\u304D\\u65B9\\u3060\\u3051\\u3092\\u4F7F\\u3063\\u3066\\u3044\\u307E\\u3059\\uFF08let / const / => / forEach / JSON \\u306F\\u4E0D\\u53EF\\uFF09\\u3002\n'
    '//  \\u540C\\u3058\\u30D5\\u30A1\\u30A4\\u30EB\\u3092 Node.js \\u306E\\u30C6\\u30B9\\u30C8 (test/test_core.js) \\u304B\\u3089\\u3082\\u8AAD\\u307F\\u8FBC\\u307F\\u307E\\u3059\\u3002\n'
    '// =====================================================================\n'
    '\n'
    'var MeishiCore = (function () {\n'
    '\n'
    '    // -----------------------------------------------------------------\n'
    '    //  1. \\u6CE8\\u6587CSV\\u306E\\u5217\\u540D \\u2192 \\u3053\\u306E\\u30A2\\u30D7\\u30EA\\u5185\\u306E\\u9805\\u76EE\\u540D\n'
    '    //     \\u697D\\u5929\\u30FBYahoo! \\u306ECSV\\u3084\\u624B\\u4F5C\\u308A\\u306ECSV\\u3067\\u5217\\u540D\\u304C\\u9055\\u3063\\u3066\\u3082\\u3001\\u3053\\u3053\\u306B\n'
    '    //     \\u5225\\u540D\\u3092\\u8DB3\\u305B\\u3070\\u8AAD\\u3081\\u308B\\u3088\\u3046\\u306B\\u306A\\u308A\\u307E\\u3059\\u3002\n'
    '    // -----------------------------------------------------------------\n'
    '    var FIELD_ALIASES = {\n'
    '        "\\u6CE8\\u6587\\u756A\\u53F7":   ["\\u6CE8\\u6587\\u756A\\u53F7", "\\u53D7\\u6CE8\\u756A\\u53F7", "\\u6CE8\\u6587ID", "OrderId"],\n'
    '        "\\u30C7\\u30B6\\u30A4\\u30F3\\u756A\\u53F7": ["\\u30C7\\u30B6\\u30A4\\u30F3\\u756A\\u53F7", "\\u30C7\\u30B6\\u30A4\\u30F3", "\\u54C1\\u756A"],\n'
    '        "\\u4F1A\\u793E\\u540D":     ["\\u4F1A\\u793E\\u540D", "\\u793E\\u540D", "\\u5C4B\\u53F7"],\n'
    '        "\\u90E8\\u7F72":       ["\\u90E8\\u7F72", "\\u90E8\\u7F72\\u540D"],\n'
    '        "\\u80A9\\u66F8":       ["\\u80A9\\u66F8", "\\u80A9\\u66F8\\u304D", "\\u5F79\\u8077"],\n'
    '        "\\u6C0F\\u540D":       ["\\u6C0F\\u540D", "\\u540D\\u524D", "\\u304A\\u540D\\u524D", "\\u540D\\u523A\\u306E\\u540D\\u524D"],\n'
    '        "\\u6C0F\\u540D\\u82F1\\u5B57":   ["\\u6C0F\\u540D\\u82F1\\u5B57", "\\u30ED\\u30FC\\u30DE\\u5B57", "\\u6C0F\\u540D\\u30ED\\u30FC\\u30DE\\u5B57", "\\u82F1\\u5B57\\u6C0F\\u540D"],\n'
    '        "\\u80A9\\u66F8\\u82F1\\u5B57":   ["\\u80A9\\u66F8\\u82F1\\u5B57", "\\u82F1\\u5B57\\u80A9\\u66F8", "\\u5F79\\u8077\\u82F1\\u5B57"],\n'
    '        "\\u4F1A\\u793E\\u540D\\u82F1\\u5B57": ["\\u4F1A\\u793E\\u540D\\u82F1\\u5B57", "\\u82F1\\u5B57\\u4F1A\\u793E\\u540D"],\n'
    '        "\\u90F5\\u4FBF\\u756A\\u53F7":   ["\\u90F5\\u4FBF\\u756A\\u53F7", "\\u3012"],\n'
    '        "\\u4F4F\\u62401":      ["\\u4F4F\\u62401", "\\u4F4F\\u6240", "\\u4F4F\\u6240\\uFF11"],\n'
    '        "\\u4F4F\\u62402":      ["\\u4F4F\\u62402", "\\u4F4F\\u6240\\uFF12", "\\u5EFA\\u7269\\u540D"],\n'
    '        "\\u82F1\\u5B57\\u4F4F\\u62401":  ["\\u82F1\\u5B57\\u4F4F\\u62401", "\\u82F1\\u5B57\\u4F4F\\u6240", "\\u82F1\\u5B57\\u4F4F\\u6240\\uFF11"],\n'
    '        "\\u82F1\\u5B57\\u4F4F\\u62402":  ["\\u82F1\\u5B57\\u4F4F\\u62402", "\\u82F1\\u5B57\\u4F4F\\u6240\\uFF12"],\n'
    '        "TEL":        ["TEL", "Tel", "\\u96FB\\u8A71", "\\u96FB\\u8A71\\u756A\\u53F7"],\n'
    '        "FAX":        ["FAX", "Fax", "\\u30D5\\u30A1\\u30C3\\u30AF\\u30B9"],\n'
    '        "\\u643A\\u5E2F":       ["\\u643A\\u5E2F", "\\u643A\\u5E2F\\u96FB\\u8A71", "Mobile"],\n'
    '        "\\u30E1\\u30FC\\u30EB":     ["\\u30E1\\u30FC\\u30EB", "\\u30E1\\u30FC\\u30EB\\u30A2\\u30C9\\u30EC\\u30B9", "E-mail", "Email"],\n'
    '        "URL":        ["URL", "\\u30DB\\u30FC\\u30E0\\u30DA\\u30FC\\u30B8", "Web\\u30B5\\u30A4\\u30C8"],\n'
    '        // \\u4EE5\\u4E0B\\u306F\\u540D\\u523A\\u306B\\u76F4\\u63A5\\u306F\\u5165\\u3089\\u306A\\u3044\\u9805\\u76EE\\uFF08\\u51E6\\u7406\\u7D50\\u679C\\u306E\\u300C\\u8981\\u78BA\\u8A8D\\u300D\\u306B\\u8868\\u793A\\u3059\\u308B\\uFF09\n'
    '        "\\u30E2\\u30FC\\u30EB":     ["\\u30E2\\u30FC\\u30EB"],\n'
    '        "\\u3075\\u308A\\u304C\\u306A":   ["\\u3075\\u308A\\u304C\\u306A", "\\u30D5\\u30EA\\u30AC\\u30CA"],\n'
    '        "\\u30ED\\u30B4\\u30C7\\u30FC\\u30BF": ["\\u30ED\\u30B4\\u30C7\\u30FC\\u30BF", "\\u30ED\\u30B4"],\n'
    '        "\\u81EA\\u7531\\u884C":     ["\\u81EA\\u7531\\u884C", "\\u884C\\u76EE"],\n'
    '        "\\u5099\\u8003":       ["\\u5099\\u8003", "\\u5F53\\u5E97\\u3078\\u306E\\u5099\\u8003"],\n'
    '        "\\u78BA\\u8A8D\\u4E8B\\u9805":   ["\\u78BA\\u8A8D\\u4E8B\\u9805"],\n'
    '        "\\u6CE8\\u6587\\u8005":     ["\\u6CE8\\u6587\\u8005", "\\u6CE8\\u6587\\u8005\\u540D"],\n'
    '        // \\u6CE8\\u6587\\u901A\\u77E5\\u30A2\\u30D7\\u30EA\\u306E\\uFF3B\\u540D\\u523A\\u3092\\u4F5C\\u6210\\uFF3D\\u304B\\u3089\\u6E21\\u3055\\u308C\\u308B\\u6307\\u793A\n'
    '        "\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8": ["\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8"],\n'
    '        "\\u4FDD\\u5B58\\u5148":     ["\\u4FDD\\u5B58\\u5148"]\n'
    '    };\n'
    '\n'
    '    // \\u540D\\u523A\\u306B\\u5DEE\\u3057\\u8FBC\\u307E\\u306A\\u3044\\u9805\\u76EE\\uFF08\\u300C\\u5DEE\\u3057\\u8FBC\\u307F\\u5148\\u304C\\u306A\\u3044\\u300D\\u306E\\u8B66\\u544A\\u304B\\u3089\\u5916\\u3059\\uFF09\n'
    '    var INFO_FIELDS = ["\\u6CE8\\u6587\\u756A\\u53F7", "\\u30C7\\u30B6\\u30A4\\u30F3\\u756A\\u53F7", "\\u90E8\\u7F72", "\\u30E2\\u30FC\\u30EB", "\\u3075\\u308A\\u304C\\u306A", "\\u30ED\\u30B4\\u30C7\\u30FC\\u30BF", "\\u81EA\\u7531\\u884C", "\\u5099\\u8003", "\\u78BA\\u8A8D\\u4E8B\\u9805",\n'
    '                       "\\u6CE8\\u6587\\u8005", "\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8", "\\u4FDD\\u5B58\\u5148"];\n'
    '\n'
    '    // -----------------------------------------------------------------\n'
    '    //  2. \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306B\\u5165\\u3063\\u3066\\u3044\\u308B\\u300C\\u4EEE\\u306E\\u6587\\u5B57\\u300D\\u2192 \\u9805\\u76EE\\u540D\n'
    '    //     \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u4EEE\\u306E\\u6587\\u5B57\\u304C\\u5897\\u3048\\u305F\\u3089\\u3001\\u3053\\u3053\\u306B\\u8DB3\\u3057\\u3066\\u3044\\u304D\\u307E\\u3059\\u3002\n'
    '    //     \\u30FB\\u7A7A\\u767D\\uFF08\\u534A\\u89D2\\u30FB\\u5168\\u89D2\\uFF09\\u306F\\u7121\\u8996\\u3057\\u3066\\u63A2\\u3057\\u307E\\u3059\\uFF08\\u9234\\u3000\\u6728\\u3000\\u592A\\u3000\\u90CE \\u3082\\u9234\\u6728\\u592A\\u90CE\\u3082\\u540C\\u3058\\uFF09\n'
    '    //     \\u30FBspaced: true \\u306E\\u9805\\u76EE\\u306F\\u3001\\u4EEE\\u306E\\u6587\\u5B57\\u304C1\\u6587\\u5B57\\u305A\\u3064\\u7A7A\\u3051\\u3066\\u3042\\u308C\\u3070\n'
    '    //       \\u304A\\u5BA2\\u3055\\u3093\\u306E\\u540D\\u524D\\u3082\\u540C\\u3058\\u7A7A\\u3051\\u65B9\\u306B\\u305D\\u308D\\u3048\\u307E\\u3059\n'
    '    //     \\u30FBwholeLine: true \\u306E\\u9805\\u76EE\\u306F\\u300C\\u305D\\u306E\\u884C\\u304C\\u305D\\u306E\\u6587\\u5B57\\u3060\\u3051\\u300D\\u306E\\u3068\\u304D\\u3060\\u3051\\u7F6E\\u304D\\u63DB\\u3048\\u307E\\u3059\n'
    '    // -----------------------------------------------------------------\n'
    '    //     \\u30FBusedAs \\u306F\\u300C\\u5DEE\\u3057\\u8FBC\\u307F\\u5148\\u3042\\u308A\\u300D\\u306E\\u5224\\u5B9A\\u306B\\u4F7F\\u3046\\u5143\\u306E\\u9805\\u76EE\\u540D\n'
    '    //     \\u30FB\\u25CB \\u3068 \\u3007 \\u306F\\u540C\\u3058\\u6587\\u5B57\\u3068\\u3057\\u3066\\u63A2\\u3057\\u307E\\u3059\\u3002\\u540C\\u3058\\u9805\\u76EE\\u306E\\u4E2D\\u3067\\u306F\\u9577\\u3044\\u6587\\u5B57\\u304B\\u3089\\u5148\\u306B\\u63A2\\u3057\\u307E\\u3059\n'
    '    var PLACEHOLDERS = [\n'
    '        { field: "\\u6C0F\\u540D",       spaced: true,\n'
    '          texts: ["\\u9234\\u6728\\u592A\\u90CE", "\\u9234\\u6728\\u82B1\\u5B50", "\\u9234\\u6728\\u4E00\\u90CE", "\\u4F50\\u85E4\\u4E00\\u90CE", "\\u6D77\\u5C71\\u5DDD\\u5730", "\\u4E2D\\u6751\\u7D75\\u7F8E"] },\n'
    '        // \\u300C\\u30ED\\u30B4\\u30C7\\u30FC\\u30BF\\u300D\\u304C\\u7121\\u3057\\u306A\\u3089 LOGO \\u306E\\u4F4D\\u7F6E\\u306B\\u4F1A\\u793E\\u540D\\u304C\\u5165\\u308B\\uFF08\\u6709\\u308A\\u306A\\u3089\\u30ED\\u30B4\\u3092\\u624B\\u4F5C\\u696D\\u3067\\u914D\\u7F6E\\uFF09\n'
    '        { field: "\\u4F1A\\u793E\\u540D",     wholeLine: true, logo: true,\n'
    '          texts: ["LOGO", "Logo", "ROGO", "rogo", "L\\u25C9G\\u25C9"] },\n'
    '        // \\u6587\\u5B57\\u306E\\u30ED\\u30B4\\uFF08\\u82F1\\u8A9E\\u9762\\u3067\\u306F\\u82F1\\u5B57\\u306E\\u4F1A\\u793E\\u540D\\u304C\\u3042\\u308C\\u3070\\u305D\\u3061\\u3089\\u3092\\u4F7F\\u3046\\uFF09\n'
    '        { field: "\\u4F1A\\u793E\\u540D",     wholeLine: true, logo: true, altField: "\\u4F1A\\u793E\\u540D\\u82F1\\u5B57",\n'
    '          texts: ["artcode", "\\u30A2\\u30FC\\u30C8\\u30B3\\u30FC\\u30C9"] },\n'
    '        // \\u4F1A\\u793E\\u540D\\u306E\\u4EEE\\u306E\\u6587\\u5B57\\u3082 LOGO \\u3068\\u540C\\u3058\\u6271\\u3044\\uFF08\\u30ED\\u30B4\\u30C7\\u30FC\\u30BF\\u6709\\u308A\\u306A\\u3089\\u305D\\u306E\\u307E\\u307E\\u30FB\\u7121\\u3057\\u306A\\u3089\\u4F1A\\u793E\\u540D\\u30FB\\u6A2A\\u306E\\u30DE\\u30FC\\u30AF\\u3092\\u6D88\\u3059\\uFF09\n'
    '        { field: "\\u4F1A\\u793E\\u540D",     wholeLine: true, logo: true,\n'
    '          texts: ["\\u682A\\u5F0F\\u4F1A\\u793E\\u25CF\\u25CF\\u5546\\u4E8B", "\\u682A\\u5F0F\\u4F1A\\u793E\\u6D77\\u5C71\\u5546\\u4E8B", "\\u25CB\\u25CB\\u5546\\u4E8B\\u25CB\\u25CB\\u25CB\\u4F01\\u753B\\u8AB2",\n'
    '                  "\\u682A\\u5F0F\\u4F1A\\u793E\\u25CB\\u25CB\\u5546\\u4E8B", "\\u682A\\u5F0F\\u4F1A\\u793E\\u25CB\\u25CB\\u25CB\\u5546\\u4E8B", "\\u682A\\u5F0F\\u4F1A\\u793E\\u25CB\\u25CB\\u25CB\\u25CB\\u5546\\u4E8B", "\\u682A\\u5F0F\\u4F1A\\u793E\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u5546\\u4E8B"] },\n'
    '        // \\u300C\\u682A\\u5F0F\\u4F1A\\u793E\\u300D\\u3068\\u300C\\u25CB\\u25CB\\u5546\\u4E8B\\u300D\\u304C\\u5225\\u306E\\u884C\\u306B\\u306A\\u3063\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3\n'
    '        { field: "\\u4F1A\\u793E\\u540D_\\u524D",  wholeLine: true, usedAs: "\\u4F1A\\u793E\\u540D", logo: true, texts: ["\\u682A\\u5F0F\\u4F1A\\u793E"] },\n'
    '        { field: "\\u4F1A\\u793E\\u540D_\\u5F8C",  wholeLine: true, usedAs: "\\u4F1A\\u793E\\u540D", logo: true,\n'
    '          texts: ["\\u25CB\\u25CB\\u5546\\u4E8B", "\\u25CB\\u25CB\\u25CB\\u5546\\u4E8B", "\\u25CB\\u25CB\\u25CB\\u25CB\\u5546\\u4E8B", "\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u5546\\u4E8B", "\\u25CF\\u25CF\\u5546\\u4E8B", "\\u6D77\\u5C71\\u5546\\u4E8B"] },\n'
    '        { field: "\\u80A9\\u66F8",       texts: ["\\u4EE3\\u8868\\u53D6\\u7DE0\\u5F79"], spaced: true },\n'
    '        { field: "\\u80A9\\u66F8",       wholeLine: true, spaced: true,\n'
    '          texts: ["\\u5E97\\u9577", "\\u30AA\\u30FC\\u30CA\\u30FC", "\\u30B7\\u30E7\\u30C3\\u30D7\\u30AA\\u30FC\\u30CA\\u30FC", "\\u53D6\\u7DE0\\u5F79\\u793E\\u9577", "\\u4EE3\\u8868", "\\u55B6\\u696D\\u4E8B\\u52D9", "\\u55B6\\u696D\\u8AB2\\u9577", "\\u8AB2\\u9577",\n'
    '                  "\\u4FDD\\u80B2\\u58EB", "\\u6599\\u7406\\u9577", "\\u6599\\u7406\\u7814\\u7A76\\u5BB6", "\\u30E9\\u30A4\\u30BF\\u30FC", "\\u30B7\\u30F3\\u30AC\\u30FC\\u30BD\\u30F3\\u30B0\\u30E9\\u30A4\\u30BF\\u30FC", "\\u30B9\\u30BF\\u30A4\\u30EA\\u30B9\\u30C8",\n'
    '                  "\\u30A4\\u30F3\\u30B9\\u30C8\\u30E9\\u30AF\\u30BF\\u30FC", "\\u53F8\\u66F8\\u88DC", "\\u30AB\\u30E1\\u30E9\\u30DE\\u30F3", "\\u30D0\\u30A4\\u30E4\\u30FC", "\\u5148\\u751F", "\\u30DC\\u30E9\\u30F3\\u30C6\\u30A3\\u30A2"] },\n'
    '        { field: "\\u6C0F\\u540D\\u82F1\\u5B57",   texts: ["Ichiro Suzuki", "Taro Suzuki", "Hanako Suzuki", "Emi Nakamura"] },\n'
    '        { field: "\\u80A9\\u66F8\\u82F1\\u5B57",   texts: ["President"], wholeLine: true },\n'
    '        { field: "\\u4F4F\\u62401",\n'
    '          texts: ["\\u25CB\\u25CB\\u25CB\\u770C\\u25CB\\u25CB\\u5E02\\u25CB\\u25CB\\u753A00-00-0", "\\u25CB\\u25CB\\u25CB\\u770C\\u25CB\\u25CB\\u5E02\\u25CB\\u25CB\\u753A0-00-0", "\\u25CB\\u25CB\\u25CB\\u770C\\u25CB\\u25CB\\u25CB\\u25CB\\u5E02\\u25CB\\u25CB\\u25CB\\u753A1-1-1",\n'
    '                  "\\u25CB\\u25CB\\u25CB\\u770C\\u25CB\\u25CB\\u25CB\\u5E02\\u25CB\\u25CB\\u25CB\\u753A1-2-3", "\\u25CB\\u25CB\\u25CB\\u770C\\u25CB\\u25CB\\u25CB\\u5E02\\u25CB\\u25CB\\u25CB\\u753A\\u25CB\\u25CB\\u30FC\\u25CB\\u30FC\\u25CB\\u25CB", "\\u25CB\\u25CB\\u770C\\u25CB\\u25CB\\u5E02\\u25CB\\u25CB\\u753A00-00-0",\n'
    '                  "\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB\\u753A000-0000", "\\u25CB\\u25CB\\u25CB\\u770C\\u25CB\\u25CB\\u5E02\\u25CB\\u25CB\\u753A"] },\n'
    '        { field: "\\u4F4F\\u62402",      texts: ["00-00-0\\u25CB\\u25CB\\u25CB\\u25CB000\\u53F7", "\\u25CB\\u25CB\\u25CB\\u25CB\\u25CB000\\u53F7", "\\u25CB\\u25CB\\u25CB000\\u53F7"] },\n'
    '        { field: "\\u30E1\\u30FC\\u30EB",     texts: ["ooooo@oooo.com"] },\n'
    '        { field: "URL",        texts: ["http://www.0123456.jp/"] },\n'
    '        { field: "\\u82F1\\u5B57\\u4F4F\\u62401",  texts: ["6-1-1-3 Hirasaku,Yokosuka city,"] },\n'
    '        { field: "\\u82F1\\u5B57\\u4F4F\\u62402",  texts: ["Kanagawa 238-0032,Japan"] }\n'
    '    ];\n'
    '\n'
    '    // \\u4F1A\\u793E\\u540D\\u3092\\u300C\\u682A\\u5F0F\\u4F1A\\u793E\\u300D\\u3068\\u300C\\u6B8B\\u308A\\u300D\\u306B\\u5206\\u3051\\u308B\\uFF08\\u300C\\u682A\\u5F0F\\u4F1A\\u793E\\u300D\\u306E\\u884C\\u304C\\u5225\\u306B\\u306A\\u3063\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3\\u7528\\uFF09\n'
    '    var COMPANY_PREFIX = /^(\\u682A\\u5F0F\\u4F1A\\u793E|\\u6709\\u9650\\u4F1A\\u793E|\\u5408\\u540C\\u4F1A\\u793E|\\u5408\\u8CC7\\u4F1A\\u793E|\\u5408\\u540D\\u4F1A\\u793E|\\u4E00\\u822C\\u793E\\u56E3\\u6CD5\\u4EBA|\\u4E00\\u822C\\u8CA1\\u56E3\\u6CD5\\u4EBA|\\u516C\\u76CA\\u793E\\u56E3\\u6CD5\\u4EBA|\\u516C\\u76CA\\u8CA1\\u56E3\\u6CD5\\u4EBA|\\u533B\\u7642\\u6CD5\\u4EBA\\u793E\\u56E3|\\u533B\\u7642\\u6CD5\\u4EBA|\\u793E\\u4F1A\\u798F\\u7949\\u6CD5\\u4EBA|\\u5B66\\u6821\\u6CD5\\u4EBA|\\u7279\\u5B9A\\u975E\\u55B6\\u5229\\u6D3B\\u52D5\\u6CD5\\u4EBA|NPO\\u6CD5\\u4EBA)[ \\t\\u3000]*/;\n'
    '\n'
    '    // -----------------------------------------------------------------\n'
    '    //  3. \\u300CTel :\\u300D\\u300CFax :\\u300D\\u306A\\u3069\\u306E\\u898B\\u51FA\\u3057\\u306E\\u5F8C\\u308D\\u306B\\u3042\\u308B\\u5024\\u3092\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\u9805\\u76EE\n'
    '    // -----------------------------------------------------------------\n'
    '    var LABELS = [\n'
    '        { field: "TEL",    words: ["Tel", "TEL", "\\u96FB\\u8A71", "\\uFF34\\uFF25\\uFF2C"] },\n'
    '        { field: "FAX",    words: ["Fax", "FAX", "\\uFF26\\uFF21\\uFF38"] },\n'
    '        { field: "\\u643A\\u5E2F",   words: ["Mobile", "Mob", "Cell", "\\u643A\\u5E2F"] },\n'
    '        { field: "\\u30E1\\u30FC\\u30EB", words: ["E-mail", "Email", "Mail"] },\n'
    '        { field: "URL",    words: ["URL", "Web", "HP"] }\n'
    '    ];\n'
    '\n'
    '    // \\u7F6E\\u304D\\u63DB\\u3048\\u5F8C\\u306B\\u3001\\u3053\\u306E\\u6587\\u5B57\\u304C\\u6B8B\\u3063\\u3066\\u3044\\u305F\\u3089\\u300C\\u7F6E\\u304D\\u63DB\\u3048\\u6F0F\\u308C\\u304B\\u3082\\u300D\\u3068\\u8B66\\u544A\\u3059\\u308B\n'
    '    var LEFTOVER_PATTERNS = [/[\\u25CB\\u3007]/, /000-/, /ooooo@/, /0123456/];\n'
    '\n'
    '    var WS = "[ \\\\t\\\\u3000]";           // \\u7A7A\\u767D\\uFF08\\u534A\\u89D2\\u30FB\\u5168\\u89D2\\u30FB\\u30BF\\u30D6\\uFF09\n'
    '    var COLON = "\\uFF1A";                   // \\u898B\\u51FA\\u3057\\u3068\\u5024\\u306E\\u9593\\u306E\\u30B3\\u30ED\\u30F3\\uFF08\\u5168\\u89D2\\u30FB\\u524D\\u5F8C\\u306E\\u7A7A\\u767D\\u306A\\u3057\\uFF09\n'
    '    var LINE_BREAK = /[\\r\\n\\u0003]/;   // Illustrator \\u306E\\u6539\\u884C\\uFF08\\r\\uFF09\\u3068\\u5F37\\u5236\\u6539\\u884C\\uFF08\\u0003\\uFF09\n'
    '\n'
    '    // ===== \\u5C0F\\u3055\\u306A\\u9053\\u5177 =====================================================\n'
    '\n'
    '    function trim(s) {\n'
    '        return String(s).replace(/^[ \\t\\u3000\\r\\n]+|[ \\t\\u3000\\r\\n]+$/g, "");\n'
    '    }\n'
    '\n'
    '    function escapeRegex(s) {\n'
    '        return s.replace(/[\\\\^$.*+?()[\\]{}|\\/-]/g, "\\\\$&");\n'
    '    }\n'
    '\n'
    '    // "Tel" \\u2192 /T[ \\t\\u3000]*e[ \\t\\u3000]*l/ \\u306E\\u3088\\u3046\\u306B\\u3001\\u6587\\u5B57\\u306E\\u9593\\u306E\\u7A7A\\u767D\\u3092\\u8A31\\u3059\\u6B63\\u898F\\u8868\\u73FE\\u306E\\u6587\\u5B57\\u5217\n'
    '    function looseSource(text, sep) {\n'
    '        var out = [];\n'
    '        for (var i = 0; i < text.length; i++) {\n'
    '            var c = text.charAt(i);\n'
    '            if (/[ \\t\\u3000]/.test(c)) continue;\n'
    '            out.push(c === "\\u25CB" || c === "\\u3007" ? "[\\u25CB\\u3007]" : escapeRegex(c));\n'
    '        }\n'
    '        return out.join((sep || WS) + "*");\n'
    '    }\n'
    '\n'
    '    function inArray(arr, v) {\n'
    '        for (var i = 0; i < arr.length; i++) if (arr[i] === v) return true;\n'
    '        return false;\n'
    '    }\n'
    '\n'
    '    // ===== CSV ============================================================\n'
    '\n'
    '    // CSV\\u306E\\u6587\\u5B57\\u5217 \\u2192 \\u884C\\u306E\\u914D\\u5217\\uFF08\\u5404\\u884C\\u306F\\u5217\\u306E\\u914D\\u5217\\uFF09\\u3002"..." \\u3067\\u56F2\\u3093\\u3060\\u5024\\u3001\\u5024\\u306E\\u4E2D\\u306E\\u6539\\u884C\\u30FB\\u30AB\\u30F3\\u30DE\\u306B\\u3082\\u5BFE\\u5FDC\\u3002\n'
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
    '        // \\u7A7A\\u884C\\u3092\\u6368\\u3066\\u308B\n'
    '        var out = [];\n'
    '        for (var r = 0; r < rows.length; r++) {\n'
    '            if (trim(rows[r].join("")) !== "") out.push(rows[r]);\n'
    '        }\n'
    '        return out;\n'
    '    }\n'
    '\n'
    '    // 1\\u884C\\u76EE\\u3092\\u898B\\u51FA\\u3057\\u3068\\u3057\\u3066\\u3001\\u5404\\u884C\\u3092 { \\u9805\\u76EE\\u540D: \\u5024 } \\u306B\\u5909\\u3048\\u308B\n'
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
    '    // \\u90E8\\u7F72\\u306F\\u5225\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u3068\\u3057\\u3066\\u80A9\\u66F8\\u306E\\u4E0A\\u306B\\u5165\\u308C\\u308B\\uFF08meishi_ai.jsx\\uFF09\n'
    '    function prepareValues(rec) {\n'
    '        var v = {};\n'
    '        for (var k in rec) if (rec.hasOwnProperty(k)) v[k] = rec[k];\n'
    '        var company = v["\\u4F1A\\u793E\\u540D"] || "";\n'
    '        var m = company.match(COMPANY_PREFIX);\n'
    '        v["\\u4F1A\\u793E\\u540D_\\u524D"] = m ? m[1] : "";\n'
    '        v["\\u4F1A\\u793E\\u540D_\\u5F8C"] = m ? company.substring(m[0].length) : company;\n'
    '        return v;\n'
    '    }\n'
    '\n'
    '    // \\u30C6\\u30AD\\u30B9\\u30C8\\u304C\\u300CE-mail\\u300D\\u306E\\u3088\\u3046\\u306A\\u898B\\u51FA\\u3057\\u3060\\u3051\\u306A\\u3089\\u3001\\u305D\\u306E\\u9805\\u76EE\\u540D\\u3092\\u8FD4\\u3059\\uFF08\\u5024\\u304C\\u5225\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306B\\u306A\\u3063\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3\\u7528\\uFF09\n'
    '    function labelOnlyField(text) {\n'
    '        for (var L = 0; L < LABELS.length; L++) {\n'
    '            for (var w = 0; w < LABELS[L].words.length; w++) {\n'
    '                var only = new RegExp("^" + WS + "*" + looseSource(LABELS[L].words[w]) + WS + "*[:\\uFF1A]?" + WS + "*$");\n'
    '                if (only.test(text)) return LABELS[L].field;\n'
    '            }\n'
    '        }\n'
    '        return null;\n'
    '    }\n'
    '\n'
    '    // \\u305D\\u306E\\u6587\\u5B57\\u304C\\u300CLOGO\\u300D\\u306A\\u3069\\u30ED\\u30B4\\u306E\\u4EEE\\u306E\\u6587\\u5B57\\u304B\\uFF08LOGO \\u6A2A\\u306E\\u30DE\\u30FC\\u30AF\\u3092\\u63A2\\u3059\\u3068\\u304D\\u306B\\u4F7F\\u3046\\uFF09\n'
    '    function isLogoText(text) {\n'
    '        var t = String(text).replace(/[ \\t\\u3000\\r\\n\\u0003]/g, "").replace(/\\u3007/g, "\\u25CB");\n'
    '        if (/^(\\u682A\\u5F0F\\u4F1A\\u793E)?([\\u25CB\\u25CF]+|\\u6D77\\u5C71)\\u5546\\u4E8B$/.test(t)) return true;   // \\u300C\\u682A\\u5F0F\\u4F1A\\u793E\\u300D\\u300C\\u25CB\\u25CB\\u25CB\\u25CB\\u5546\\u4E8B\\u300D\\u304C2\\u884C\\u306E\\u30C7\\u30B6\\u30A4\\u30F3\\u3082\n'
    '        for (var k = 0; k < PLACEHOLDERS.length; k++) {\n'
    '            if (!PLACEHOLDERS[k].logo || PLACEHOLDERS[k].field === "\\u4F1A\\u793E\\u540D_\\u524D") continue;   // \\u300C\\u682A\\u5F0F\\u4F1A\\u793E\\u300D\\u3060\\u3051\\u3067\\u306F\\u5224\\u65AD\\u3057\\u306A\\u3044\n'
    '            for (var i = 0; i < PLACEHOLDERS[k].texts.length; i++) {\n'
    '                if (PLACEHOLDERS[k].texts[i] === t) return true;\n'
    '            }\n'
    '        }\n'
    '        return false;\n'
    '    }\n'
    '\n'
    '    // \\u30ED\\u30B4\\u30C7\\u30FC\\u30BF\\u304C\\u300C\\u6709\\u308A\\u300D\\u306E\\u6CE8\\u6587\\u304B\n'
    '    function hasLogoData(rec) {\n'
    '        return /^[ \\t\\u3000]*\\u6709/.test(rec["\\u30ED\\u30B4\\u30C7\\u30FC\\u30BF"] || "");\n'
    '    }\n'
    '\n'
    '    // ===== \\u5DEE\\u3057\\u8FBC\\u307F\\u4F4D\\u7F6E\\u3092\\u63A2\\u3059 =============================================\n'
    '\n'
    '    // \\u6587\\u5B57\\u5217 contents\\uFF081\\u3064\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306E\\u4E2D\\u8EAB\\uFF09\\u306B\\u3064\\u3044\\u3066\\u3001\\u3069\\u3053\\u3092\\u4F55\\u306B\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\u304B\\u3092\\u8FD4\\u3059\\u3002\n'
    '    //   edits:  [{ start, end, text, field }]   \\uFF08start\\u301Cend \\u3092 text \\u306B\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\uFF09\n'
    '    //   used:   \\u3053\\u306E\\u4E2D\\u3067\\u898B\\u3064\\u304B\\u3063\\u305F\\u9805\\u76EE\\u540D\\u306E\\u4E00\\u89A7\n'
    '    //   leftoverRemoved: \\u8A8D\\u8B58\\u3067\\u304D\\u306A\\u3044\\u4EEE\\u306E\\u6587\\u5B57\\uFF08\\u25CB\\u25CB\\u25CB\\u30FB000- \\u306A\\u3069\\uFF09\\u304C\\u6B8B\\u308B\\u305F\\u3081\\u6D88\\u3057\\u305F\\u884C\n'
    '    //   opts.keepLeftover \\u304C true \\u306E\\u3068\\u304D\\u306F\\u3001\\u305D\\u306E\\u884C\\u3092\\u6D88\\u3055\\u305A\\u306B leftover \\u306B\\u5165\\u308C\\u308B\\uFF08\\u691C\\u67FB\\u30C4\\u30FC\\u30EB\\u7528\\uFF09\n'
    '    function planEdits(contents, rec, opts) {\n'
    '        opts = opts || {};\n'
    '        var values = prepareValues(rec);\n'
    '        values.__logo = hasLogoData(rec);\n'
    '        var edits = [], used = [], leftoverRemoved = [], leftover = [], notes = [];\n'
    '\n'
    '        // \\u6C0F\\u540D\\u304C\\u300C\\u9234\\u6728\\u300D\\u300C\\u3000\\u82B1\\u5B50\\u300D\\u306E\\u3088\\u3046\\u306B2\\u884C\\u306B\\u5206\\u304B\\u308C\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3\\uFF08\\u7E26\\u66F8\\u304D\\u306A\\u3069\\uFF09\\u3092\\u5148\\u306B\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\u3002\n'
    '        // \\u7F6E\\u304D\\u63DB\\u3048\\u305F\\u90E8\\u5206\\u306F\\u884C\\u3054\\u3068\\u306E\\u51E6\\u7406\\u3067\\u89E6\\u3089\\u306A\\u3044\\u3088\\u3046\\u3001\\u5370\\u306E\\u6587\\u5B57\\uFF08\\u0001\\uFF09\\u3067\\u96A0\\u3057\\u3066\\u304A\\u304F\n'
    '        var masked = planMultiLineName(contents, values, edits, used, notes);\n'
    '\n'
    '        // \\u884C\\u3054\\u3068\\u306B\\u3001\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\u3068\\u3053\\u308D\\u3068\\u300C\\u884C\\u3054\\u3068\\u6D88\\u3059\\u304B\\u300D\\u3092\\u6C7A\\u3081\\u308B\n'
    '        var lines = [];\n'
    '        var lineStart = 0;\n'
    '        while (lineStart <= contents.length) {\n'
    '            var lineEnd = lineStart;\n'
    '            while (lineEnd < contents.length && !LINE_BREAK.test(contents.charAt(lineEnd))) lineEnd++;\n'
    '            var line = masked.substring(lineStart, lineEnd);\n'
    '            var lineEdits = planLine(line, values, used);\n'
    '\n'
    '            // \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u6587\\u5B57\\u306E\\u3046\\u3061\\u3001\\u7F6E\\u304D\\u63DB\\u3048\\u306A\\u304B\\u3063\\u305F\\u90E8\\u5206\\u306B\\u4EEE\\u306E\\u6587\\u5B57\\u304C\\u6B8B\\u3063\\u3066\\u3044\\u308B\\u304B\n'
    '            // \\uFF08\\u304A\\u5BA2\\u3055\\u3093\\u306E\\u5165\\u529B\\u3057\\u305F\\u5024\\u306F\\u6570\\u3048\\u306A\\u3044\\u3002\\u300C03-1000-2000\\u300D\\u306E\\u300C000-\\u300D\\u306A\\u3069\\u3092\\u8AA4\\u3063\\u3066\\u6D88\\u3055\\u306A\\u3044\\u305F\\u3081\\uFF09\n'
    '            var blanks = [];\n'
    '            for (var b = 0; b < lineEdits.length; b++) {\n'
    '                blanks.push({ start: lineEdits[b].start, end: lineEdits[b].end, text: "" });\n'
    '            }\n'
    '            var stillPlaceholder = hasLeftover(applyEditsToString(line, blanks));\n'
    '            if (stillPlaceholder) {\n'
    '                if (opts.keepLeftover) leftover.push(line);\n'
    '                else leftoverRemoved.push(line);\n'
    '            }\n'
    '            // \\u6D88\\u3059\\u3082\\u306E\\u3070\\u304B\\u308A\\u3067\\u4F55\\u3082\\u6B8B\\u3089\\u306A\\u3044\\u3001\\u307E\\u305F\\u306F\\u672A\\u5165\\u529B\\u306E\\u4EEE\\u306E\\u6587\\u5B57\\u304C\\u6B8B\\u308B \\u2192 \\u884C\\u3054\\u3068\\u6D88\\u3059\n'
    '            var remove = (stillPlaceholder && !opts.keepLeftover) ||\n'
    '                         (lineEdits.length > 0 && trim(applyEditsToString(line, lineEdits)) === "");\n'
    '            lines.push({ start: lineStart, end: lineEnd, edits: lineEdits, remove: remove });\n'
    '            if (lineEnd >= contents.length) break;\n'
    '            lineStart = lineEnd + 1;\n'
    '        }\n'
    '\n'
    '        // \\u305D\\u308C\\u305E\\u308C\\u306E\\u9805\\u76EE\\u304C\\u5143\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306E\\u4F55\\u6587\\u5B57\\u76EE\\u306B\\u3042\\u3063\\u305F\\u304B\\uFF08\\u3075\\u308A\\u304C\\u306A\\u30FB\\u90E8\\u7F72\\u540D\\u3092\\u7F6E\\u304F\\u4F4D\\u7F6E\\u3092\\u6C7A\\u3081\\u308B\\u305F\\u3081\\uFF09\n'
    '        var fieldPos = {};\n'
    '        for (var e0 = 0; e0 < edits.length; e0++) {\n'
    '            if (!fieldPos.hasOwnProperty(edits[e0].field)) fieldPos[edits[e0].field] = edits[e0].start;\n'
    '        }\n'
    '        for (var i0 = 0; i0 < lines.length; i0++) {\n'
    '            for (var k0 = 0; k0 < lines[i0].edits.length; k0++) {\n'
    '                var f0 = lines[i0].edits[k0].field;\n'
    '                if (!fieldPos.hasOwnProperty(f0)) fieldPos[f0] = lines[i0].edits[k0].start + lines[i0].start;\n'
    '            }\n'
    '        }\n'
    '\n'
    '        for (var i = 0; i < lines.length; i++) {\n'
    '            var L = lines[i];\n'
    '            if (!L.remove) {\n'
    '                for (var k = 0; k < L.edits.length; k++) {\n'
    '                    if (L.edits[k].field === "(\\u305D\\u306E\\u307E\\u307E)") continue;   // \\u30ED\\u30B4\\u6709\\u308A\\u3067\\u6B8B\\u3059\\u90E8\\u5206\\u306F\\u66F8\\u304D\\u63DB\\u3048\\u306A\\u3044\n'
    '                    var ed = { start: L.edits[k].start + L.start, end: L.edits[k].end + L.start,\n'
    '                               text: L.edits[k].text, field: L.edits[k].field };\n'
    '                    if (L.edits[k].hasOwnProperty("spacingFrom")) ed.spacingFrom = L.edits[k].spacingFrom + L.start;\n'
    '                    edits.push(ed);\n'
    '                }\n'
    '                continue;\n'
    '            }\n'
    '            // \\u524D\\u306B\\u6B8B\\u308B\\u884C\\u304C\\u3042\\u308C\\u3070\\u300C\\u524D\\u306E\\u6539\\u884C\\uFF0B\\u3053\\u306E\\u884C\\u300D\\u3092\\u6D88\\u3059\\u3002\n'
    '            // \\uFF08\\u300C\\u3053\\u306E\\u884C\\uFF0B\\u5F8C\\u308D\\u306E\\u6539\\u884C\\u300D\\u3092\\u6D88\\u3059\\u3068\\u3001Illustrator \\u3067\\u306F\\u6B21\\u306E\\u884C\\u304C\\u6D88\\u3057\\u305F\\u884C\\u306E\\u6BB5\\u843D\\u306E\\u8A2D\\u5B9A\n'
    '            //   \\uFF08\\u5B57\\u4E0B\\u3052\\u30FB\\u6587\\u5B57\\u7D44\\u307F\\u306A\\u3069\\uFF09\\u3092\\u5F15\\u304D\\u7D99\\u3044\\u3067\\u3001\\u884C\\u306E\\u982D\\u306B\\u3059\\u304D\\u9593\\u304C\\u3067\\u304D\\u308B\\u3053\\u3068\\u304C\\u3042\\u308B\\uFF09\n'
    '            var keptBefore = false, keptAfter = false;\n'
    '            for (var jb = 0; jb < i; jb++) if (!lines[jb].remove) { keptBefore = true; break; }\n'
    '            for (var j = i + 1; j < lines.length; j++) if (!lines[j].remove) { keptAfter = true; break; }\n'
    '            if (keptBefore && keptAfter) {\n'
    '                edits.push({ start: L.start - 1, end: L.end, text: "", field: "(\\u884C\\u524A\\u9664)" });\n'
    '            } else if (keptAfter) {\n'
    '                edits.push({ start: L.start, end: L.end + 1, text: "", field: "(\\u884C\\u524A\\u9664)" });   // \\u5148\\u982D\\u306E\\u884C\n'
    '            } else {\n'
    '                // \\u6700\\u5F8C\\u307E\\u3067\\u6D88\\u3059\\u884C\\u304C\\u7D9A\\u304F \\u2192 \\u524D\\u306E\\u6539\\u884C\\u304B\\u3089\\u30C6\\u30AD\\u30B9\\u30C8\\u306E\\u6700\\u5F8C\\u307E\\u3067\\u3092\\u307E\\u3068\\u3081\\u3066\\u6D88\\u3059\n'
    '                edits.push({ start: L.start > 0 ? L.start - 1 : 0, end: contents.length, text: "", field: "(\\u884C\\u524A\\u9664)" });\n'
    '                break;\n'
    '            }\n'
    '        }\n'
    '        edits.sort(function (a, b) { return a.start - b.start; });\n'
    '        return { edits: edits, used: used, leftoverRemoved: leftoverRemoved, leftover: leftover, notes: notes,\n'
    '                 fieldPos: fieldPos };\n'
    '    }\n'
    '\n'
    '    // \\u6C0F\\u540D\\u306E\\u4EEE\\u306E\\u6587\\u5B57\\u304C\\u6539\\u884C\\u3092\\u307E\\u305F\\u3044\\u3067\\u3044\\u305F\\u3089\\u3001\\u304A\\u5BA2\\u3055\\u3093\\u306E\\u540D\\u524D\\u3092\\u300C\\u59D3\\u300D\\u3068\\u300C\\u540D\\u300D\\u306B\\u5206\\u3051\\u3066\\u5165\\u308C\\u308B\\u3002\n'
    '    // \\u7F6E\\u304D\\u63DB\\u3048\\u305F\\u7BC4\\u56F2\\u3092\\u5370\\u306E\\u6587\\u5B57\\u3067\\u96A0\\u3057\\u305F contents \\u3092\\u8FD4\\u3059\n'
    '    function planMultiLineName(contents, values, edits, used, notes) {\n'
    '        if (!/[\\r\\n\\u0003]/.test(contents)) return contents;\n'
    '        var rule = null;\n'
    '        for (var k = 0; k < PLACEHOLDERS.length; k++) if (PLACEHOLDERS[k].field === "\\u6C0F\\u540D") { rule = PLACEHOLDERS[k]; break; }\n'
    '        var masked = contents;\n'
    '        var texts = rule.texts.slice(0).sort(function (a, b) { return b.length - a.length; });\n'
    '        for (var t = 0; t < texts.length; t++) {\n'
    '            var re = new RegExp(looseSource(texts[t], "[ \\\\t\\u3000\\\\r\\\\n\\u0003]"), "g");\n'
    '            var m;\n'
    '            while ((m = re.exec(masked)) !== null) {\n'
    '                var br = m[0].search(/[\\r\\n\\u0003]/);\n'
    '                if (br < 0) continue;                                   // 1\\u884C\\u306B\\u53CE\\u307E\\u3063\\u3066\\u3044\\u308B\\u3082\\u306E\\u306F\\u884C\\u3054\\u3068\\u306E\\u51E6\\u7406\\u306B\\u4EFB\\u305B\\u308B\n'
    '                var ms = m.index, me = m.index + m[0].length;\n'
    '                var p1e = ms + br;                                       // 1\\u884C\\u76EE\\u306E\\u7D42\\u308F\\u308A\n'
    '                while (p1e > ms && /[ \\t\\u3000]/.test(contents.charAt(p1e - 1))) p1e--;\n'
    '                var p2s = ms + br;                                       // 2\\u884C\\u76EE\\u306E\\u59CB\\u307E\\u308A\\uFF08\\u5B57\\u4E0B\\u3052\\u306E\\u3042\\u3068\\uFF09\n'
    '                while (p2s < me && /[ \\t\\u3000\\r\\n\\u0003]/.test(contents.charAt(p2s))) p2s++;\n'
    '\n'
    '                var name = values["\\u6C0F\\u540D"] || "";\n'
    '                var parts = name.match(/^([^ \\t\\u3000]+)[ \\t\\u3000]+(.+)$/);\n'
    '                if (name === "") {\n'
    '                    edits.push({ start: ms, end: me, text: "", field: "\\u6C0F\\u540D" });\n'
    '                } else if (parts) {\n'
    '                    edits.push({ start: ms, end: p1e, text: matchSpacing(contents.substring(ms, p1e), parts[1]), field: "\\u6C0F\\u540D" });\n'
    '                    edits.push({ start: p2s, end: me, text: matchSpacing(contents.substring(p2s, me), parts[2]), field: "\\u6C0F\\u540D" });\n'
    '                } else {\n'
    '                    // \\u59D3\\u3068\\u540D\\u306E\\u9593\\u306B\\u7A7A\\u767D\\u304C\\u306A\\u304F\\u5206\\u3051\\u3089\\u308C\\u306A\\u3044 \\u2192 1\\u884C\\u76EE\\u306B\\u307E\\u3068\\u3081\\u3066\\u30012\\u884C\\u76EE\\u306F\\u6D88\\u3059\n'
    '                    edits.push({ start: ms, end: p1e, text: matchSpacing(contents.substring(ms, p1e), name), field: "\\u6C0F\\u540D" });\n'
    '                    edits.push({ start: p1e, end: me, text: "", field: "\\u6C0F\\u540D" });\n'
    '                    notes.push("\\u6C0F\\u540D\\u3092\\u59D3\\u3068\\u540D\\u306B\\u5206\\u3051\\u3089\\u308C\\u306A\\u304B\\u3063\\u305F\\u306E\\u30671\\u884C\\u3067\\u5165\\u308C\\u307E\\u3057\\u305F: " + name);\n'
    '                }\n'
    '                if (!inArray(used, "\\u6C0F\\u540D")) used.push("\\u6C0F\\u540D");\n'
    '                masked = masked.substring(0, ms) +\n'
    '                         masked.substring(ms, me).replace(/[^\\r\\n\\u0003]/g, "\\u0001") + masked.substring(me);\n'
    '            }\n'
    '        }\n'
    '        return masked;\n'
    '    }\n'
    '\n'
    '    // \\u30B3\\u30ED\\u30F3\\u306E\\u306A\\u3044\\u898B\\u51FA\\u3057\\u306E\\u3068\\u304D\\u306F\\u3001\\u5F8C\\u308D\\u304C\\u672C\\u5F53\\u306B\\u96FB\\u8A71\\u756A\\u53F7\\u306A\\u3069\\u304B\\u3092\\u78BA\\u304B\\u3081\\u308B\\uFF08\\u300CWeb \\u30C7\\u30B6\\u30A4\\u30F3\\u300D\\u306A\\u3069\\u3092\\u907F\\u3051\\u308B\\uFF09\n'
    '    function looksLikeValue(field, rest) {\n'
    '        if (field === "\\u30E1\\u30FC\\u30EB") return /@/.test(rest);\n'
    '        if (field === "URL") return /^(https?|www)/i.test(rest);\n'
    '        return /^[0-9\\uFF10-\\uFF19\\u25CB\\u3007+(\\uFF08]/.test(rest);\n'
    '    }\n'
    '\n'
    '    // ===== \\u6F22\\u6570\\u5B57 =========================================================\n'
    '    //  \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u4EEE\\u306E\\u6587\\u5B57\\u304C\\u6F22\\u6570\\u5B57\\uFF08\\u3007\\u3007\\u3007\\u30FC\\u3007\\u3007\\u3007\\u3007 \\u306A\\u3069\\uFF09\\u306A\\u3089\\u3001\\u304A\\u5BA2\\u3055\\u3093\\u306E\\u6570\\u5B57\\u3082\\u6F22\\u6570\\u5B57\\u306B\\u3059\\u308B\\u3002\n'
    '    //  \\u30EB\\u30FC\\u30EB\\uFF08\\u4EEE\\uFF09\\uFF1A\\u6570\\u5B57\\u30921\\u6587\\u5B57\\u305A\\u3064 \\u3007\\u4E00\\u4E8C\\u4E09\\u56DB\\u4E94\\u516D\\u4E03\\u516B\\u4E5D \\u306B\\u3001\\u30CF\\u30A4\\u30D5\\u30F3\\u3092\\u300C\\u30FC\\u300D\\u306B\\u3059\\u308B\\u3002\n'
    '    //  \\u203B https://artcode.jp/number_converter.html \\u306E\\u30EB\\u30FC\\u30EB\\u306B\\u5408\\u308F\\u305B\\u3066\\u3001\\u3053\\u3053\\u3092\\u76F4\\u3059\n'
    '    var KANJI_DIGITS = "\\u3007\\u4E00\\u4E8C\\u4E09\\u56DB\\u4E94\\u516D\\u4E03\\u516B\\u4E5D";\n'
    '    var KANJI_FIELDS = ["TEL", "FAX", "\\u643A\\u5E2F", "\\u90F5\\u4FBF\\u756A\\u53F7", "\\u4F4F\\u62401", "\\u4F4F\\u62402"];\n'
    '\n'
    '    function toKanjiNumber(s) {\n'
    '        return String(s).replace(/[0-9\\uFF10-\\uFF19]/g, function (d) {\n'
    '            var n = d.charCodeAt(0);\n'
    '            return KANJI_DIGITS.charAt(n >= 0xFF10 ? n - 0xFF10 : n - 48);\n'
    '        }).replace(/[-\\u2010\\uFF0D\\u2212\\u2013\\u2014]/g, "\\u30FC");\n'
    '    }\n'
    '\n'
    '    // \\u7F6E\\u304D\\u63DB\\u3048\\u308B\\u5143\\u306E\\u6587\\u5B57\\u306B\\u6F22\\u6570\\u5B57\\u306E\\u300C\\u3007\\u300D\\u304C\\u5165\\u3063\\u3066\\u3044\\u308C\\u3070\\u3001\\u5024\\u3092\\u6F22\\u6570\\u5B57\\u306B\\u3059\\u308B\n'
    '    function kanjiIfNeeded(original, value, field) {\n'
    '        if (value === "" || !inArray(KANJI_FIELDS, field) || !/\\u3007/.test(original)) return value;\n'
    '        return toKanjiNumber(value);\n'
    '    }\n'
    '\n'
    '    function planLine(line, values, used) {\n'
    '        var edits = [];\n'
    '        var taken = [];  // \\u3059\\u3067\\u306B\\u7F6E\\u304D\\u63DB\\u3048\\u5BFE\\u8C61\\u306B\\u306A\\u3063\\u305F\\u7BC4\\u56F2\\uFF08\\u4E8C\\u91CD\\u306B\\u7F6E\\u304D\\u63DB\\u3048\\u306A\\u3044\\u305F\\u3081\\uFF09\n'
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
    '        // --- (a) \\u300CTel : 000-...\\u300D\\u306E\\u3088\\u3046\\u306A\\u898B\\u51FA\\u3057\\u4ED8\\u304D\\u306E\\u5024 ---\n'
    '        var found = [];\n'
    '        for (var L = 0; L < LABELS.length; L++) {\n'
    '            for (var w = 0; w < LABELS[L].words.length; w++) {\n'
    '                // \\u300CTel :\\u300D\\u306E\\u3088\\u3046\\u306B\\u30B3\\u30ED\\u30F3\\u304C\\u3042\\u308B\\u304B\\u3001\\u300C\\u96FB\\u8A71 \\u3007\\u3007\\u3007\\u300D\\u306E\\u3088\\u3046\\u306B\\u7A7A\\u767D\\u306E\\u3042\\u3068\\u306B\\u5024\\u304C\\u7D9A\\u304F\n'
    '                var re = new RegExp("(^|" + WS + ")(" + looseSource(LABELS[L].words[w]) + ")(" + WS + "*[:\\uFF1A]" + WS + "*|" + WS + "+)", "g");\n'
    '                var m;\n'
    '                while ((m = re.exec(line)) !== null) {\n'
    '                    if (!/[:\\uFF1A]/.test(m[3]) && !looksLikeValue(LABELS[L].field, line.substring(m.index + m[0].length))) continue;\n'
    '                    var labelStart = m.index + m[1].length;\n'
    '                    var dup = false;\n'
    '                    for (var d = 0; d < found.length; d++) if (found[d].labelStart === labelStart) dup = true;\n'
    '                    if (!dup) found.push({ field: LABELS[L].field, labelStart: labelStart, valueStart: m.index + m[0].length,\n'
    '                                           labelEnd: labelStart + m[2].length, colon: /[:\\uFF1A]/.test(m[3]) });\n'
    '                }\n'
    '            }\n'
    '        }\n'
    '        found.sort(function (a, b) { return a.labelStart - b.labelStart; });\n'
    '        for (var i = 0; i < found.length; i++) {\n'
    '            var vEnd = (i + 1 < found.length) ? found[i + 1].labelStart : line.length;\n'
    '            while (vEnd > found[i].valueStart && /[ \\t\\u3000]/.test(line.charAt(vEnd - 1))) vEnd--;\n'
    '            if (vEnd <= found[i].valueStart) continue;  // \\u5024\\u304C\\u306A\\u3044\\u898B\\u51FA\\u3057\\u306F\\u89E6\\u3089\\u306A\\u3044\n'
    '            var v = val(found[i].field);\n'
    '            if (v !== "") {\n'
    '                var newValue = kanjiIfNeeded(line.substring(found[i].valueStart, vEnd), v, found[i].field);\n'
    '                if (found[i].colon && found[i].field !== "URL") {\n'
    '                    // \\u300CTel : \\u300D\\u2192\\u300CTel\\uFF1A\\u300D\\uFF08\\u30B3\\u30ED\\u30F3\\u306E\\u524D\\u5F8C\\u306E\\u7A7A\\u767D\\u3092\\u306A\\u304F\\u3057\\u3001\\u5168\\u89D2\\u306E\\u30B3\\u30ED\\u30F3\\u306B\\u3059\\u308B\\u3002URL \\u306F\\u305D\\u306E\\u307E\\u307E\\uFF09\n'
    '                    add(found[i].labelEnd, vEnd, COLON + newValue, found[i].field);\n'
    '                    // \\u898B\\u51FA\\u3057\\u306E\\u6700\\u521D\\u306E\\u6587\\u5B57\\u306E\\u4F4D\\u7F6E\\uFF08Illustrator \\u3067\\u6587\\u5B57\\u306E\\u9593\\u9694\\u3092\\u305D\\u308D\\u3048\\u76F4\\u3059\\u3068\\u304D\\u306E\\u76EE\\u5370\\uFF09\n'
    '                    edits[edits.length - 1].spacingFrom = found[i].labelStart;\n'
    '                } else {\n'
    '                    add(found[i].valueStart, vEnd, newValue, found[i].field);\n'
    '                }\n'
    '            } else {\n'
    '                // \\u5024\\u304C\\u7A7A \\u2192 \\u898B\\u51FA\\u3057\\u3054\\u3068\\u6D88\\u3059\\uFF08\\u524D\\u306E\\u7A7A\\u767D\\u3082\\u6D88\\u3059\\uFF09\n'
    '                var s = found[i].labelStart;\n'
    '                while (s > 0 && /[ \\t\\u3000]/.test(line.charAt(s - 1))) s--;\n'
    '                var delEnd = vEnd;\n'
    '                // \\u884C\\u306E\\u982D\\u306E\\u9805\\u76EE\\uFF08\\u300CMobile:000\\u3000E-mail:\\u2026\\u300D\\u306E Mobile\\uFF09\\u3092\\u6D88\\u3059\\u3068\\u304D\\u306F\\u3001\n'
    '                // \\u5F8C\\u308D\\u306E\\u533A\\u5207\\u308A\\u306E\\u7A7A\\u767D\\uFF08\\u5168\\u89D2\\u30B9\\u30DA\\u30FC\\u30B9\\u306A\\u3069\\uFF09\\u3082\\u6D88\\u3059\\u3002\\u6B8B\\u3059\\u3068\\u6B21\\u306E\\u9805\\u76EE\\u306E\\u524D\\u306B\\u3059\\u304D\\u9593\\u304C\\u3067\\u304D\\u308B\n'
    '                if (s === 0 && i + 1 < found.length) delEnd = found[i + 1].labelStart;\n'
    '                add(s, delEnd, "", found[i].field);\n'
    '            }\n'
    '        }\n'
    '\n'
    '        // --- (a2) \\u898B\\u51FA\\u3057\\u3060\\u3051\\u306E\\u884C\\uFF08\\u300CE-mail\\u300D\\u306E\\u5024\\u304C\\u5225\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306B\\u306A\\u3063\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3\\uFF09---\n'
    '        //     \\u5024\\u304C\\u7A7A\\u306A\\u3089\\u898B\\u51FA\\u3057\\u3082\\u6D88\\u3059\\u3002\\u5024\\u304C\\u3042\\u308C\\u3070\\u898B\\u51FA\\u3057\\u306F\\u305D\\u306E\\u307E\\u307E\n'
    '        if (found.length === 0) {\n'
    '            for (var L2 = 0; L2 < LABELS.length; L2++) {\n'
    '                for (var w2 = 0; w2 < LABELS[L2].words.length; w2++) {\n'
    '                    var only = new RegExp("^" + WS + "*" + looseSource(LABELS[L2].words[w2]) + WS + "*[:\\uFF1A]?" + WS + "*$");\n'
    '                    if (only.test(line) && val(LABELS[L2].field) === "" && isFree(0, line.length)) {\n'
    '                        add(0, line.length, "", LABELS[L2].field);\n'
    '                    }\n'
    '                }\n'
    '            }\n'
    '            if (/^[ \\t\\u3000]*\\u3012[ \\t\\u3000]*$/.test(line) && val("\\u90F5\\u4FBF\\u756A\\u53F7") === "" && isFree(0, line.length)) {\n'
    '                add(0, line.length, "", "\\u90F5\\u4FBF\\u756A\\u53F7");\n'
    '            }\n'
    '        }\n'
    '\n'
    '        // --- (b) \\u898B\\u51FA\\u3057\\u306E\\u306A\\u3044 URL\\u30FB\\u30E1\\u30FC\\u30EB\\u30FB\\u90F5\\u4FBF\\u756A\\u53F7 ---\n'
    '        var patterns = [\n'
    '            { field: "URL", re: /https?:\\/\\/[^ \\t\\u3000]+/g },\n'
    '            { field: "\\u30E1\\u30FC\\u30EB", re: /[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/g }\n'
    '        ];\n'
    '        for (var p = 0; p < patterns.length; p++) {\n'
    '            var pm;\n'
    '            patterns[p].re.lastIndex = 0;\n'
    '            while ((pm = patterns[p].re.exec(line)) !== null) {\n'
    '                var ps = pm.index, pe = pm.index + pm[0].length;\n'
    '                if (!isFree(ps, pe)) continue;\n'
    '                var pv = val(patterns[p].field);\n'
    '                if (pv === "") {\n'
    '                    // \\u300C  : ooooo@...\\u300D\\u306E\\u3088\\u3046\\u306B\\u524D\\u306B\\u300C:\\u300D\\u3060\\u3051\\u6B8B\\u308B\\u5834\\u5408\\u3082\\u4E00\\u7DD2\\u306B\\u6D88\\u3059\n'
    '                    while (ps > 0 && /[ \\t\\u3000:\\uFF1A]/.test(line.charAt(ps - 1))) ps--;\n'
    '                }\n'
    '                add(ps, pe, pv, patterns[p].field);\n'
    '            }\n'
    '        }\n'
    '        var zipRe = new RegExp("\\u3012" + WS + "*([0-9\\uFF10-\\uFF19\\u25CB\\u3007]" + WS + "*){3}[-\\u2010\\uFF0D\\u30FC]" + WS + "*([0-9\\uFF10-\\uFF19\\u25CB\\u3007]" + WS + "*){3}[0-9\\uFF10-\\uFF19\\u25CB\\u3007]", "g");\n'
    '        var zm;\n'
    '        while ((zm = zipRe.exec(line)) !== null) {\n'
    '            var zs = zm.index, ze = zm.index + zm[0].length;\n'
    '            if (!isFree(zs, ze)) continue;\n'
    '            var zv = val("\\u90F5\\u4FBF\\u756A\\u53F7");\n'
    '            if (zv === "") add(zs, ze, "", "\\u90F5\\u4FBF\\u756A\\u53F7");\n'
    '            else add(zs + 1, ze, kanjiIfNeeded(line.substring(zs, ze), zv.replace(/^\\u3012/, ""), "\\u90F5\\u4FBF\\u756A\\u53F7"), "\\u90F5\\u4FBF\\u756A\\u53F7");   // \\u3012 \\u306F\\u6B8B\\u3059\n'
    '        }\n'
    '\n'
    '        // --- (c) \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u4EEE\\u306E\\u6587\\u5B57 ---\n'
    '        for (var k = 0; k < PLACEHOLDERS.length; k++) {\n'
    '            var ph = PLACEHOLDERS[k];\n'
    '            var keepLogo = ph.logo && values.__logo;      // \\u30ED\\u30B4\\u6709\\u308A \\u2192 LOGO\\u30FB\\u4F1A\\u793E\\u540D\\u306E\\u4EEE\\u306E\\u6587\\u5B57\\u306F\\u305D\\u306E\\u307E\\u307E\n'
    '            var texts = ph.texts.slice(0).sort(function (a, b) { return b.length - a.length; });\n'
    '            for (var t = 0; t < texts.length; t++) {\n'
    '                var src = looseSource(texts[t]);\n'
    '                if (ph.wholeLine) src = "^" + WS + "*" + src + WS + "*$";\n'
    '                var pre = new RegExp(src, "g");\n'
    '                var mm;\n'
    '                while ((mm = pre.exec(line)) !== null) {\n'
    '                    if (mm[0].length === 0) { pre.lastIndex++; continue; }\n'
    '                    var ms = mm.index, me = mm.index + mm[0].length;\n'
    '                    if (ph.wholeLine) {   // \\u524D\\u5F8C\\u306E\\u7A7A\\u767D\\u306F\\u6B8B\\u3059\n'
    '                        while (ms < me && /[ \\t\\u3000]/.test(line.charAt(ms))) ms++;\n'
    '                        while (me > ms && /[ \\t\\u3000]/.test(line.charAt(me - 1))) me--;\n'
    '                    }\n'
    '                    if (!isFree(ms, me)) continue;\n'
    '                    if (keepLogo) { add(ms, me, line.substring(ms, me), "(\\u305D\\u306E\\u307E\\u307E)", "(\\u305D\\u306E\\u307E\\u307E)"); continue; }\n'
    '                    var field = (ph.altField && val(ph.altField) !== "") ? ph.altField : ph.field;\n'
    '                    var nv = kanjiIfNeeded(line.substring(ms, me), val(field), field);\n'
    '                    if (nv !== "" && ph.spaced) nv = matchSpacing(line.substring(ms, me), nv);\n'
    '                    // \\u5024\\u304C\\u7A7A\\u306E\\u3068\\u304D\\u306F\\u300C  : ooooo@...\\u300D\\u306E\\u300C:\\u300D\\u3082\\u4E00\\u7DD2\\u306B\\u6D88\\u3059\n'
    '                    if (nv === "") while (ms > 0 && /[ \\t\\u3000:\\uFF1A]/.test(line.charAt(ms - 1))) ms--;\n'
    '                    add(ms, me, nv, field, ph.usedAs);\n'
    '                }\n'
    '            }\n'
    '        }\n'
    '        return edits;\n'
    '    }\n'
    '\n'
    '    // \\u4EEE\\u306E\\u6587\\u5B57\\u304C\\u300C\\u9234\\u3000\\u6728\\u3000\\u592A\\u3000\\u90CE\\u300D\\u306E\\u3088\\u3046\\u306B1\\u6587\\u5B57\\u305A\\u3064\\u7A7A\\u3044\\u3066\\u3044\\u305F\\u3089\\u3001\n'
    '    // \\u304A\\u5BA2\\u3055\\u3093\\u306E\\u540D\\u524D\\u300C\\u5C71\\u7530 \\u82B1\\u5B50\\u300D\\u3082\\u300C\\u5C71\\u3000\\u7530\\u3000\\u82B1\\u3000\\u5B50\\u300D\\u306B\\u305D\\u308D\\u3048\\u308B\n'
    '    function matchSpacing(placeholderText, value) {\n'
    '        var m = placeholderText.match(/^[^ \\t\\u3000]([ \\t\\u3000]+)[^ \\t\\u3000]/);\n'
    '        if (!m) return value;\n'
    '        var chars = value.replace(/[ \\t\\u3000]+/g, "");\n'
    '        var out = [];\n'
    '        for (var i = 0; i < chars.length; i++) out.push(chars.charAt(i));\n'
    '        return out.join(m[1]);\n'
    '    }\n'
    '\n'
    '    // edits \\u3092\\u6587\\u5B57\\u5217\\u306B\\u5F53\\u3066\\u306F\\u3081\\u305F\\u7D50\\u679C\\u3092\\u8FD4\\u3059\\uFF08\\u5F8C\\u308D\\u304B\\u3089\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\uFF09\n'
    '    function applyEditsToString(s, edits) {\n'
    '        var sorted = edits.slice(0).sort(function (a, b) { return b.start - a.start; });\n'
    '        for (var i = 0; i < sorted.length; i++) {\n'
    '            s = s.substring(0, sorted[i].start) + sorted[i].text + s.substring(sorted[i].end);\n'
    '        }\n'
    '        return s;\n'
    '    }\n'
    '\n'
    '    // ===== \\u30C1\\u30A7\\u30C3\\u30AF =======================================================\n'
    '\n'
    '    // \\u5024\\u304C\\u5165\\u3063\\u3066\\u3044\\u308B\\u306E\\u306B\\u3001\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306B\\u5DEE\\u3057\\u8FBC\\u307F\\u5148\\u304C\\u306A\\u304B\\u3063\\u305F\\u9805\\u76EE\n'
    '    function unusedFields(rec, used) {\n'
    '        var out = [];\n'
    '        for (var k in rec) {\n'
    '            if (!rec.hasOwnProperty(k) || inArray(INFO_FIELDS, k)) continue;\n'
    '            if (k === "\\u4F1A\\u793E\\u540D" && hasLogoData(rec)) continue;\n'
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
    '    // ===== \\u5099\\u8003 =========================================================\n'
    '    //  \\u5099\\u8003\\u6B04\\u306B\\u304A\\u5E97\\u304C\\u6700\\u521D\\u304B\\u3089\\u5165\\u308C\\u3066\\u3044\\u308B\\u6848\\u5185\\u6587\\u3002\\u3053\\u308C\\u4EE5\\u5916\\u306B\\u4F55\\u3082\\u66F8\\u304B\\u308C\\u3066\\u3044\\u306A\\u3051\\u308C\\u3070\\u6D41\\u3057\\u8FBC\\u307E\\u306A\\u3044\n'
    '    // \\u304A\\u5BA2\\u3055\\u3093\\u304C\\u4F55\\u304B\\u66F8\\u3044\\u3066\\u3044\\u308C\\u3070 true\\uFF08\\u6848\\u5185\\u6587\\u30FB\\u533A\\u5207\\u308A\\u7DDA\\u30FB\\u7A7A\\u767D\\u3060\\u3051\\u306A\\u3089 false\\uFF09\n'
    '    //  \\u6587\\u5B57\\u306E\\u7A2E\\u985E\\u306E\\u3061\\u304C\\u3044\\uFF08\\u5168\\u89D2\\u30FB\\u534A\\u89D2\\u3001\\u3044\\u308D\\u3044\\u308D\\u306A\\u30C0\\u30C3\\u30B7\\u30E5\\u3001\\u898B\\u3048\\u306A\\u3044\\u7A7A\\u767D\\uFF09\\u304C\\u3042\\u3063\\u3066\\u3082\\u6848\\u5185\\u6587\\u3068\\u5206\\u304B\\u308B\\u3088\\u3046\\u306B\\u3001\n'
    '    //  \\u6848\\u5185\\u6587\\u306E\\u6C7A\\u307E\\u3063\\u305F\\u8A00\\u3044\\u56DE\\u3057\\u3092\\u53D6\\u308A\\u9664\\u3044\\u3066\\u304B\\u3089\\u3001\\u4F55\\u304B\\u6B8B\\u308B\\u304B\\u3067\\u5224\\u65AD\\u3059\\u308B\n'
    '    function remarkHasContent(text) {\n'
    '        var t = String(text || "");\n'
    '        t = t.replace(/[ \\t\\u3000\\u00A0\\u200B-\\u200D\\uFEFF\\r\\n]/g, "");               // \\u7A7A\\u767D\\u30FB\\u6539\\u884C\\u30FB\\u898B\\u3048\\u306A\\u3044\\u6587\\u5B57\n'
    '        t = t.replace(/[\\u3010\\[\\uFF3B(\\uFF08]?[ ]*\\u4E0D\\u660E\\u70B9\\u306A\\u3069\\u78BA\\u8A8D\\u6642\\u306E\\u3054\\u9023\\u7D61\\u5148[^\\u3011\\]\\uFF3D)\\uFF09]*[\\u3011\\]\\uFF3D)\\uFF09]?/g, "");\n'
    '        t = t.replace(/[\\u2605\\u2606*\\uFF0A]?\\u5546\\u54C1\\u30DA\\u30FC\\u30B8\\u3067\\u5165\\u529B\\u3067\\u304D\\u306A\\u304B\\u3063\\u305F\\u9805\\u76EE\\u3084\\u3054\\u8981\\u671B\\u7B49\\u3054\\u3056\\u3044\\u307E\\u3057\\u305F\\u3089[\\u3001,\\uFF0C]?\\u3053\\u3061\\u3089\\u306B\\u3054\\u5165\\u529B(\\u4E0B|\\u304F\\u3060)\\u3055\\u3044[\\u3002.\\uFF0E]?/g, "");\n'
    '        t = t.replace(/[-\\u2010\\u2011\\u2012\\u2013\\u2014\\u2015\\u2212\\uFF0D\\u30FC\\u2500\\u2501\\uFF70_\\uFF3F~\\u301C\\uFF5E=\\uFF1D\\u30FB\\uFF65.\\u3002]/g, "");                             // \\u533A\\u5207\\u308A\\u7DDA\n'
    '        return t !== "";\n'
    '    }\n'
    '\n'
    '    // ===== \\u6CE8\\u6587\\u901A\\u77E5\\u30A2\\u30D7\\u30EA\\u304B\\u3089\\u306E\\u6307\\u793A\\u30D5\\u30A1\\u30A4\\u30EB ================================\n'
    '    //  \\u6587\\u5B57\\u30B3\\u30FC\\u30C9\\u306E\\u9055\\u3044\\u3067\\u5316\\u3051\\u306A\\u3044\\u3088\\u3046\\u3001\\u82F1\\u6570\\u5B57\\u3060\\u3051\\u3067\\u66F8\\u304B\\u308C\\u3066\\u3044\\u308B\\u3002\n'
    '    //    1\\u884C\\u76EE: MEISHIJOB1\n'
    '    //    \\u300C\\u9805\\u76EE\\u540D<\\u30BF\\u30D6>\\u5024\\u300D\\u30921\\u884C\\u305A\\u3064\\uFF08\\u3069\\u3061\\u3089\\u3082 %E5%90%8D \\u306E\\u3088\\u3046\\u306A UTF-8 \\u306E\\u30D1\\u30FC\\u30BB\\u30F3\\u30C8\\u8868\\u8A18\\uFF09\n'
    '    //    \\u7A7A\\u306E\\u884C\\u3067\\u6B21\\u306E\\u6CE8\\u6587\\u306B\\u533A\\u5207\\u308B\n'
    '    function parseJob(text) {\n'
    '        var lines = String(text).replace(/^\\uFEFF/, "").split(/\\r\\n|\\r|\\n/);\n'
    '        if (trim(lines[0]) !== "MEISHIJOB1") return null;\n'
    '        var records = [], rec = null;\n'
    '        for (var i = 1; i < lines.length; i++) {\n'
    '            var line = lines[i];\n'
    '            if (trim(line) === "") { rec = null; continue; }\n'
    '            var tab = line.indexOf("\\t");\n'
    '            if (tab < 0) continue;\n'
    '            if (!rec) { rec = {}; records.push(rec); }\n'
    '            rec[decodeURIComponent(line.substring(0, tab))] = decodeURIComponent(line.substring(tab + 1));\n'
    '        }\n'
    '        return records;\n'
    '    }\n'
    '\n'
    '    // ===== \\u6587\\u5B57\\u30B3\\u30FC\\u30C9\\u30FB\\u30C7\\u30B6\\u30A4\\u30F3\\u756A\\u53F7 ========================================\n'
    '\n'
    '    // \\u30D0\\u30A4\\u30C8\\u5217\\uFF081\\u6587\\u5B57=1\\u30D0\\u30A4\\u30C8\\u306E\\u6587\\u5B57\\u5217\\uFF09\\u304C UTF-8 \\u304B Shift_JIS \\u304B\\u3092\\u5224\\u5B9A\\u3059\\u308B\\u3002\n'
    '    // Excel \\u3067\\u4FDD\\u5B58\\u3057\\u305F\\u65E5\\u672C\\u8A9ECSV\\u306F Shift_JIS\\u3001\\u300CCSV UTF-8\\u300D\\u3067\\u4FDD\\u5B58\\u3059\\u308B\\u3068 UTF-8 \\u306B\\u306A\\u308A\\u307E\\u3059\\u3002\n'
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
    '    // \\u30C7\\u30B6\\u30A4\\u30F3\\u756A\\u53F7\\u3084\\u30D5\\u30A1\\u30A4\\u30EB\\u540D\\u3092\\u6BD4\\u3079\\u3084\\u3059\\u3044\\u5F62\\u306B\\u3059\\u308B\\uFF08\\u5168\\u89D2\\u82F1\\u6570\\u2192\\u534A\\u89D2\\u3001\\u5C0F\\u6587\\u5B57\\u3001\\u7A7A\\u767D\\u306A\\u3057\\u3001.ai \\u306A\\u3057\\uFF09\n'
    '    function normalizeKey(s) {\n'
    '        s = String(s || "").replace(/[\\uFF01-\\uFF5E]/g, function (c) {\n'
    '            return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);\n'
    '        });\n'
    '        return s.replace(/[ \\t\\u3000]+/g, "").replace(/\\.ai$/i, "").toLowerCase();\n'
    '    }\n'
    '\n'
    '    // ===== \\u30D5\\u30A1\\u30A4\\u30EB\\u540D =====================================================\n'
    '\n'
    '    // \\u300C\\u6CE8\\u6587\\u756A\\u53F7_\\u540D\\u524D.ai\\u300D \\u30D5\\u30A1\\u30A4\\u30EB\\u540D\\u306B\\u4F7F\\u3048\\u306A\\u3044\\u6587\\u5B57\\u3084\\u7A7A\\u767D\\u306F\\u53D6\\u308A\\u9664\\u304F\n'
    '    function makeFileName(rec) {\n'
    '        function clean(s) {\n'
    '            return String(s || "").replace(/[\\\\\\/:*?"<>|\\r\\n\\t]/g, "").replace(/[ \\u3000]+/g, "");\n'
    '        }\n'
    '        var order = clean(rec["\\u6CE8\\u6587\\u756A\\u53F7"]) || "\\u6CE8\\u6587\\u756A\\u53F7\\u306A\\u3057";\n'
    '        var name = clean(rec["\\u6C0F\\u540D"]) || clean(rec["\\u6C0F\\u540D\\u82F1\\u5B57"]) || "\\u540D\\u524D\\u306A\\u3057";\n'
    '        return order + "_" + name + ".ai";\n'
    '    }\n'
    '\n'
    '    return {\n'
    '        FIELD_ALIASES: FIELD_ALIASES,\n'
    '        PLACEHOLDERS: PLACEHOLDERS,\n'
    '        LABELS: LABELS,\n'
    '        trim: trim,\n'
    '        parseCSV: parseCSV,\n'
    '        parseJob: parseJob,\n'
    '        remarkHasContent: remarkHasContent,\n'
    '        toKanjiNumber: toKanjiNumber,\n'
    '        rowsToRecords: rowsToRecords,\n'
    '        INFO_FIELDS: INFO_FIELDS,\n'
    '        prepareValues: prepareValues,\n'
    '        hasLogoData: hasLogoData,\n'
    '        isLogoText: isLogoText,\n'
    '        labelOnlyField: labelOnlyField,\n'
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
    '// Node.js \\u306E\\u30C6\\u30B9\\u30C8\\u304B\\u3089\\u8AAD\\u307F\\u8FBC\\u3080\\u3068\\u304D\\u7528\n'
    'if (typeof module !== "undefined" && module.exports) module.exports = MeishiCore;\n'
    '\n'
    '// =====================================================================\n'
    '//  \\u540D\\u523A\\u81EA\\u52D5\\u4F5C\\u6210 \\u2014 Illustrator \\u306E\\u66F8\\u985E\\u3092\\u66F8\\u304D\\u63DB\\u3048\\u308B\\u90E8\\u5206\n'
    '//  \\uFF08meishi_job.jsx \\u3068 meishi_auto.jsx \\u304B\\u3089 #include \\u3057\\u3066\\u4F7F\\u3044\\u307E\\u3059\\uFF09\n'
    '//  \\u5148\\u306B meishi_core.jsx \\u3092 #include \\u3057\\u3066\\u304A\\u304F\\u5FC5\\u8981\\u304C\\u3042\\u308A\\u307E\\u3059\\u3002\n'
    '// =====================================================================\n'
    '\n'
    'var MeishiAI = (function () {\n'
    '    var C = MeishiCore;\n'
    '\n'
    '    // \\u6587\\u5B57\\u30B3\\u30FC\\u30C9\\u3092\\u5224\\u5B9A\\u3057\\u3066\\u30C6\\u30AD\\u30B9\\u30C8\\u30D5\\u30A1\\u30A4\\u30EB\\u3092\\u8AAD\\u3080\\uFF08UTF-8 / Shift_JIS\\uFF09\n'
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
    '        return s.length > max ? s.substring(0, max) + "\\u2026" : s;\n'
    '    }\n'
    '\n'
    '    // \\u30C6\\u30AD\\u30B9\\u30C8\\u30D5\\u30EC\\u30FC\\u30E0\\u306E start\\u301Cend \\u6587\\u5B57\\u76EE\\u3092 text \\u306B\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\uFF08\\u6700\\u521D\\u306E\\u6587\\u5B57\\u306E\\u66F8\\u5F0F\\u3092\\u5F15\\u304D\\u7D99\\u3050\\uFF09\n'
    '    function replaceRange(tf, start, end, text) {\n'
    '        var len = end - start;\n'
    '        if (len <= 0) return;\n'
    '        var r = tf.characters[start];\n'
    '        try {\n'
    '            if (len > 1) r.length = len;\n'
    '        } catch (e) {\n'
    '            // length \\u304C\\u5909\\u3048\\u3089\\u308C\\u306A\\u3044\\u5834\\u5408\\u306F1\\u6587\\u5B57\\u305A\\u3064\\u6D88\\u3059\n'
    '            for (var i = end - 1; i > start; i--) tf.characters[i].remove();\n'
    '            r = tf.characters[start];\n'
    '        }\n'
    '        if (text === "") r.remove();\n'
    '        else r.contents = text;\n'
    '    }\n'
    '\n'
    '    // \\u300CE-mail  : ooooo\\u300D\\u306E\\u7A7A\\u767D\\u306B\\u30DE\\u30A4\\u30CA\\u30B9\\u306E\\u6587\\u5B57\\u9593\\u9694\\uFF08\\u30AB\\u30FC\\u30CB\\u30F3\\u30B0\\u30FB\\u30C8\\u30E9\\u30C3\\u30AD\\u30F3\\u30B0\\uFF09\\u3092\\u4ED8\\u3051\\u3066\n'
    '    // \\u30B3\\u30ED\\u30F3\\u3092\\u898B\\u51FA\\u3057\\u306B\\u5BC4\\u305B\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3\\u304C\\u3042\\u308B\\u3002\\u7A7A\\u767D\\u3092\\u300C\\uFF1A\\u5024\\u300D\\u306B\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\u3068\\u3001\\u305D\\u306E\\u8A70\\u3081\\u304C\\u6B8B\\u3063\\u3066\n'
    '    // \\u300C\\uFF1A\\u300D\\u304C\\u898B\\u51FA\\u3057\\u306B\\u91CD\\u306A\\u308B\\u306E\\u3067\\u3001\\u7F6E\\u304D\\u63DB\\u3048\\u305F\\u6587\\u5B57\\u306E\\u9593\\u9694\\u3092\\u898B\\u51FA\\u3057\\u306E\\u6700\\u521D\\u306E\\u6587\\u5B57\\u3068\\u540C\\u3058\\u306B\\u623B\\u3059\\u3002\n'
    '    function resetSpacing(tf, baseIndex, start, len) {\n'
    '        var base = 0;\n'
    '        try { base = tf.characters[baseIndex].characterAttributes.tracking; } catch (e0) { base = 0; }\n'
    '        // \\u898B\\u51FA\\u3057\\u306E\\u6700\\u521D\\u306E\\u6587\\u5B57\\u306E\\u524D\\u306B\\u4F59\\u8A08\\u306A\\u3059\\u304D\\u9593\\u3092\\u4F5C\\u3089\\u306A\\u3044\\uFF08\\u305D\\u306E\\u6587\\u5B57\\u3068\\u3001\\u3072\\u3068\\u3064\\u524D\\u306E\\u6539\\u884C\\u6587\\u5B57\\u306E\\u9593\\u9694\\u3092 0 \\u306B\\uFF09\n'
    '        try { tf.characters[baseIndex].kerning = 0; } catch (e3) { /* \\u305D\\u306E\\u307E\\u307E */ }\n'
    '        if (baseIndex > 0) {\n'
    '            try {\n'
    '                var prev = tf.characters[baseIndex - 1];\n'
    '                if (/[\\r\\n\\u0003]/.test(prev.contents)) {\n'
    '                    prev.kerning = 0;\n'
    '                    prev.characterAttributes.tracking = base;\n'
    '                }\n'
    '            } catch (e4) { /* \\u305D\\u306E\\u307E\\u307E */ }\n'
    '        }\n'
    '        for (var i = start - 1; i < start + len; i++) {\n'
    '            if (i < 0) continue;\n'
    '            try {\n'
    '                var ch = tf.characters[i];\n'
    '                ch.characterAttributes.tracking = base;\n'
    '                try { ch.kerning = 0; } catch (e1) { /* \\u30AB\\u30FC\\u30CB\\u30F3\\u30B0\\u3092\\u5909\\u3048\\u3089\\u308C\\u306A\\u3044\\u3068\\u304D\\u306F\\u305D\\u306E\\u307E\\u307E */ }\n'
    '            } catch (e2) { /* \\u305D\\u306E\\u6587\\u5B57\\u306F\\u98DB\\u3070\\u3059 */ }\n'
    '        }\n'
    '    }\n'
    '\n'
    '    // \\u78BA\\u8A8D\\u7528\\u30ED\\u30B0\\uFF08\\u300CE-mail\\u300D\\u306E\\u884C\\u306A\\u3069\\u306E\\u6587\\u5B57\\u3054\\u3068\\u306E\\u9593\\u9694\\u3092\\u3001\\u76F4\\u3059\\u524D\\u3068\\u5F8C\\u3067\\u8A18\\u9332\\u3059\\u308B\\uFF09\n'
    '    var debugLog = [];\n'
    '\n'
    '    function spacingDump(tf, from, to) {\n'
    '        var out = [];\n'
    '        for (var i = Math.max(0, from); i < to; i++) {\n'
    '            var ch;\n'
    '            try { ch = tf.characters[i]; } catch (e) { break; }\n'
    '            var c = "?", k = "?", t = "?";\n'
    '            try { c = ch.contents === "\\r" ? "\\u23CE" : ch.contents; } catch (e1) { /* \\u8AAD\\u3081\\u306A\\u3051\\u308C\\u3070 ? */ }\n'
    '            try { k = ch.kerning; } catch (e2) { /* \\u8AAD\\u3081\\u306A\\u3051\\u308C\\u3070 ? */ }\n'
    '            try { t = ch.characterAttributes.tracking; } catch (e3) { /* \\u8AAD\\u3081\\u306A\\u3051\\u308C\\u3070 ? */ }\n'
    '            out.push(c + "(k" + k + ",t" + t + ")");\n'
    '        }\n'
    '        return out.join(" ");\n'
    '    }\n'
    '\n'
    '    // \\u305D\\u306E\\u884C\\uFF08\\u6BB5\\u843D\\uFF09\\u306E\\u5B57\\u4E0B\\u3052\\u306E\\u8A2D\\u5B9A\\uFF08\\u30ED\\u30B0\\u7528\\uFF09\n'
    '    function indentDump(tf, index) {\n'
    '        try {\n'
    '            var pa = tf.characters[index].paragraphAttributes;\n'
    '            return "[\\u5B57\\u4E0B\\u3052 \\u5DE6" + pa.leftIndent + " 1\\u884C\\u76EE" + pa.firstLineIndent + " \\u305D\\u308D\\u3048" + pa.justification + "]";\n'
    '        } catch (e) { return ""; }\n'
    '    }\n'
    '\n'
    '    // edits \\u3092\\u5F53\\u3066\\u306F\\u3081\\u305F\\u3042\\u3068\\u306E\\u3001\\u305D\\u308C\\u305E\\u308C\\u306E\\u7F6E\\u304D\\u63DB\\u3048\\u90E8\\u5206\\u306E\\u59CB\\u307E\\u308A\\u306E\\u4F4D\\u7F6E\\u3067 resetSpacing \\u3059\\u308B\n'
    '    function fixSpacing(tf, edits) {\n'
    '        var shift = 0;\n'
    '        for (var e = 0; e < edits.length; e++) {\n'
    '            var ed = edits[e];\n'
    '            if (ed.hasOwnProperty("spacingFrom")) {\n'
    '                var from = ed.spacingFrom + shift, st = ed.start + shift;\n'
    '                var beforeDump = spacingDump(tf, from - 1, st + 3) + "  " + indentDump(tf, from);\n'
    '                resetSpacing(tf, from, st, ed.text.length);\n'
    '                debugLog.push(ed.field + "  \\u76F4\\u3059\\u524D: " + beforeDump + "\\n" + ed.field + "  \\u76F4\\u3057\\u305F\\u5F8C: " + spacingDump(tf, from - 1, st + 3));\n'
    '            }\n'
    '            shift += ed.text.length - (ed.end - ed.start);\n'
    '        }\n'
    '    }\n'
    '\n'
    '    // \\u66F8\\u304D\\u63DB\\u3048\\u306E\\u3058\\u3083\\u307E\\u306B\\u306A\\u308B\\u30ED\\u30C3\\u30AF\\u3092\\u4E00\\u6642\\u7684\\u306B\\u5916\\u3059\n'
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
    '    // ----- LOGO \\u6A2A\\u306E\\u30DE\\u30FC\\u30AF -----\n'
    '\n'
    '    // geometricBounds \\u306F [\\u5DE6, \\u4E0A, \\u53F3, \\u4E0B]\\uFF08\\u4E0A\\u306E\\u65B9\\u304C\\u6570\\u5B57\\u304C\\u5927\\u304D\\u3044\\uFF09\n'
    '    // \\u300CLOGO \\u306E\\u5DE6\\u53F3\\u3059\\u3050\\u6A2A\\u306B\\u3042\\u308A\\u3001LOGO \\u3068\\u540C\\u3058\\u304F\\u3089\\u3044\\u306E\\u5927\\u304D\\u3055\\u3067\\u3001LOGO \\u306B\\u91CD\\u306A\\u3063\\u3066\\u3044\\u306A\\u3044\\u300D\\u3082\\u306E\\u3092\\u30DE\\u30FC\\u30AF\\u3068\\u307F\\u306A\\u3059\n'
    '    // \\uFF08463 \\u500B\\u306E\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u3067\\u78BA\\u8A8D\\u3002\\u80CC\\u666F\\u306E\\u7D75\\u3084\\u5927\\u304D\\u306A\\u98FE\\u308A\\u306F\\u5BFE\\u8C61\\u5916\\u306B\\u306A\\u308B\\uFF09\n'
    '    function isNextToLogo(b, logo) {\n'
    '        var h = logo[1] - logo[3];\n'
    '        var ih = b[1] - b[3], iw = b[2] - b[0];\n'
    '        if (ih <= 0 || iw <= 0 || ih > h * 3 || iw > h * 3) return false;  // LOGO \\u306E3\\u500D\\u3088\\u308A\\u5927\\u304D\\u3044\\u3082\\u306E\\u306F\\u80CC\\u666F\n'
    '        var vOverlap = Math.min(logo[1], b[1]) - Math.max(logo[3], b[3]);\n'
    '        if (vOverlap < ih * 0.5) return false;                             // \\u534A\\u5206\\u4EE5\\u4E0A\\u304C LOGO \\u3068\\u540C\\u3058\\u9AD8\\u3055\\u306B\\u3042\\u308B\n'
    '        var gap;\n'
    '        if (b[2] <= logo[0] + 1) gap = logo[0] - b[2];                     // \\u5DE6\\u5074\n'
    '        else if (b[0] >= logo[2] - 1) gap = b[0] - logo[2];                // \\u53F3\\u5074\n'
    '        else return false;                                                  // LOGO \\u306B\\u91CD\\u306A\\u3063\\u3066\\u3044\\u308B\\uFF08\\u80CC\\u666F\\uFF09\n'
    '        return gap <= h;\n'
    '    }\n'
    '\n'
    '    function overlaps(a, b) {\n'
    '        return Math.min(a[2], b[2]) > Math.max(a[0], b[0]) && Math.min(a[1], b[1]) > Math.max(a[3], b[3]);\n'
    '    }\n'
    '\n'
    '    // \\u753B\\u50CF\\u306E\\u7BC4\\u56F2\\u306E\\u4E00\\u89A7\\u304B\\u3089\\u3001LOGO \\u6A2A\\u306E\\u30DE\\u30FC\\u30AF\\u3060\\u3051\\u3092\\u9078\\u3076\\uFF08\\u756A\\u53F7\\u306E\\u4E00\\u89A7\\u3092\\u8FD4\\u3059\\uFF09\n'
    '    // \\u30FB\\u4ED6\\u306E\\u753B\\u50CF\\u306B\\u91CD\\u306A\\u3063\\u3066\\u3044\\u308B\\u3082\\u306E\\uFF08\\u80CC\\u666F\\u306E\\u7D75\\u306E\\u4E00\\u90E8\\uFF09\\u306F\\u9078\\u3070\\u306A\\u3044\n'
    '    // \\u30FB\\u5019\\u88DC\\u304C2\\u3064\\u4EE5\\u4E0A\\u3042\\u308B\\u3068\\u304D\\u306F\\u3001\\u3069\\u308C\\u304C\\u30DE\\u30FC\\u30AF\\u304B\\u5206\\u304B\\u3089\\u306A\\u3044\\u306E\\u3067\\u4F55\\u3082\\u9078\\u3070\\u306A\\u3044\\uFF08ambiguous \\u306B\\u5370\\u3092\\u4ED8\\u3051\\u308B\\uFF09\n'
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
    '    // LOGO \\u306E\\u6587\\u5B57\\u306E\\u6A2A\\u306B\\u3042\\u308B\\u30ED\\u30B4\\u30DE\\u30FC\\u30AF\\u3092\\u63A2\\u3059\n'
    '    //  \\u2460 LOGO \\u306E\\u6587\\u5B57\\u3068\\u30B0\\u30EB\\u30FC\\u30D7\\u306B\\u306A\\u3063\\u3066\\u3044\\u308B\\u56F3\\u5F62\\u30FB\\u753B\\u50CF\\uFF08LOGO \\u306E\\u3059\\u3050\\u6A2A\\u306B\\u3042\\u308B\\u3082\\u306E\\uFF09\n'
    '    //  \\u2461 LOGO \\u306E\\u3059\\u3050\\u6A2A\\uFF08\\u4E0A\\u4E0B\\uFF09\\u306B\\u3042\\u308B\\u753B\\u50CF\n'
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
    '                // \\u30DE\\u30B9\\u30AF\\u3067\\u5207\\u308A\\u629C\\u304B\\u308C\\u3066\\u3044\\u308B\\u753B\\u50CF\\u306F\\u30DE\\u30B9\\u30AF\\u306E\\u30B0\\u30EB\\u30FC\\u30D7\\u3054\\u3068\\u6D88\\u3059\n'
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
    '        if (C.hasLogoData(rec)) return;    // \\u30ED\\u30B4\\u6709\\u308A \\u2192 \\u30DE\\u30FC\\u30AF\\u306F\\u305D\\u306E\\u307E\\u307E\\uFF08\\u3042\\u3068\\u3067\\u5DEE\\u3057\\u66FF\\u3048\\uFF09\n'
    '        var count = 0;\n'
    '        for (var i = 0; i < doc.textFrames.length; i++) {\n'
    '            var tf = doc.textFrames[i];\n'
    '            if (!C.isLogoText(tf.contents)) continue;\n'
    '            var marks = findLogoMarks(doc, tf);\n'
    '            if (marks.ambiguous) warnings.push("LOGO \\u6A2A\\u306B\\u753B\\u50CF\\u304C\\u8907\\u6570\\u3042\\u308A\\u3001\\u30DE\\u30FC\\u30AF\\u304B\\u5206\\u304B\\u3089\\u306A\\u3044\\u305F\\u3081\\u6D88\\u3057\\u3066\\u3044\\u307E\\u305B\\u3093");\n'
    '            for (var m = 0; m < marks.length; m++) {\n'
    '                try {\n'
    '                    var relock = unlockFor(marks[m]);\n'
    '                    marks[m].remove();\n'
    '                    count++;\n'
    '                    relock();\n'
    '                } catch (e) {\n'
    '                    warnings.push("LOGO \\u6A2A\\u306E\\u30DE\\u30FC\\u30AF\\u3092\\u6D88\\u305B\\u307E\\u305B\\u3093\\u3067\\u3057\\u305F\\uFF08" + e.message + "\\uFF09");\n'
    '                }\n'
    '            }\n'
    '        }\n'
    '        if (count > 0) warnings.push("LOGO \\u6A2A\\u306E\\u30DE\\u30FC\\u30AF\\u3092 " + count + " \\u500B\\u6D88\\u3057\\u307E\\u3057\\u305F\\uFF08\\u4F4D\\u7F6E\\u3092\\u78BA\\u8A8D\\u3057\\u3066\\u304F\\u3060\\u3055\\u3044\\uFF09");\n'
    '    }\n'
    '\n'
    '    // ----- \\u5099\\u8003 -----\n'
    '\n'
    '    var MM = 72 / 25.4;                    // 1mm = \\u7D042.83pt\n'
    '    var REMARK_OFFSET = 50 * MM;           // \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u4E2D\\u5FC3\\u304B\\u3089 5cm \\u4E0B\n'
    '    var FALLBACK_OFFSET = 50 * MM;         // \\u7F6E\\u304F\\u5834\\u6240\\u304C\\u898B\\u3064\\u304B\\u3089\\u306A\\u3044\\u3068\\u304D\\uFF1A\\u4E2D\\u5FC3\\u304B\\u3089 5cm \\u4E0A\n'
    '    var REMARK_SIZE = 7;                   // 7pt\n'
    '    var REMARK_FONTS = ["MS-Gothic", "MSGothic", "MS Gothic", "\\uFF2D\\uFF33\\u30B4\\u30B7\\u30C3\\u30AF", "\\uFF2D\\uFF33 \\u30B4\\u30B7\\u30C3\\u30AF"];\n'
    '\n'
    '    function findFont(names) {\n'
    '        for (var i = 0; i < names.length; i++) {\n'
    '            try { return app.textFonts.getByName(names[i]); } catch (e) { /* \\u6B21\\u306E\\u540D\\u524D\\u3092\\u8A66\\u3059 */ }\n'
    '        }\n'
    '        return null;\n'
    '    }\n'
    '\n'
    '    // \\u30A2\\u30FC\\u30C8\\u30DC\\u30FC\\u30C9\\uFF08\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\uFF09\\u306E\\u4E2D\\u5FC3 [x, y]\n'
    '    function artboardCenter(doc) {\n'
    '        var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;   // [\\u5DE6, \\u4E0A, \\u53F3, \\u4E0B]\n'
    '        return [(ab[0] + ab[2]) / 2, (ab[1] + ab[3]) / 2];\n'
    '    }\n'
    '\n'
    '    // \\u304A\\u5BA2\\u3055\\u3093\\u306E\\u5099\\u8003\\u3092\\u3001\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u4E2D\\u5FC3\\u304B\\u3089 5cm \\u4E0B\\u306B 7pt \\u306E MS\\u30B4\\u30B7\\u30C3\\u30AF\\u3067\\u5165\\u308C\\u308B\\uFF08\\u4E2D\\u592E\\u63C3\\u3048\\uFF09\n'
    '    function addRemarks(doc, text, warnings) {\n'
    '        text = C.trim(text || "");\n'
    '        if (!C.remarkHasContent(text)) return;   // \\u304A\\u5E97\\u306E\\u6848\\u5185\\u6587\\u3060\\u3051\\uFF08\\u304A\\u5BA2\\u3055\\u3093\\u304C\\u4F55\\u3082\\u66F8\\u3044\\u3066\\u3044\\u306A\\u3044\\uFF09\\u306A\\u3089\\u5165\\u308C\\u306A\\u3044\n'
    '        var c = artboardCenter(doc), cx = c[0], cy = c[1];\n'
    '\n'
    '        var layer = doc.layers.add();\n'
    '        layer.name = "\\u5099\\u8003";\n'
    '        var tf = layer.textFrames.add();\n'
    '        tf.contents = text.replace(/\\r\\n|\\n/g, "\\r");\n'
    '        var range = tf.textRange;\n'
    '        range.characterAttributes.size = REMARK_SIZE;\n'
    '        var font = findFont(REMARK_FONTS);\n'
    '        if (font) range.characterAttributes.textFont = font;\n'
    '        else warnings.push("MS\\u30B4\\u30B7\\u30C3\\u30AF\\u304C\\u898B\\u3064\\u304B\\u3089\\u306A\\u3044\\u305F\\u3081\\u3001\\u5099\\u8003\\u306F\\u6A19\\u6E96\\u306E\\u30D5\\u30A9\\u30F3\\u30C8\\u3067\\u5165\\u308C\\u307E\\u3057\\u305F");\n'
    '        range.paragraphAttributes.justification = Justification.CENTER;\n'
    '        // \\u6587\\u5B57\\u306E\\u304B\\u305F\\u307E\\u308A\\u306E\\u300C\\u4E0A\\u306E\\u4E2D\\u592E\\u300D\\u3092\\u3001\\u4E2D\\u5FC3\\u304B\\u3089 8cm \\u4E0B\\u306B\\u305D\\u308D\\u3048\\u308B\n'
    '        tf.position = [cx - tf.width / 2, cy - REMARK_OFFSET];\n'
    '        warnings.push("\\u5099\\u8003\\u3092\\u540D\\u523A\\u306E\\u4E0B\\uFF08\\u4E2D\\u5FC3\\u304B\\u30895cm\\u4E0B\\uFF09\\u306B\\u5165\\u308C\\u307E\\u3057\\u305F");\n'
    '    }\n'
    '\n'
    '    // ----- \\u898B\\u51FA\\u3057\\u3068\\u5024\\u304C\\u5225\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306B\\u306A\\u3063\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3 -----\n'
    '    //  \\u300CE-mail\\u300D\\u3068\\u300C  : ooooo@oooo.com\\u300D\\u3092\\u91CD\\u306D\\u3066\\u7F6E\\u3044\\u3066\\u3044\\u308B\\u30C7\\u30B6\\u30A4\\u30F3\\uFF08372 \\u500B\\uFF09\\u306F\\u3001\n'
    '    //  \\u305D\\u306E\\u307E\\u307E\\u30B3\\u30ED\\u30F3\\u3092\\u8A70\\u3081\\u308B\\u3068\\u300C\\uFF1A\\u300D\\u304C\\u898B\\u51FA\\u3057\\u306B\\u91CD\\u306A\\u308B\\u306E\\u3067\\u3001\\u898B\\u51FA\\u3057\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306B1\\u3064\\u306B\\u307E\\u3068\\u3081\\u308B\\u3002\n'
    '    //  \\uFF08URL \\u306F\\u5BFE\\u8C61\\u5916\\u3002\\u307E\\u3068\\u3081\\u305F\\u3042\\u3068\\u306E\\u300C\\uFF1A\\u300D\\u306F meishi_core.jsx \\u306E\\u6C7A\\u307E\\u308A\\u3067\\u305D\\u308D\\u3046\\uFF09\n'
    '    function mergeSplitLabels(doc) {\n'
    '        var labels = [], values = [], removed = [];\n'
    '        for (var i = 0; i < doc.textFrames.length; i++) {\n'
    '            var tf = doc.textFrames[i], t = tf.contents;\n'
    '            // \\u5024\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\uFF1A\\u300C  : ooooo@\\u2026\\u300D\\u306E\\u3088\\u3046\\u306B 1 \\u884C\\u3067\\u30B3\\u30ED\\u30F3\\u304B\\u3089\\u59CB\\u307E\\u308B\n'
    '            if (!/[\\r\\n\\u0003]/.test(t) && /^[ \\t\\u3000]*[:\\uFF1A]/.test(t)) { values.push(tf); continue; }\n'
    '            // \\u898B\\u51FA\\u3057\\u306E\\u884C\\uFF1A\\u30C6\\u30AD\\u30B9\\u30C8\\u306E\\u4E2D\\u306E\\u300CE-mail\\u300D\\u3060\\u3051\\u306E\\u884C\\uFF08\\u300CMobile \\u2026\\u300D\\u3068\\u540C\\u3058\\u30C6\\u30AD\\u30B9\\u30C8\\u306E2\\u884C\\u76EE\\u306A\\u3069\\u3067\\u3082\\u3088\\u3044\\uFF09\n'
    '            var lines = t.split(/[\\r\\n\\u0003]/), pos = 0;\n'
    '            for (var li = 0; li < lines.length; li++) {\n'
    '                var field = C.labelOnlyField(lines[li]);\n'
    '                if (field && field !== "URL" && C.trim(lines[li]) !== "") {\n'
    '                    labels.push({ frame: tf, index: li, count: lines.length, start: pos, text: lines[li] });\n'
    '                }\n'
    '                pos += lines[li].length + 1;\n'
    '            }\n'
    '        }\n'
    '        for (var l = 0; l < labels.length; l++) {\n'
    '            var L = labels[l], fb = L.frame.geometricBounds;\n'
    '            // \\u305D\\u306E\\u884C\\u306E\\u304A\\u304A\\u3088\\u305D\\u306E\\u9AD8\\u3055\\u306E\\u7BC4\\u56F2\\uFF08\\u8907\\u6570\\u884C\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306F\\u884C\\u306E\\u6570\\u3067\\u7B49\\u5206\\u3057\\u3066\\u8003\\u3048\\u308B\\uFF09\n'
    '            var lineH = (fb[1] - fb[3]) / L.count;\n'
    '            var top = fb[1] - lineH * L.index, bottom = top - lineH;\n'
    '            var best = null, bestGap = 0;\n'
    '            for (var v = 0; v < values.length; v++) {\n'
    '                if (!values[v]) continue;\n'
    '                var vb = values[v].geometricBounds;\n'
    '                var vOverlap = Math.min(top, vb[1]) - Math.max(bottom, vb[3]);\n'
    '                var gap = vb[0] - fb[0];                         // \\u5024\\u306F\\u898B\\u51FA\\u3057\\u306E\\u53F3\\u5074\\uFF08\\u91CD\\u306A\\u3063\\u3066\\u3044\\u3066\\u3082\\u3088\\u3044\\uFF09\n'
    '                if (vOverlap < Math.min(lineH, vb[1] - vb[3]) * 0.5 || gap < 0 || vb[0] > fb[2] + lineH * 3) continue;\n'
    '                if (best === null || gap < bestGap) { best = v; bestGap = gap; }\n'
    '            }\n'
    '            if (best === null) continue;\n'
    '            var valueFrame = values[best];\n'
    '            var relock = unlockFor(L.frame);\n'
    '            var relock2 = unlockFor(valueFrame);\n'
    '            // \\u300CE-mail\\u300D\\u306E\\u884C\\u306E\\u6700\\u5F8C\\u306B\\u300C:\\u5024\\u300D\\u3092\\u3064\\u306A\\u3052\\u308B\\uFF08\\u6700\\u5F8C\\u306E\\u6587\\u5B57\\u306E\\u66F8\\u5F0F\\u3092\\u5F15\\u304D\\u7D99\\u3050\\uFF09\n'
    '            var word = L.text.replace(/[ \\t\\u3000:\\uFF1A]+$/, "");\n'
    '            var wordEnd = L.start + L.text.search(/[ \\t\\u3000:\\uFF1A]*$/);\n'
    '            var lineEnd = L.start + L.text.length;\n'
    '            var addText = ":" + valueFrame.contents.replace(/^[ \\t\\u3000]*[:\\uFF1A]/, "");\n'
    '            var before = L.frame.contents;\n'
    '            var expected = before.substring(0, wordEnd) + addText + before.substring(lineEnd);\n'
    '            try {\n'
    '                replaceRange(L.frame, wordEnd - 1, lineEnd, word.charAt(word.length - 1) + addText);\n'
    '            } catch (e) { /* \\u4E0B\\u3067\\u4E2D\\u8EAB\\u3054\\u3068\\u5165\\u308C\\u76F4\\u3059 */ }\n'
    '            if (L.frame.contents !== expected) L.frame.contents = expected;\n'
    '            removed.push(valueFrame);\n'
    '            valueFrame.remove();\n'
    '            values[best] = null;\n'
    '            relock();\n'
    '            try { relock2(); } catch (e2) { /* \\u6D88\\u3057\\u305F\\u30C6\\u30AD\\u30B9\\u30C8\\u306E\\u30ED\\u30C3\\u30AF\\u306F\\u623B\\u3055\\u306A\\u3044 */ }\n'
    '        }\n'
    '        return removed;\n'
    '    }\n'
    '\n'
    '    // ----- \\u3075\\u308A\\u304C\\u306A\\u30FB\\u90E8\\u7F72\\u540D\\uFF08\\u65B0\\u3057\\u3044\\u30C6\\u30AD\\u30B9\\u30C8\\u3068\\u3057\\u3066\\u8DB3\\u3059\\uFF09 -----\n'
    '\n'
    '    var FURIGANA_SIZE = 5;     // \\u3075\\u308A\\u304C\\u306A\\uFF1A\\u6C0F\\u540D\\u306E\\u4E0A\\u306B 5pt\n'
    '    var DEPARTMENT_SIZE = 8;   // \\u90E8\\u7F72\\u540D\\uFF1A\\u4F1A\\u793E\\u540D\\u3068\\u80A9\\u66F8\\u306E\\u9593\\uFF08\\u80A9\\u66F8\\u306E\\u4E0A\\uFF09\\u306B 8pt\n'
    '    var LABEL_GAP = 1;         // \\u5143\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u3068\\u306E\\u3059\\u304D\\u9593\\uFF08pt\\uFF09\n'
    '\n'
    '    // \\u66F8\\u304D\\u63DB\\u3048\\u308B\\u524D\\u306B\\u3001\\u305D\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306E\\u4F4D\\u7F6E\\u30FB\\u30D5\\u30A9\\u30F3\\u30C8\\u30FB\\u305D\\u308D\\u3048\\u65B9\\u30FB\\u7E26\\u66F8\\u304D\\u304B\\u3092\\u899A\\u3048\\u3066\\u304A\\u304F\n'
    '    function captureInfo(tf, index, frameIndex) {\n'
    '        var info = { frame: tf, frameIndex: frameIndex, removed: false, bounds: tf.geometricBounds,\n'
    '                     font: null, align: "left", vertical: false };\n'
    '        try { info.font = tf.characters[index].characterAttributes.textFont; } catch (e1) { /* \\u30D5\\u30A9\\u30F3\\u30C8\\u306F\\u6A19\\u6E96\\u306E\\u307E\\u307E */ }\n'
    '        try { info.vertical = tf.orientation === TextOrientation.VERTICAL; } catch (e2) { /* \\u6A2A\\u66F8\\u304D */ }\n'
    '        try {\n'
    '            var j = tf.characters[index].paragraphAttributes.justification;\n'
    '            if (j === Justification.CENTER) info.align = "center";\n'
    '            else if (j === Justification.RIGHT) info.align = "right";\n'
    '        } catch (e3) { /* \\u5DE6\\u305D\\u308D\\u3048 */ }\n'
    '        return info;\n'
    '    }\n'
    '\n'
    '    // \\u5143\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u304C\\u307E\\u3060\\u3042\\u308C\\u3070\\u305D\\u306E\\u4ECA\\u306E\\u4F4D\\u7F6E\\u3001\\u6D88\\u3048\\u3066\\u3044\\u308C\\u3070\\u66F8\\u304D\\u63DB\\u3048\\u308B\\u524D\\u306E\\u4F4D\\u7F6E\n'
    '    // \\uFF08\\u6D88\\u3057\\u305F\\u30C6\\u30AD\\u30B9\\u30C8\\u306B\\u89E6\\u308B\\u3068 Illustrator \\u304C\\u300C\\u30AA\\u30D6\\u30B8\\u30A7\\u30AF\\u30C8\\u304C\\u7121\\u52B9\\u3067\\u3059\\u300D\\u306B\\u306A\\u308B\\u306E\\u3067\\u3001\\u6D88\\u3057\\u305F\\u3082\\u306E\\u306F\\u899A\\u3048\\u305F\\u4F4D\\u7F6E\\u3092\\u4F7F\\u3046\\uFF09\n'
    '    function currentBounds(info) {\n'
    '        if (info.removed) return info.bounds;\n'
    '        try { return info.frame.geometricBounds; } catch (e) { return info.bounds; }\n'
    '    }\n'
    '\n'
    '    // \\u8DB3\\u3059\\u30C6\\u30AD\\u30B9\\u30C8\\u306F\\u5C02\\u7528\\u306E\\u30EC\\u30A4\\u30E4\\u30FC\\u300C\\u8FFD\\u52A0\\u30C6\\u30AD\\u30B9\\u30C8\\u300D\\u306B\\u5165\\u308C\\u308B\n'
    '    // \\uFF08\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u30EC\\u30A4\\u30E4\\u30FC\\u304C\\u30ED\\u30C3\\u30AF\\u30FB\\u975E\\u8868\\u793A\\u3060\\u3068\\u6587\\u5B57\\u3092\\u8DB3\\u305B\\u305A\\u306B\\u30A8\\u30E9\\u30FC\\u306B\\u306A\\u308B\\u305F\\u3081\\uFF09\n'
    '    var ADDED_LAYER = "\\u8FFD\\u52A0\\u30C6\\u30AD\\u30B9\\u30C8";\n'
    '\n'
    '    function addedLayer(doc) {\n'
    '        var layer = null;\n'
    '        try { layer = doc.layers.getByName(ADDED_LAYER); } catch (e) { layer = null; }\n'
    '        if (!layer) {\n'
    '            layer = doc.layers.add();\n'
    '            layer.name = ADDED_LAYER;\n'
    '        }\n'
    '        try { layer.locked = false; layer.visible = true; } catch (e2) { /* \\u305D\\u306E\\u307E\\u307E */ }\n'
    '        return layer;\n'
    '    }\n'
    '\n'
    '    function newText(doc, text, size, font) {\n'
    '        var tf = addedLayer(doc).textFrames.add();\n'
    '        tf.contents = text;\n'
    '        var attrs = tf.textRange.characterAttributes;\n'
    '        attrs.size = size;\n'
    '        if (font) {\n'
    '            try { attrs.textFont = font; } catch (e) { /* \\u30D5\\u30A9\\u30F3\\u30C8\\u3092\\u5909\\u3048\\u3089\\u308C\\u306A\\u3051\\u308C\\u3070\\u30C7\\u30D5\\u30A9\\u30EB\\u30C8\\u306E\\u307E\\u307E */ }\n'
    '        }\n'
    '        return tf;\n'
    '    }\n'
    '\n'
    '    // info \\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u306E\\u307E\\u308F\\u308A\\u306B\\u3001\\u5C0F\\u3055\\u306A\\u6587\\u5B57\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u3092\\u8DB3\\u3059\\u3002\n'
    '    //   mode "above"   \\uFF1A\\u4E0A\\uFF08\\u7E26\\u66F8\\u304D\\u306A\\u3089\\u53F3\\u3069\\u306A\\u308A\\uFF09\n'
    '    //   mode "inPlace" \\uFF1Ainfo \\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u304C\\u3042\\u3063\\u305F\\u5834\\u6240\\uFF08\\u80A9\\u66F8\\u304C\\u7A7A\\u3067\\u6D88\\u3048\\u305F\\u3068\\u304D\\uFF09\n'
    '    //   mode "below"   \\uFF1A\\u4E0B\\uFF08\\u7E26\\u66F8\\u304D\\u306A\\u3089\\u5DE6\\u3069\\u306A\\u308A\\uFF09\n'
    '    function addLabelAbove(doc, info, text, size, align, mode) {\n'
    '        var tf = newText(doc, text, size, info.font);\n'
    '        if (info.vertical) {\n'
    '            try { tf.orientation = TextOrientation.VERTICAL; } catch (e) { /* \\u6A2A\\u66F8\\u304D\\u306E\\u307E\\u307E */ }\n'
    '        }\n'
    '        var b = currentBounds(info);                  // [\\u5DE6, \\u4E0A, \\u53F3, \\u4E0B]\\uFF08\\u4E0A\\u306E\\u65B9\\u304C\\u6570\\u5B57\\u304C\\u5927\\u304D\\u3044\\uFF09\n'
    '        var w = tf.width, h = tf.height;\n'
    '        if (info.vertical) {                          // \\u7E26\\u66F8\\u304D\\uFF1A\\u4E0A\\u3092\\u305D\\u308D\\u3048\\u308B\n'
    '            var x = mode === "inPlace" ? b[0] : mode === "below" ? b[0] - LABEL_GAP - w : b[2] + LABEL_GAP;\n'
    '            tf.position = [x, b[1]];\n'
    '        } else {\n'
    '            var left = align === "center" ? (b[0] + b[2]) / 2 - w / 2 : align === "right" ? b[2] - w : b[0];\n'
    '            var top = mode === "inPlace" ? b[1] : mode === "below" ? b[3] - LABEL_GAP : b[1] + LABEL_GAP + h;\n'
    '            tf.position = [left, top];\n'
    '        }\n'
    '        return tf;\n'
    '    }\n'
    '\n'
    '    // \\u7F6E\\u304F\\u5834\\u6240\\u304C\\u898B\\u3064\\u304B\\u3089\\u306A\\u304B\\u3063\\u305F\\u9805\\u76EE\\u3092\\u3001\\u307E\\u3068\\u3081\\u3066\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306E\\u4E2D\\u5FC3\\u304B\\u3089 5cm \\u4E0A\\u306B\\u5165\\u308C\\u308B\\uFF08\\u30C7\\u30D5\\u30A9\\u30EB\\u30C8\\u306E\\u30D5\\u30A9\\u30F3\\u30C8\\u30FB8pt\\uFF09\n'
    '    var FALLBACK_SIZE = 8;\n'
    '\n'
    '    function addFallbackBlock(doc, lines) {\n'
    '        var tf = newText(doc, lines.join("\\r"), FALLBACK_SIZE, null);\n'
    '        try { tf.textRange.paragraphAttributes.justification = Justification.CENTER; } catch (e) { /* \\u5DE6\\u305D\\u308D\\u3048\\u306E\\u307E\\u307E */ }\n'
    '        var c = [0, 0];\n'
    '        try { c = artboardCenter(doc); } catch (e2) { /* \\u30A2\\u30FC\\u30C8\\u30DC\\u30FC\\u30C9\\u304C\\u5206\\u304B\\u3089\\u306A\\u3051\\u308C\\u3070\\u539F\\u70B9 */ }\n'
    '        tf.position = [c[0] - tf.width / 2, c[1] + FALLBACK_OFFSET];\n'
    '        return tf;\n'
    '    }\n'
    '\n'
    '    // \\u7F6E\\u304D\\u5834\\u6240\\u304C\\u306A\\u304B\\u3063\\u305F\\u9805\\u76EE\\u3092\\u3001\\u540D\\u523A\\u3067\\u306E\\u66F8\\u304D\\u65B9\\u306B\\u3057\\u30661\\u884C\\u306B\\u3059\\u308B\n'
    '    var FALLBACK_ORDER = ["\\u4F1A\\u793E\\u540D", "\\u4F1A\\u793E\\u540D\\u82F1\\u5B57", "\\u80A9\\u66F8", "\\u80A9\\u66F8\\u82F1\\u5B57", "\\u6C0F\\u540D", "\\u6C0F\\u540D\\u82F1\\u5B57", "\\u90F5\\u4FBF\\u756A\\u53F7",\n'
    '                          "\\u4F4F\\u62401", "\\u4F4F\\u62402", "\\u82F1\\u5B57\\u4F4F\\u62401", "\\u82F1\\u5B57\\u4F4F\\u62402", "TEL", "FAX", "\\u643A\\u5E2F", "\\u30E1\\u30FC\\u30EB", "URL"];\n'
    '    var FALLBACK_PREFIX = { "\\u90F5\\u4FBF\\u756A\\u53F7": "\\u3012", "TEL": "TEL\\uFF1A", "FAX": "FAX\\uFF1A", "\\u643A\\u5E2F": "Mobile\\uFF1A", "\\u30E1\\u30FC\\u30EB": "E-mail\\uFF1A" };\n'
    '\n'
    '    function fallbackLine(field, value) {\n'
    '        return (FALLBACK_PREFIX[field] || "") + value;\n'
    '    }\n'
    '\n'
    '    // ----- \\u66F8\\u985E\\u5168\\u4F53\\u306E\\u66F8\\u304D\\u63DB\\u3048 -----\n'
    '\n'
    '    // \\u66F8\\u985E\\u306E\\u6587\\u5B57\\u3092\\u6CE8\\u6587\\u5185\\u5BB9\\u306B\\u66F8\\u304D\\u63DB\\u3048\\u308B\\u3002\\u78BA\\u8A8D\\u3057\\u3066\\u307B\\u3057\\u3044\\u3053\\u3068\\u3092 warnings \\u306B\\u8DB3\\u3059\\u3002\n'
    '    function editDocument(doc, rec, warnings) {\n'
    '        removeLogoMarks(doc, rec, warnings);   // LOGO \\u306E\\u6587\\u5B57\\u304C\\u4F1A\\u793E\\u540D\\u306B\\u5909\\u308F\\u308B\\u524D\\u306B\\u63A2\\u3059\n'
    '        try { mergeSplitLabels(doc); }\n'
    '        catch (mergeErr) { warnings.push("\\u300CE-mail\\u300D\\u306A\\u3069\\u306E\\u898B\\u51FA\\u3057\\u3092\\u307E\\u3068\\u3081\\u3089\\u308C\\u307E\\u305B\\u3093\\u3067\\u3057\\u305F\\uFF08" + mergeErr.message + "\\uFF09"); }\n'
    '\n'
    '        var used = [];\n'
    '        var frames = [];\n'
    '        // \\uFF08\\u307E\\u3068\\u3081\\u3066\\u6D88\\u3057\\u305F\\u30C6\\u30AD\\u30B9\\u30C8\\u306F\\u3001\\u3082\\u3046 doc.textFrames \\u306B\\u5165\\u3063\\u3066\\u3044\\u306A\\u3044\\uFF09\n'
    '        for (var i = 0; i < doc.textFrames.length; i++) frames.push(doc.textFrames[i]);\n'
    '\n'
    '        var values = C.prepareValues(rec);\n'
    '        var nameInfo = null, titleInfo = null, companyInfo = null;   // \\u3075\\u308A\\u304C\\u306A\\u30FB\\u90E8\\u7F72\\u540D\\u3092\\u7F6E\\u304F\\u5834\\u6240\\u306E\\u76EE\\u5370\n'
    '        var COMPANY_KEYS = ["\\u4F1A\\u793E\\u540D", "\\u4F1A\\u793E\\u540D_\\u5F8C", "\\u4F1A\\u793E\\u540D_\\u524D", "\\u4F1A\\u793E\\u540D\\u82F1\\u5B57", "(\\u305D\\u306E\\u307E\\u307E)"];\n'
    '        for (var f = 0; f < frames.length; f++) {\n'
    '            var tf = frames[f];\n'
    '            var frameBefore = tf.contents;\n'
    '            var relock = unlockFor(tf);\n'
    '            try {\n'
    '                // \\u30C6\\u30AD\\u30B9\\u30C8\\u306B\\u9805\\u76EE\\u540D\\u306E\\u540D\\u524D\\uFF08\\u4F8B:\\u300C\\u6C0F\\u540D\\u300D\\uFF09\\u304C\\u4ED8\\u3044\\u3066\\u3044\\u308C\\u3070\\u3001\\u4E2D\\u8EAB\\u3092\\u4E38\\u3054\\u3068\\u7F6E\\u304D\\u63DB\\u3048\\u308B\n'
    '                if (tf.name && C.FIELD_ALIASES.hasOwnProperty(tf.name)) {\n'
    '                    if (tf.name === "\\u6C0F\\u540D" && !nameInfo) nameInfo = captureInfo(tf, 0, f);\n'
    '                    if (tf.name === "\\u80A9\\u66F8" && !titleInfo) titleInfo = captureInfo(tf, 0, f);\n'
    '                    if (tf.contents !== "") replaceRange(tf, 0, tf.contents.length, values[tf.name] || "");\n'
    '                    used.push(tf.name);\n'
    '                } else {\n'
    '                    var before = tf.contents;\n'
    '                    var plan = C.planEdits(before, rec);\n'
    '                    for (var u = 0; u < plan.used.length; u++) used.push(plan.used[u]);\n'
    '                    if (!nameInfo && plan.fieldPos.hasOwnProperty("\\u6C0F\\u540D")) nameInfo = captureInfo(tf, plan.fieldPos["\\u6C0F\\u540D"], f);\n'
    '                    if (!titleInfo && plan.fieldPos.hasOwnProperty("\\u80A9\\u66F8")) titleInfo = captureInfo(tf, plan.fieldPos["\\u80A9\\u66F8"], f);\n'
    '                    for (var ck = 0; !companyInfo && ck < COMPANY_KEYS.length; ck++) {\n'
    '                        if (plan.fieldPos.hasOwnProperty(COMPANY_KEYS[ck])) companyInfo = captureInfo(tf, plan.fieldPos[COMPANY_KEYS[ck]], f);\n'
    '                    }\n'
    '                    if (plan.edits.length > 0) {\n'
    '                        var expected = C.applyEditsToString(before, plan.edits);\n'
    '                        try {\n'
    '                            // \\u5F8C\\u308D\\u304B\\u30891\\u304B\\u6240\\u305A\\u3064\\u7F6E\\u304D\\u63DB\\u3048\\u308B\\uFF08\\u6587\\u5B57\\u3054\\u3068\\u306E\\u66F8\\u5F0F\\u3092\\u6B8B\\u3059\\u305F\\u3081\\uFF09\n'
    '                            for (var e = plan.edits.length - 1; e >= 0; e--) {\n'
    '                                replaceRange(tf, plan.edits[e].start, plan.edits[e].end, plan.edits[e].text);\n'
    '                            }\n'
    '                        } catch (rangeErr) {\n'
    '                            // \\u6539\\u884C\\u3092\\u307E\\u305F\\u3050\\u524A\\u9664\\u306A\\u3069\\u3067 Illustrator \\u304C\\u30A8\\u30E9\\u30FC\\u3092\\u51FA\\u3057\\u305F\\u3068\\u304D\\u306F\\u3001\\u4E0B\\u3067\\u4E2D\\u8EAB\\u3054\\u3068\\u5165\\u308C\\u76F4\\u3059\n'
    '                        }\n'
    '                        if (tf.contents !== expected) {\n'
    '                            // \\u5B89\\u5168\\u7B56\\uFF1A\\u3046\\u307E\\u304F\\u7F6E\\u304D\\u63DB\\u308F\\u3089\\u306A\\u304B\\u3063\\u305F\\u3089\\u4E2D\\u8EAB\\u3054\\u3068\\u5165\\u308C\\u76F4\\u3059\n'
    '                            tf.contents = expected;\n'
    '                            warnings.push("\\u6587\\u5B57\\u306E\\u66F8\\u5F0F\\u304C\\u4E00\\u90E8\\u304F\\u305A\\u308C\\u305F\\u304B\\u3082\\u3057\\u308C\\u307E\\u305B\\u3093: \\u300C" + oneLine(expected) + "\\u300D");\n'
    '                        }\n'
    '                        fixSpacing(tf, plan.edits);   // \\u300C\\uFF1A\\u300D\\u304C\\u898B\\u51FA\\u3057\\u306B\\u91CD\\u306A\\u3089\\u306A\\u3044\\u3088\\u3046\\u6587\\u5B57\\u306E\\u9593\\u9694\\u3092\\u305D\\u308D\\u3048\\u308B\n'
    '                    }\n'
    '                    for (var nt = 0; nt < plan.notes.length; nt++) warnings.push(plan.notes[nt]);\n'
    '                    for (var r = 0; r < plan.leftoverRemoved.length; r++) {\n'
    '                        warnings.push("\\u898B\\u3064\\u304B\\u3089\\u306A\\u3044\\u4EEE\\u306E\\u6587\\u5B57\\u304C\\u6B8B\\u3063\\u3066\\u3044\\u305F\\u306E\\u3067\\u884C\\u3092\\u6D88\\u3057\\u307E\\u3057\\u305F: \\u300C" + oneLine(plan.leftoverRemoved[r]) + "\\u300D");\n'
    '                    }\n'
    '                }\n'
    '            } catch (err) {\n'
    '                warnings.push("\\u30C6\\u30AD\\u30B9\\u30C8\\u3092\\u66F8\\u304D\\u63DB\\u3048\\u3089\\u308C\\u307E\\u305B\\u3093\\u3067\\u3057\\u305F\\uFF08" + err.message + "\\uFF09: \\u300C" + oneLine(tf.contents) + "\\u300D");\n'
    '            }\n'
    '            // \\u672A\\u5165\\u529B\\u3067\\u4E2D\\u8EAB\\u304C\\u7A7A\\u306B\\u306A\\u3063\\u305F\\u30C6\\u30AD\\u30B9\\u30C8\\u306F\\u3001\\u30C6\\u30AD\\u30B9\\u30C8\\u3054\\u3068\\u6D88\\u3059\n'
    '            var emptied = false;\n'
    '            try {\n'
    '                if (frameBefore !== "" && C.trim(tf.contents) === "") {\n'
    '                    // \\u6D88\\u3059\\u524D\\u306B\\uFF08\\u307E\\u3060\\u6709\\u52B9\\u306A\\u3046\\u3061\\u306B\\uFF09\\u76EE\\u5370\\u306E\\u30C6\\u30AD\\u30B9\\u30C8\\u304B\\u3069\\u3046\\u304B\\u3092\\u8A18\\u9332\\u3059\\u308B\n'
    '                    var infos = [nameInfo, titleInfo, companyInfo];\n'
    '                    for (var ii = 0; ii < infos.length; ii++) {\n'
    '                        if (infos[ii] && infos[ii].frameIndex === f) infos[ii].removed = true;   // \\u756A\\u53F7\\u3067\\u6BD4\\u3079\\u308B\\uFF08\\u6D88\\u3057\\u305F\\u3082\\u306E\\u3068\\u306F\\u6BD4\\u3079\\u306A\\u3044\\uFF09\n'
    '                    }\n'
    '                    tf.remove();\n'
    '                    emptied = true;\n'
    '                }\n'
    '            } catch (removeErr) { /* \\u6D88\\u305B\\u306A\\u304F\\u3066\\u3082\\u7A7A\\u306A\\u306E\\u3067\\u898B\\u305F\\u76EE\\u306F\\u540C\\u3058 */ }\n'
    '            if (!emptied) relock();\n'
    '        }\n'
    '        // \\u7F6E\\u304D\\u5834\\u6240\\u304C\\u898B\\u3064\\u304B\\u3089\\u306A\\u304B\\u3063\\u305F\\u9805\\u76EE\\u306F fallback \\u306B\\u96C6\\u3081\\u3066\\u3001\\u6700\\u5F8C\\u306B\\u307E\\u3068\\u3081\\u3066\\u4E2D\\u5FC3\\u304B\\u3089 5cm \\u4E0A\\u306B\\u5165\\u308C\\u308B\n'
    '        var fallback = [], fallbackNames = [];\n'
    '        function toFallback(name, line) { fallback.push(line); fallbackNames.push(name); }\n'
    '\n'
    '        // \\u3075\\u308A\\u304C\\u306A\\uFF1A\\u6C0F\\u540D\\u306E\\u4E0A\\u306B\\u3001\\u6C0F\\u540D\\u3068\\u540C\\u3058\\u30D5\\u30A9\\u30F3\\u30C8\\u3067 5pt\\uFF08\\u4E2D\\u592E\\u305D\\u308D\\u3048\\uFF09\n'
    '        if (rec["\\u3075\\u308A\\u304C\\u306A"]) {\n'
    '            var furiDone = false;\n'
    '            if (nameInfo) {\n'
    '                try { addLabelAbove(doc, nameInfo, rec["\\u3075\\u308A\\u304C\\u306A"], FURIGANA_SIZE, "center", "above"); furiDone = true; }\n'
    '                catch (furiErr) { /* \\u4E0B\\u3067\\u307E\\u3068\\u3081\\u3066\\u5165\\u308C\\u308B */ }\n'
    '            }\n'
    '            if (!furiDone) toFallback("\\u3075\\u308A\\u304C\\u306A", rec["\\u3075\\u308A\\u304C\\u306A"]);\n'
    '        }\n'
    '        // \\u90E8\\u7F72\\u540D\\uFF1A8pt\\u3002\\u7F6E\\u304F\\u5834\\u6240\\u306F\\u4E0A\\u304B\\u3089\\u9806\\u306B\n'
    '        //   1. \\u80A9\\u66F8\\u306E\\u4E0A\\uFF08\\u4F1A\\u793E\\u540D\\u3068\\u80A9\\u66F8\\u306E\\u9593\\uFF09\\u2026 \\u80A9\\u66F8\\u3068\\u540C\\u3058\\u30D5\\u30A9\\u30F3\\u30C8\\u30FB\\u305D\\u308D\\u3048\\u65B9\n'
    '        //   2. \\u80A9\\u66F8\\u304C\\u7A7A\\u3067\\u6D88\\u3048\\u305F\\u3068\\u304D\\u306F\\u3001\\u80A9\\u66F8\\u304C\\u3042\\u3063\\u305F\\u5834\\u6240\n'
    '        //   3. \\u80A9\\u66F8\\u306E\\u5834\\u6240\\u304C\\u306A\\u3044\\u30C7\\u30B6\\u30A4\\u30F3\\u306F\\u3001\\u6C0F\\u540D\\u306E\\u4E0A\n'
    '        //   4. \\u80A9\\u66F8\\u3082\\u6C0F\\u540D\\u3082\\u5834\\u6240\\u304C\\u306A\\u3051\\u308C\\u3070\\u3001\\u4F1A\\u793E\\u540D\\u306E\\u4E0B\n'
    '        //   5. \\u3069\\u308C\\u3082\\u898B\\u3064\\u304B\\u3089\\u306A\\u3044\\u30FB\\u5165\\u308C\\u3089\\u308C\\u306A\\u3051\\u308C\\u3070\\u3001\\u4E2D\\u5FC3\\u304B\\u3089 5cm \\u4E0A\\uFF08\\u307E\\u3068\\u3081\\u3066\\uFF09\n'
    '        if (rec["\\u90E8\\u7F72"]) {\n'
    '            var titleGone = !!(titleInfo && titleInfo.removed);\n'
    '            var tries = [];\n'
    '            if (titleInfo) tries.push([titleInfo, titleGone ? "inPlace" : "above", titleGone ? "\\u80A9\\u66F8\\u306E\\u5834\\u6240" : "\\u80A9\\u66F8\\u306E\\u4E0A"]);\n'
    '            if (nameInfo) tries.push([nameInfo, "above", "\\u6C0F\\u540D\\u306E\\u4E0A"]);\n'
    '            if (companyInfo) tries.push([companyInfo, "below", "\\u4F1A\\u793E\\u540D\\u306E\\u4E0B"]);\n'
    '            var deptWhere = null;\n'
    '            for (var tr = 0; tr < tries.length && !deptWhere; tr++) {\n'
    '                try {\n'
    '                    addLabelAbove(doc, tries[tr][0], rec["\\u90E8\\u7F72"], DEPARTMENT_SIZE, tries[tr][0].align, tries[tr][1]);\n'
    '                    deptWhere = tries[tr][2];\n'
    '                } catch (deptErr) { /* \\u6B21\\u306E\\u5834\\u6240\\u3092\\u8A66\\u3059 */ }\n'
    '            }\n'
    '            if (deptWhere) warnings.push("\\u90E8\\u7F72\\u540D\\u3092" + deptWhere + "\\u306B\\u5165\\u308C\\u307E\\u3057\\u305F\\uFF08\\u4F4D\\u7F6E\\u3092\\u78BA\\u8A8D\\u3057\\u3066\\u304F\\u3060\\u3055\\u3044\\uFF09");\n'
    '            else toFallback("\\u90E8\\u7F72\\u540D", rec["\\u90E8\\u7F72"]);\n'
    '        }\n'
    '\n'
    '        // \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u306B\\u5DEE\\u3057\\u8FBC\\u307F\\u5148\\u304C\\u306A\\u304B\\u3063\\u305F\\u9805\\u76EE\\u3082\\u3001\\u6D41\\u3057\\u8FBC\\u307F\\u6F0F\\u308C\\u304C\\u306A\\u3044\\u3088\\u3046\\u306B\\u6253\\u3061\\u8FBC\\u3080\n'
    '        var unused = C.unusedFields(rec, used);\n'
    '        for (var fo = 0; fo < FALLBACK_ORDER.length; fo++) {\n'
    '            for (var un = 0; un < unused.length; un++) {\n'
    '                if (unused[un] === FALLBACK_ORDER[fo]) toFallback(unused[un], fallbackLine(unused[un], rec[unused[un]]));\n'
    '            }\n'
    '        }\n'
    '        if (rec["\\u81EA\\u7531\\u884C"]) toFallback("\\u81EA\\u7531\\u8A18\\u5165\\uFF08\\u884C\\u76EE\\uFF09", rec["\\u81EA\\u7531\\u884C"].split(" / ").join("\\r"));\n'
    '\n'
    '        if (fallback.length > 0) {\n'
    '            try {\n'
    '                addFallbackBlock(doc, fallback);\n'
    '                warnings.push("\\u7F6E\\u304D\\u5834\\u6240\\u304C\\u898B\\u3064\\u304B\\u3089\\u306A\\u304B\\u3063\\u305F\\u9805\\u76EE\\u3092\\u4E2D\\u5FC3\\u304B\\u30895cm\\u4E0A\\u306B\\u5165\\u308C\\u307E\\u3057\\u305F\\uFF08\\u79FB\\u52D5\\u3057\\u3066\\u304F\\u3060\\u3055\\u3044\\uFF09: " + fallbackNames.join("\\u3001"));\n'
    '            } catch (fbErr) {\n'
    '                warnings.push("\\u9805\\u76EE\\u3092\\u5165\\u308C\\u3089\\u308C\\u307E\\u305B\\u3093\\u3067\\u3057\\u305F\\uFF08" + fbErr.message + "\\uFF09: " + oneLine(fallback.join(" / "), 120));\n'
    '            }\n'
    '        }\n'
    '\n'
    '        // \\u540D\\u523A\\u306B\\u306F\\u5165\\u308C\\u3066\\u3044\\u306A\\u3044\\u304C\\u3001\\u76EE\\u3067\\u78BA\\u8A8D\\u3057\\u3066\\u307B\\u3057\\u3044\\u60C5\\u5831\n'
    '        if (C.hasLogoData(rec)) warnings.push("\\u30ED\\u30B4\\u30C7\\u30FC\\u30BF\\u6709\\u308A: LOGO \\u306E\\u4F4D\\u7F6E\\u306B\\u30ED\\u30B4\\u3092\\u914D\\u7F6E\\u3057\\u3066\\u304F\\u3060\\u3055\\u3044");\n'
    '        if (rec["\\u5099\\u8003"]) {\n'
    '            try { addRemarks(doc, rec["\\u5099\\u8003"], warnings); }\n'
    '            catch (remarkErr) { warnings.push("\\u5099\\u8003\\u3092\\u5165\\u308C\\u3089\\u308C\\u307E\\u305B\\u3093\\u3067\\u3057\\u305F\\uFF08" + remarkErr.message + "\\uFF09: " + oneLine(rec["\\u5099\\u8003"], 80)); }\n'
    '        }\n'
    '        if (rec["\\u78BA\\u8A8D\\u4E8B\\u9805"]) warnings.push(rec["\\u78BA\\u8A8D\\u4E8B\\u9805"]);\n'
    '    }\n'
    '\n'
    '    return {\n'
    '        readTextFile: readTextFile,\n'
    '        oneLine: oneLine,\n'
    '        isNextToLogo: isNextToLogo,\n'
    '        pickMarks: pickMarks,\n'
    '        addRemarks: addRemarks,\n'
    '        addLabelAbove: addLabelAbove,\n'
    '        fallbackLine: fallbackLine,\n'
    '        mergeSplitLabels: mergeSplitLabels,\n'
    '        fixSpacing: fixSpacing,\n'
    '        debugLog: debugLog,\n'
    '        REMARK_OFFSET: REMARK_OFFSET,\n'
    '        FALLBACK_OFFSET: FALLBACK_OFFSET,\n'
    '        editDocument: editDocument\n'
    '    };\n'
    '})();\n'
    '\n'
    '\n'
    '(function () {\n'
    '    var C = MeishiCore;\n'
    '    var JOB_FILE = new File(Folder.userData + "/meishi_job.txt");\n'
    '\n'
    '    if (!JOB_FILE.exists) {\n'
    '        alert("\\u540D\\u523A\\u4F5C\\u6210\\u306E\\u6307\\u793A\\u30D5\\u30A1\\u30A4\\u30EB\\u304C\\u898B\\u3064\\u304B\\u308A\\u307E\\u305B\\u3093\\u3002\\n\\u6CE8\\u6587\\u901A\\u77E5\\u30A2\\u30D7\\u30EA\\u306E\\uFF3B\\u540D\\u523A\\u3092\\u4F5C\\u6210\\uFF3D\\u30DC\\u30BF\\u30F3\\u304B\\u3089\\u5B9F\\u884C\\u3057\\u3066\\u304F\\u3060\\u3055\\u3044\\u3002");\n'
    '        return;\n'
    '    }\n'
    '    JOB_FILE.encoding = "UTF-8";   // \\u4E2D\\u8EAB\\u306F\\u82F1\\u6570\\u5B57\\u3060\\u3051\n'
    '    JOB_FILE.open("r");\n'
    '    var records = C.parseJob(JOB_FILE.read());\n'
    '    JOB_FILE.close();\n'
    '    JOB_FILE.remove();   // \\u540C\\u3058\\u6307\\u793A\\u3067\\u4E8C\\u5EA6\\u4F5C\\u3089\\u306A\\u3044\\u3088\\u3046\\u306B\\u6D88\\u3059\n'
    '    if (!records) {\n'
    '        alert("\\u540D\\u523A\\u4F5C\\u6210\\u306E\\u6307\\u793A\\u30D5\\u30A1\\u30A4\\u30EB\\u306E\\u5F62\\u304C\\u9055\\u3044\\u307E\\u3059\\u3002\\u6CE8\\u6587\\u901A\\u77E5\\u30A2\\u30D7\\u30EA\\u3092\\u6700\\u65B0\\u7248\\u306B\\u3057\\u3066\\u304F\\u3060\\u3055\\u3044\\u3002");\n'
    '        return;\n'
    '    }\n'
    '\n'
    '    var report = [];\n'
    '    var oldLevel = app.userInteractionLevel;\n'
    '    app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;   // \\u30D5\\u30A9\\u30F3\\u30C8\\u4E0D\\u8DB3\\u306A\\u3069\\u306E\\u78BA\\u8A8D\\u3092\\u51FA\\u3055\\u306A\\u3044\n'
    '    try {\n'
    '        for (var i = 0; i < records.length; i++) {\n'
    '            var rec = records[i];\n'
    '            var warnings = [];\n'
    '            if (!rec["\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8"] || !rec["\\u4FDD\\u5B58\\u5148"]) {\n'
    '                var keys = [];\n'
    '                for (var k in rec) if (rec.hasOwnProperty(k)) keys.push(k);\n'
    '                report.push("\\u2715 " + (rec["\\u6CE8\\u6587\\u756A\\u53F7"] || "") + "\\n   \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u304B\\u4FDD\\u5B58\\u5148\\u304C\\u6307\\u5B9A\\u3055\\u308C\\u3066\\u3044\\u307E\\u305B\\u3093\\uFF08\\u53D7\\u3051\\u53D6\\u3063\\u305F\\u9805\\u76EE: " + keys.join("\\u3001") + "\\uFF09");\n'
    '                continue;\n'
    '            }\n'
    '            var tpl = new File(rec["\\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8"]);\n'
    '            var out = new File(rec["\\u4FDD\\u5B58\\u5148"]);\n'
    '            var title = (rec["\\u6CE8\\u6587\\u756A\\u53F7"] || "") + "  " + decodeURI(out.name);\n'
    '            if (!tpl.exists) {\n'
    '                report.push("\\u2715 " + (rec["\\u6CE8\\u6587\\u756A\\u53F7"] || "") + "\\n   \\u30C6\\u30F3\\u30D7\\u30EC\\u30FC\\u30C8\\u304C\\u898B\\u3064\\u304B\\u308A\\u307E\\u305B\\u3093: " + tpl.fsName);\n'
    '                continue;\n'
    '            }\n'
    '            try {\n'
    '                var doc = app.open(tpl);\n'
    '                MeishiAI.editDocument(doc, rec, warnings);\n'
    '                if (!out.parent.exists) out.parent.create();\n'
    '                var opts = new IllustratorSaveOptions();\n'
    '                opts.pdfCompatible = true;\n'
    '                doc.saveAs(out, opts);       // \\u5225\\u540D\\u4FDD\\u5B58\\u3002\\u66F8\\u985E\\u306F\\u958B\\u3044\\u305F\\u307E\\u307E\\u306B\\u3059\\u308B\n'
    '            } catch (err) {\n'
    '                report.push("\\u2715 " + title + "\\n   \\u30A8\\u30E9\\u30FC: " + err.message);\n'
    '                continue;\n'
    '            }\n'
    '            if (warnings.length > 0) {\n'
    '                report.push("\\u25B3 " + title + "\\n   - " + warnings.join("\\n   - "));\n'
    '            }\n'
    '        }\n'
    '    } finally {\n'
    '        app.userInteractionLevel = oldLevel;\n'
    '    }\n'
    '\n'
    '    // \\u78BA\\u8A8D\\u7528\\u30ED\\u30B0\\uFF08\\u3046\\u307E\\u304F\\u3044\\u304B\\u306A\\u3044\\u3068\\u304D\\u306B\\u9001\\u3063\\u3066\\u3082\\u3089\\u3046\\uFF09\\uFF1A\\u30C7\\u30B9\\u30AF\\u30C8\\u30C3\\u30D7\\u306E\\u300C\\u540D\\u523A\\u4F5C\\u6210\\u30ED\\u30B0.txt\\u300D\n'
    '    try {\n'
    '        var log = new File(Folder.desktop + "/\\u540D\\u523A\\u4F5C\\u6210\\u30ED\\u30B0.txt");\n'
    '        log.encoding = "UTF-8";\n'
    '        log.open("w");\n'
    '        log.write("\\uFEFF" + report.join("\\n\\n") + "\\n\\n--- \\u6587\\u5B57\\u306E\\u9593\\u9694\\uFF08k=\\u30AB\\u30FC\\u30CB\\u30F3\\u30B0, t=\\u30C8\\u30E9\\u30C3\\u30AD\\u30F3\\u30B0\\uFF09 ---\\n" +\n'
    '                  MeishiAI.debugLog.join("\\n"));\n'
    '        log.close();\n'
    '    } catch (logErr) { /* \\u30ED\\u30B0\\u304C\\u66F8\\u3051\\u306A\\u304F\\u3066\\u3082\\u540D\\u523A\\u3065\\u304F\\u308A\\u306B\\u306F\\u95A2\\u4FC2\\u306A\\u3044 */ }\n'
    '\n'
    '    if (report.length > 0) {\n'
    '        alert("\\u540D\\u523A\\u3092\\u4F5C\\u6210\\u3057\\u307E\\u3057\\u305F\\u3002\\u6B21\\u306E\\u70B9\\u3092\\u78BA\\u8A8D\\u3057\\u3066\\u304F\\u3060\\u3055\\u3044\\u3002\\n\\n" + report.join("\\n\\n"));\n'
    '    }\n'
    '})();\n'
)
# ---- ここまで自動生成 ----
