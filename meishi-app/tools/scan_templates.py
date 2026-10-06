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
    lines, images = [], []
    for page in doc:
        for im in page.get_image_info():
            # 画像の細かさ（1pt あたりのピクセル数）。貼り込んだ画像は高く、
            # 透明やグラデーションを PDF 用に画像化した断片は 1 前後になる
            w = im["bbox"][2] - im["bbox"][0]
            dpp = round(im["width"] / w, 1) if w > 0 else 0
            images.append({"bbox": [round(v, 1) for v in im["bbox"]], "px_per_pt": dpp})
        vertical = []
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(c["c"] for s in line["spans"] for c in s["chars"])
                if text.strip():
                    span = line["spans"][0]
                    item = {"text": text, "font": span["font"], "size": round(span["size"], 1),
                            "bbox": [round(v, 1) for v in line["bbox"]]}
                    if abs(line["dir"][1]) > 0.9:   # 縦書き（PDF では1文字ずつに分かれる）
                        vertical.append(item)
                    else:
                        lines.append(item)
        lines = join_horizontal(lines) + join_vertical(vertical)
    return {"lines": lines, "images": images}


def join_horizontal(items):
    """同じ高さに並んでいる横書きの文字を1行につなげる（PDF ではタブなどで分かれるため）。"""
    items = sorted(items, key=lambda i: (round(i["bbox"][3]), i["bbox"][0]))
    out = []
    for it in items:
        prev = out[-1] if out else None
        size = it["bbox"][3] - it["bbox"][1]
        if (prev and abs(prev["bbox"][3] - it["bbox"][3]) < 1.5
                and -1 <= it["bbox"][0] - prev["bbox"][2] < size * 4):
            gap = it["bbox"][0] - prev["bbox"][2]
            prev["text"] += ("\t" if gap >= size * 0.5 else "") + it["text"]
            prev["bbox"][2] = it["bbox"][2]
        else:
            out.append(dict(it, bbox=list(it["bbox"])))
    return out


def join_vertical(items):
    """縦書きの文字を、同じ列で続いているものごとに1行へつなげる。

    文字と文字の間が文字の大きさの半分以上空いていれば、全角スペースが入っていたとみなす。
    """
    items = sorted(items, key=lambda i: (round(i["bbox"][0]), i["bbox"][1]))
    out = []
    for it in items:
        prev = out[-1] if out else None
        size = it["bbox"][3] - it["bbox"][1]
        if prev and abs(prev["bbox"][0] - it["bbox"][0]) < 2 and -size <= it["bbox"][1] - prev["bbox"][3] < size * 2.5:
            gap = it["bbox"][1] - prev["bbox"][3]
            prev["text"] += ("\u3000" if gap >= size * 0.5 else "") + it["text"]
            prev["bbox"][3] = it["bbox"][3]
        else:
            out.append(dict(it, bbox=list(it["bbox"]), vertical=True))
    return out


def main():
    root = pathlib.Path(sys.argv[1])
    result = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() != ".ai":
            continue
        try:
            result.append(dict(file=str(path.relative_to(root)), **scan(path)))
        except Exception as e:  # PDF互換でない .ai など
            result.append({"file": str(path.relative_to(root)), "error": str(e)})
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
