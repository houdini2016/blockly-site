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
