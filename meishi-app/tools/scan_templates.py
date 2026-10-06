"""テンプレート(.ai)の文字をまとめて取り出し、JSON に書き出す（開発用の検査ツール）。

使い方:
    pip install pymupdf
    python scan_templates.py テンプレートフォルダ > templates.json
    node scan_report.js templates.json > report.md

.ai は「PDF互換ファイルを作成」にチェックを入れて保存されている必要があります。
取り出した文字は Illustrator 上の行とほぼ同じですが、完全には一致しないことがあります。
"""
import json
import pathlib
import sys

import pymupdf


def scan(path):
    doc = pymupdf.open(path)
    lines = []
    for page in doc:
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(c["c"] for s in line["spans"] for c in s["chars"])
                if text.strip():
                    span = line["spans"][0]
                    lines.append({"text": text, "font": span["font"], "size": round(span["size"], 1)})
    return lines


def main():
    root = pathlib.Path(sys.argv[1])
    result = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() != ".ai":
            continue
        try:
            result.append({"file": str(path.relative_to(root)), "lines": scan(path)})
        except Exception as e:  # PDF互換でない .ai など
            result.append({"file": str(path.relative_to(root)), "error": str(e)})
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
