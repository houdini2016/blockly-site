"""meishi_export.py のテスト。  実行: python3 meishi-app/mail/test_meishi_export.py

items は注文通知アプリの _parse_detail_items が返す形をそのまま書いたものです。
"""
import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meishi_export as M  # noqa: E402

RAKUTEN_DETAIL = """【楽天】
注文番号：297406-20261006-0833446491
お試し名刺40枚
SKU管理番号otameshi
作成するデザインの商品番号（例：business001など） ※当店の100枚販売の名刺デザインから1つ選んでいただき40枚で作成します。business008
ロゴデータ（無しの場合、会社名：の項目がLOGO位置に入ります）無し"""

RAKUTEN_ITEMS = [
    {"label": "", "value": "【楽天】", "group": "section"},
    {"label": "注文番号", "value": "297406-20261006-0833446491", "group": None},
    {"label": "", "value": "SKU管理番号otameshi", "group": None},
    {"label": "", "value": "ロゴデータ（無しの場合、会社名：の項目がLOGO位置に入ります）無し", "group": None},
    {"label": "会社名", "value": "株式会社サンプル", "group": None},
    {"label": "部署名", "value": "営業部", "group": None},
    {"label": "肩書き", "value": "部長", "group": None},
    {"label": "氏名", "value": "山田 太郎", "group": None},
    {"label": "ふりがな", "value": "Taro Yamada", "group": None},
    {"label": "住所", "group": "address", "value":
        "〒100-0005\n東京都千代田区\n丸の内1-2-3\nサンプルビル5F\nTEL：03-1234-5678\n"
        "Mobile：090-1111-2222\nE-mail：taro@example.co.jp\nhttps//example.co.jp/"},
    {"label": "行目", "value": "一級建築士", "group": "lines"},
    {"label": "", "value": "[備考]\n校正は不要です", "group": None},
]


def self_card():
    return {"注文番号": "1", "氏名": "山田 太郎", "会社名": "株式会社A&B, \"テスト\""}


class CardFromOrderTests(unittest.TestCase):
    def rakuten(self):
        order = {"order_id": "297406-20261006-0833446491", "mall": "楽天", "customer": "山田 太郎",
                 "product": "お試し名刺40枚", "detail": RAKUTEN_DETAIL}
        return M.card_from_order(order, RAKUTEN_ITEMS)

    def test_rakuten_fields(self):
        c = self.rakuten()
        self.assertEqual(c["注文者"], "山田 太郎")
        self.assertEqual(c["会社名"], "株式会社サンプル")
        self.assertEqual((c["部署"], c["肩書"], c["氏名"]), ("営業部", "部長", "山田 太郎"))
        self.assertEqual(c["氏名英字"], "Taro Yamada")      # ローマ字のふりがなは英字氏名へ
        self.assertEqual(c["郵便番号"], "100-0005")
        self.assertEqual(c["住所1"], "東京都千代田区丸の内1-2-3")
        self.assertEqual(c["住所2"], "サンプルビル5F")
        self.assertEqual((c["TEL"], c["携帯"]), ("03-1234-5678", "090-1111-2222"))
        self.assertEqual(c["メール"], "taro@example.co.jp")
        self.assertEqual(c["URL"], "https://example.co.jp/")  # https// を直す
        self.assertEqual(c["ロゴデータ"], "無し")
        self.assertEqual(c["自由行"], "一級建築士")
        self.assertEqual(c["備考"], "校正は不要です")
        self.assertEqual(c["確認事項"], "")

    def test_yahoo_name_with_ruby_and_no_orderer(self):
        c = M.card_from_order({"order_id": "artcode-1", "mall": "Yahoo!", "customer": "佐藤花子", "detail": ""},
                              [{"label": "氏名", "value": "佐藤花子（さとうはなこ）", "group": None}])
        self.assertEqual((c["氏名"], c["ふりがな"]), ("佐藤花子", "さとうはなこ"))
        self.assertEqual(c["注文者"], "")   # Yahoo! は注文者名を使わない

    def test_output_path(self):
        with tempfile.TemporaryDirectory() as d:
            card = {"注文番号": "297406-20261006-0833446491", "氏名": "山田 太郎", "注文者": "山田 花子"}
            p = M.output_path(card, d)
            self.assertEqual(os.path.basename(p), "297406-20261006-0833446491_山田太郎_山田花子.ai")
            open(p, "w").close()
            self.assertTrue(M.output_path(card, d).endswith("_山田花子_2.ai"))   # 同じ名前があれば _2
            # 氏名がなければ会社名、注文者がなければ付けない（Yahoo!）
            self.assertEqual(os.path.basename(M.output_path({"注文番号": "artcode-1", "会社名": "株式会社 A/B"}, d)),
                             "artcode-1_株式会社AB.ai")

    def test_address_without_city_split(self):
        c = M.card_from_order({"order_id": "1", "detail": ""}, [
            {"label": "氏名", "value": "A", "group": None},
            {"label": "住所", "group": "address",
             "value": "〒231-0001\n神奈川県横浜市中区新港1-1-1\n0451112222"}])
        self.assertEqual((c["住所1"], c["住所2"]), ("神奈川県横浜市中区新港1-1-1", ""))
        self.assertEqual(c["TEL"], "0451112222")
        self.assertIn("見出しのない電話番号", c["確認事項"])

    def test_write_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "job", "meishi_job.csv")
            card = dict(self.rakuten(), テンプレート="/T/business008.ai", 保存先="/O/x.ai")
            M.write_csv(path, [card])
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["氏名"], "山田 太郎")
            self.assertEqual(rows[0]["テンプレート"], "/T/business008.ai")
            self.assertEqual(list(rows[0].keys()), M.CSV_COLUMNS)

class JobScriptTests(unittest.TestCase):
    def test_write_job_is_ascii(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "job.txt")
            card = dict(self_card(), テンプレート="/Dropbox/1名刺表札作業用/business008.ai")
            M.write_job(path, [card, card])
            with open(path, "rb") as f:
                data = f.read()
            data.decode("ascii")                                   # 英数字だけ（化けない）
            lines = data.decode("ascii").split("\n")
            self.assertEqual(lines[0], "MEISHIJOB1")
            self.assertIn("%E3%83%86%E3%83%B3%E3%83%97%E3%83%AC%E3%83%BC%E3%83%88\t"   # テンプレート
                          "%2FDropbox%2F1%E5%90%8D%E5%88%BA", data.decode("ascii"))
            self.assertEqual(lines.count(""), 3)                   # 2件の区切り＋最後

    def test_embedded_script_is_ascii(self):
        self.assertTrue(all(ord(c) < 128 for c in M.JOB_JSX))

    def test_embedded_script_is_up_to_date(self):
        # .jsx を直したのに tools/bundle_jsx.py を実行し忘れていないか
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
        import bundle_jsx
        self.assertEqual(M.JOB_JSX, bundle_jsx.bundled_jsx(),
                         "meishi_export.py の埋め込みが古いです。python3 tools/bundle_jsx.py を実行してください")

    def test_install_job_script(self):
        with tempfile.TemporaryDirectory() as d:
            path = M.install_job_script(os.path.join(d, "x", "job.jsx"))
            with open(path, "rb") as f:
                data = f.read()
            self.assertTrue(data.startswith(b"\xef\xbb\xbf"))           # BOM 付き
            text = data.decode("utf-8-sig")
            self.assertIn("var MeishiCore", text)
            self.assertIn("var MeishiAI", text)
            self.assertNotIn('#include "', text)


if __name__ == "__main__":
    unittest.main()
