// meishi_ai.jsx を、Illustrator の代わりの「ニセの書類」で動かすテスト
//   node test/test_ai_mock.js
var assert = require("assert");
var fs = require("fs");
var path = require("path");
global.MeishiCore = require(path.join(__dirname, "..", "meishi_core.jsx"));
var AI = eval(fs.readFileSync(path.join(__dirname, "..", "meishi_ai.jsx"), "utf8").replace(/^﻿/, "") + "; MeishiAI");

// ---- Illustrator の TextFrame / TextRange をまねた最小限のもの ----
function TextRange(frame, start) {
    this.frame = frame; this.start = start; this._len = 1;
}
Object.defineProperty(TextRange.prototype, "length", {
    get: function () { return this._len; }, set: function (v) { this._len = v; }
});
Object.defineProperty(TextRange.prototype, "contents", {
    get: function () { return this.frame.contents.substr(this.start, this._len); },
    set: function (v) {
        var c = this.frame.contents;
        this.frame.contents = c.substring(0, this.start) + v + c.substring(this.start + this._len);
    }
});
TextRange.prototype.remove = function () { this.contents = ""; };

function TextFrame(contents, bounds, parent) {
    var self = this;
    this.typename = "TextFrame"; this.contents = contents; this.name = "";
    this.locked = false; this.geometricBounds = bounds || [0, 0, 10, -10]; this.parent = parent;
    this.characters = new Proxy({}, { get: function (_, k) { return new TextRange(self, Number(k)); } });
}
function Item(type, bounds, doc) {
    this.typename = type; this.geometricBounds = bounds; this.locked = false; this.parent = doc.layer;
    this.remove = function () {
        var list = type === "RasterItem" ? doc.rasterItems : doc.placedItems;
        list.splice(list.indexOf(this), 1);
        doc.removed.push(this);
    };
}
function makeDoc(texts) {
    var doc = { typename: "Document", rasterItems: [], placedItems: [], removed: [] };
    doc.layer = { typename: "Layer", locked: false, parent: doc };
    doc.textFrames = texts.map(function (t) { return new TextFrame(t[0], t[1], doc.layer); });
    return doc;
}

var failures = 0;
function test(name, fn) {
    try { fn(); console.log("ok   " + name); }
    catch (e) { failures++; console.log("FAIL " + name + "\n     " + e.stack); }
}

var REC = {
    "会社名": "株式会社サンプル", "ロゴデータ": "無し", "肩書": "部長", "氏名": "山田 太郎",
    "郵便番号": "100-0005", "住所1": "東京都千代田区丸の内1-2-3", "住所2": "",
    "TEL": "03-1234-5678", "FAX": "", "携帯": "090-1111-2222",
    "メール": "taro@example.co.jp", "URL": "https://example.co.jp/"
};

function business008() {
    var doc = makeDoc([
        ["LOGO", [228, -368, 291, -393]],
        ["代表取締役鈴　木　太　郎", [229, -400, 330, -410]],
        ["〒000-0000", [277, -442, 300, -448]],
        ["○○○県○○市○○町00-00-0\r○○○○○000号\rTe l : 000-000-0000\rFax : 000-000-0000\r" +
         "Mobile: 000-0000-0000\rE-mail\t: ooooo@oooo.com\rhttp://www.0123456.jp/", [313, -442, 400, -490]]
    ]);
    doc.rasterItems.push(new Item("RasterItem", [197, -369, 224, -393], doc));   // LOGO 横のマーク
    doc.rasterItems.push(new Item("RasterItem", [196, -443, 252, -499], doc));   // QRコード
    return doc;
}

test("business008: 流し込みとLOGO横のマーク削除", function () {
    var doc = business008(), w = [];
    AI.editDocument(doc, REC, w);
    var t = doc.textFrames.map(function (f) { return f.contents; });
    assert.strictEqual(t[0], "株式会社サンプル");
    assert.strictEqual(t[1], "部長山　田　太　郎");
    assert.strictEqual(t[2], "〒100-0005");
    assert.strictEqual(t[3], "東京都千代田区丸の内1-2-3\rTe l : 03-1234-5678\rMobile: 090-1111-2222\r" +
                             "E-mail\t: taro@example.co.jp\rhttps://example.co.jp/");
    assert.strictEqual(doc.removed.length, 1);                      // マークだけ消える
    assert.deepStrictEqual(doc.rasterItems[0].geometricBounds, [196, -443, 252, -499]);   // QRは残る
    assert.ok(w.join("\n").indexOf("マークを 1 個消しました") >= 0, w.join("\n"));
    assert.ok(w.join("\n").indexOf("文字の書式") < 0, w.join("\n"));
});

test("ロゴデータ有り: LOGO もマークもそのまま", function () {
    var doc = business008(), w = [];
    var rec = {}; for (var k in REC) rec[k] = REC[k];
    rec["ロゴデータ"] = "有り";
    AI.editDocument(doc, rec, w);
    assert.strictEqual(doc.textFrames[0].contents, "LOGO");
    assert.strictEqual(doc.removed.length, 0);
    assert.ok(w.join("\n").indexOf("ロゴを配置") >= 0);
});

test("ロックされたテキストも書き換えて、ロックを戻す", function () {
    var doc = business008();
    doc.textFrames[2].locked = true; doc.layer.locked = true;
    AI.editDocument(doc, REC, []);
    assert.strictEqual(doc.textFrames[2].contents, "〒100-0005");
    assert.ok(doc.textFrames[2].locked && doc.layer.locked);
});

console.log(failures === 0 ? "\nすべて成功" : "\n失敗: " + failures + " 件");
process.exit(failures === 0 ? 0 : 1);
