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


class CardFromOrderTests(unittest.TestCase):
    def rakuten(self):
        order = {"order_id": "297406-20261006-0833446491", "mall": "楽天",
                 "product": "お試し名刺40枚", "detail": RAKUTEN_DETAIL}
        return M.card_from_order(order, RAKUTEN_ITEMS)

    def test_rakuten_fields(self):
        c = self.rakuten()
        self.assertEqual(c["デザイン番号"], "business008")   # 例示の business001 ではない
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

    def test_repeat_order_without_design_number(self):
        detail = "作成するデザインの商品番号（例：business001など） ※40枚で作成します。以前と同じ"
        c = M.card_from_order({"order_id": "1", "detail": detail},
                              [{"label": "氏名", "value": "山田 太郎", "group": None}])
        self.assertEqual(c["デザイン番号"], "")
        self.assertIn("以前と同じ", c["確認事項"])

    def test_design_number_from_product_name(self):
        c = M.card_from_order({"order_id": "artcode-1", "mall": "Yahoo!",
                               "product": "名刺 100枚 abstract001", "detail": ""},
                              [{"label": "氏名", "value": "佐藤花子（さとうはなこ）", "group": None}])
        self.assertEqual(c["デザイン番号"], "abstract001")
        self.assertEqual((c["氏名"], c["ふりがな"]), ("佐藤花子", "さとうはなこ"))

    def test_address_without_city_split(self):
        c = M.card_from_order({"order_id": "1", "detail": "business008"}, [
            {"label": "氏名", "value": "A", "group": None},
            {"label": "住所", "group": "address",
             "value": "〒231-0001\n神奈川県横浜市中区新港1-1-1\n0451112222"}])
        self.assertEqual((c["住所1"], c["住所2"]), ("神奈川県横浜市中区新港1-1-1", ""))
        self.assertEqual(c["TEL"], "0451112222")
        self.assertIn("見出しのない電話番号", c["確認事項"])

    def test_write_csv_and_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            M.write_csv(path, [self.rakuten()])
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["氏名"], "山田 太郎")
            self.assertEqual(list(rows[0].keys()), M.CSV_COLUMNS)

            settings = os.path.join(d, "s", "settings.txt")
            os.makedirs(os.path.dirname(settings))
            with open(settings, "w", encoding="utf-8") as f:
                f.write("templates=/T\ncsv=/old.csv\n")
            M.set_csv_for_illustrator(path, settings)
            with open(settings, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("templates=/T\n", text)
            self.assertIn("csv=" + path + "\n", text)


if __name__ == "__main__":
    unittest.main()
