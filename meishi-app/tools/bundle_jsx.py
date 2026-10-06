"""meishi_core.jsx・meishi_ai.jsx・meishi_job.jsx を1つにまとめ、mail/meishi_export.py の中に埋め込む。

注文通知アプリは、埋め込んだスクリプトを毎回書き出して Illustrator に渡すので、
アプリの中に .jsx ファイルが無くても動きます。.jsx を直したら必ずこれを実行してください。
    python3 tools/bundle_jsx.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "mail" / "meishi_export.py"
BEGIN = "# ---- ここから自動生成（tools/bundle_jsx.py）。手で書き換えないでください ----\n"
END = "# ---- ここまで自動生成 ----\n"


def bundled_jsx():
    def read(name):
        return (ROOT / name).read_text(encoding="utf-8-sig")
    job = read("meishi_job.jsx")
    job = re.sub(r'^#include "meishi_core.jsx"\n', lambda m: read("meishi_core.jsx") + "\n", job, flags=re.M)
    job = re.sub(r'^#include "meishi_ai.jsx"\n', lambda m: read("meishi_ai.jsx") + "\n", job, flags=re.M)
    assert not re.search(r"^#include", job, flags=re.M)
    return to_ascii(job)


def to_ascii(text):
    """日本語などを \\uXXXX に置き換えて、英数字だけのスクリプトにする。

    Illustrator がスクリプトをどの文字コードで読んでも、日本語が化けないようにするため。
    （文字列・正規表現・コメントのどこにあっても \\uXXXX は同じ意味になる）
    """
    out = []
    for ch in text:
        code = ord(ch)
        if code < 0x80:
            out.append(ch)
        elif code <= 0xFFFF:
            out.append("\\u%04X" % code)
        else:  # 絵文字など（2つの \\u に分ける）
            code -= 0x10000
            out.append("\\u%04X\\u%04X" % (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)))
    return "".join(out)


def main():
    body = bundled_jsx()
    lines = ["JOB_JSX = (\n"] + [f"    {line!r}\n" for line in body.splitlines(keepends=True)] + [")\n"]
    src = TARGET.read_text(encoding="utf-8")
    a, b = src.index(BEGIN) + len(BEGIN), src.index(END)
    TARGET.write_text(src[:a] + "".join(lines) + src[b:], encoding="utf-8")
    print(f"{TARGET.name} に埋め込みました（{len(body)} 文字）")


if __name__ == "__main__":
    main()
