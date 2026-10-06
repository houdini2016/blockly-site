"""注文通知アプリの注文データから、名刺作成用のCSVを作る部品。

注文通知アプリ（chumon_notifier.py）が整理した注文詳細（_parse_detail_items の結果）を
名刺の項目（氏名・肩書・住所・TEL…）に振り分け、Illustrator スクリプト
（meishi_auto.jsx）が読める CSV に書き出します。

この部品はメールにもインターネットにも接続しません（受け取った文字を整理するだけ）。
"""
import csv
import os
import re
import subprocess

# meishi_auto.jsx が読む列（順番どおりに書き出す）
CSV_COLUMNS = [
    "注文番号", "モール", "デザイン番号",
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
# デザイン番号の形（business008, abstract001 など）。後ろに「など」が付くものは例示なので除く
_DESIGN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]+[-_]?\d{3})(?![0-9])(?!など)")


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


def _find_design(card, detail, product):
    # ① 「作成するデザインの商品番号」の欄
    for line in detail.split("\n"):
        if "デザイン" in line and "番号" in line:
            value = _option_value(line)
            found = _DESIGN.findall(value) or _DESIGN.findall(line)
            if found:
                card["デザイン番号"] = found[-1]
                return
            if value:
                _add_note(card, f"デザイン番号の欄: 「{value}」")
                return
    # ② 商品名・注文詳細の中のデザイン番号らしき文字
    found = []
    for token in _DESIGN.findall((product or "") + "\n" + detail):
        if token.lower() not in [f.lower() for f in found]:
            found.append(token)
    if len(found) == 1:
        card["デザイン番号"] = found[0]
    elif found:
        card["デザイン番号"] = found[0]
        _add_note(card, "デザイン番号の候補が複数あります: " + "、".join(found))
    else:
        _add_note(card, "デザイン番号が見つかりません")


def card_from_order(order, items):
    """1件の注文を名刺の項目に振り分ける。

    order: 注文通知アプリの注文（order_id, mall, customer, product, detail を持つ dict）
    items: _parse_detail_items(order["detail"]) の結果
    """
    card = {c: "" for c in CSV_COLUMNS}
    card["注文番号"] = order.get("order_id", "")
    card["モール"] = order.get("mall", "")
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

    _find_design(card, order.get("detail", ""), order.get("product", ""))
    return card


def write_csv(path, cards):
    """Illustrator スクリプト用の CSV を書き出す（Excel でも文字化けしない UTF-8 BOM 付き）。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
        w.writeheader()
        for card in cards:
            w.writerow({c: card.get(c, "") for c in CSV_COLUMNS})


# ----------------------------------------------------------------------
#  Illustrator を呼び出す（Mac 用）
# ----------------------------------------------------------------------

# meishi_auto.jsx が前回の設定を保存している場所（Illustrator の Folder.userData）
ILLUSTRATOR_SETTINGS = os.path.expanduser("~/Library/Application Support/meishi_auto_settings.txt")


def set_csv_for_illustrator(csv_path, settings_path=ILLUSTRATOR_SETTINGS):
    """meishi_auto.jsx の画面に、今作った CSV が最初から入っているようにする。"""
    settings = {}
    if os.path.exists(settings_path):
        with open(settings_path, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.rstrip("\r\n").split("=", 1)
                    settings[k] = v
    settings["csv"] = csv_path
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        for k, v in settings.items():
            f.write(f"{k}={v}\n")


def run_illustrator_script(jsx_path):
    """Illustrator を前面に出して meishi_auto.jsx を実行する（終わるのは待たない）。"""
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
