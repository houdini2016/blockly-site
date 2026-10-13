"""市外局番の長さの表を作り、mail/meishi_export.py の中に書き込む。

10桁の固定電話の番号（数字だけ）にハイフンを入れるとき、市外局番が何桁かを決めるのに使う表です。
（例：0930310490 → 0930-31-0490、0312345678 → 03-1234-5678）
電話番号のライブラリ phonenumbers（Google の libphonenumber）の日本のデータから作ります。
アプリでは phonenumbers を使わないので、表だけを埋め込みます。市外局番が変わったときに実行してください。
    pip install phonenumbers
    python3 tools/make_area_codes.py
"""
import pathlib

import phonenumbers as P

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "mail" / "meishi_export.py"
BEGIN = "# ---- ここから自動生成（tools/make_area_codes.py）。手で書き換えないでください ----\n"
END = "# ---- ここまで自動生成（市外局番） ----\n"
FILLERS = ("0000", "5555", "9999", "1234")


def area_length(number):
    """10桁の番号を phonenumbers で区切ったときの、市外局番の桁数（3つに区切れなければ None）"""
    try:
        n = P.parse(number, "JP")
    except P.NumberParseException:
        return None
    parts = P.format_number(n, P.PhoneNumberFormat.NATIONAL).split("-")
    return len(parts[0]) if len(parts) == 3 and len(parts[2]) == 4 else None


def table():
    # 先頭6桁ごとに桁数を調べ、同じ桁数になる番号をまとめて短い頭の数字にする
    six = {}
    for i in range(100000):
        p = "0" + str(i).zfill(5)
        if p[1] == "0":
            continue
        vals = {area_length(p + f) for f in FILLERS}
        assert len(vals) == 1, p     # 7桁目以降で桁数が変わる番号はない
        six[p] = vals.pop()

    def build(prefix):
        if len(prefix) == 6:
            return {prefix: six.get(prefix)}
        kids = {}
        for d in "0123456789":
            kids.update(build(prefix + d))
        vals = set(kids.values())
        return {prefix: vals.pop()} if len(vals) == 1 else kids

    out = {}
    for d in "123456789":
        out.update(build("0" + d))
    return {k: v for k, v in out.items() if v is not None}


def render(t):
    lines = [BEGIN, "AREA_CODE_PREFIXES = {\n"]
    for length in sorted(set(t.values())):
        codes = sorted(k for k, v in t.items() if v == length)
        lines.append(f"    {length}: (\n")
        for i in range(0, len(codes), 14):
            lines.append('        "' + " ".join(codes[i:i + 14]) + ' "\n')
        lines.append("    ),\n")
    lines.append("}\n")
    lines.append(END)
    return "".join(lines)


if __name__ == "__main__":
    src = TARGET.read_text(encoding="utf-8")
    a, b = src.index(BEGIN), src.index(END) + len(END)
    TARGET.write_text(src[:a] + render(table()) + src[b:], encoding="utf-8")
    print("meishi_export.py に市外局番の表を書き込みました")
