// meishi_ai.jsx を、Illustrator の代わりの「ニセの書類」で動かすテスト
//   node test/test_ai_mock.js
var assert = require("assert");
var fs = require("fs");
var path = require("path");
global.MeishiCore = require(path.join(__dirname, "..", "meishi_core.jsx"));
var C2 = global.MeishiCore;
var AI = eval(fs.readFileSync(path.join(__dirname, "..", "meishi_ai.jsx"), "utf8").replace(/^﻿/, "") + "; MeishiAI");

// ---- Illustrator の TextFrame / TextRange をまねた最小限のもの ----
function TextRange(frame, start) {
    this.frame = frame; this.start = start; this._len = 1;
    this.characterAttributes = { textFont: frame.fontAt ? frame.fontAt(start) : "Font" };
    this.paragraphAttributes = { justification: frame.justification || "left" };
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

// 本物の Illustrator と同じく、消したテキストに触ると「オブジェクトが無効です」になる
function TextFrame(contents, bounds, parent) {
    var self = this, _contents = contents, _bounds = bounds || [0, 0, 10, -10];
    function check() { if (self.removed) throw new Error("オブジェクトが無効です"); }
    this.removed = false;
    this.remove = function () {
        check();
        self.removed = true;
        var list = parent && parent.parent && parent.parent.textFrames;     // 書類のテキスト一覧からも消える
        if (list && list.indexOf(self) >= 0) list.splice(list.indexOf(self), 1);
    };
    Object.defineProperty(this, "contents", { get: function () { check(); return _contents; },
                                              set: function (v) { check(); _contents = v; } });
    Object.defineProperty(this, "geometricBounds", { get: function () { check(); return _bounds; } });
    this.typename = "TextFrame"; this.name = "";
    this.locked = false; this.parent = parent;
    this.characters = new Proxy({}, { get: function (_, k) { check(); return new TextRange(self, Number(k)); } });
}
function Item(type, bounds, doc) {
    this.typename = type; this.geometricBounds = bounds; this.locked = false; this.parent = doc.layer;
    this.remove = function () {
        var list = type === "RasterItem" ? doc.rasterItems : doc.placedItems;
        list.splice(list.indexOf(this), 1);
        doc.removed.push(this);
    };
}
global.TextOrientation = { VERTICAL: "vertical", HORIZONTAL: "horizontal" };
global.Justification = { CENTER: "center", RIGHT: "right", LEFT: "left" };
global.ElementPlacement = { PLACEBEFORE: "before" };

function makeDoc(texts) {
    var doc = { typename: "Document", rasterItems: [], placedItems: [], removed: [], added: [] };
    doc.layer = { typename: "Layer", locked: false, parent: doc };
    doc.textFrames = texts.map(function (t) { return new TextFrame(t[0], t[1], doc.layer); });
    doc.textFrames.add = function () {
        var t = { contents: "", width: 40, height: 6, position: null, orientation: "horizontal", movedBefore: null,
                  textRange: { characterAttributes: {} } };
        t.move = function (target) { t.movedBefore = target; };
        doc.added.push(t);
        return t;
    };
    // 「追加テキスト」レイヤー（足すテキストはここに入る）
    var layers = [];
    doc.layers = {
        getByName: function (n) {
            for (var i = 0; i < layers.length; i++) if (layers[i].name === n) return layers[i];
            throw new Error("no such layer");
        },
        add: function () {
            var l = { name: "", locked: false, visible: true, textFrames: { add: doc.textFrames.add } };
            layers.push(l); doc.addedLayers = layers; return l;
        }
    };
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
    assert.strictEqual(t[3], "東京都千代田区丸の内1-2-3\rTe l：03-1234-5678\rMobile：090-1111-2222\r" +
                             "E-mail：taro@example.co.jp\rhttps://example.co.jp/");
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

// 今回の不具合の再現：住所〜E-mail が1つのテキストで、未入力の行（Fax など）がある
var ADDRESS_BLOCK = "○○○県○○市○○町00-00-0\r\u3000\u3000\u3000\u3000\u3000  ○○○○○000号\r" +
    "Tel :0 0 0 - 0 0 0 - 0 0 0 0\rFax :0 0 0 - 0 0 0 - 0 0 0 0\rMobile: 0 0 0 - 0 0 0 0 - 0 0 0 0\r" +
    "E-mail : ooooo@oooo.com";
var HASHIMOTO = { "会社名": "インテリア\u3000ハシモト", "氏名": "五関 北斗", "郵便番号": "272-0811",
                  "住所1": "千葉県市川市北方町1-2-3", "TEL": "047-123-4567" };

test("住所〜E-mail のテキスト: 未入力の Fax・Mobile・E-mail・住所2 の行を消す", function () {
    var doc = makeDoc([["〒000-0000", [0, 0, 10, -10]], [ADDRESS_BLOCK, [0, 0, 10, -10]]]);
    AI.editDocument(doc, HASHIMOTO, []);
    assert.strictEqual(doc.textFrames[0].contents, "〒272-0811");
    assert.strictEqual(doc.textFrames[1].contents, "千葉県市川市北方町1-2-3\rTel：047-123-4567");
});

test("未入力で空になったテキスト（肩書の枠など）はテキストごと消す", function () {
    var doc = makeDoc([["店\u3000長", [0, 0, 10, -10]], ["鈴\u3000木\u3000花\u3000子", [0, 0, 10, -10]]]);
    var title = doc.textFrames[0], name = doc.textFrames[1];
    AI.editDocument(doc, HASHIMOTO, []);
    assert.ok(title.removed);
    assert.ok(!name.removed);
    assert.strictEqual(name.contents, "五\u3000関\u3000北\u3000斗");
});

test("Illustrator が改行をまたぐ削除でエラーを出しても、中身ごと入れ直して置き換える", function () {
    var doc = makeDoc([[ADDRESS_BLOCK, [0, 0, 10, -10]]]);
    var tf = doc.textFrames[0];
    var real = tf.characters;
    tf.characters = new Proxy({}, { get: function (_, k) {
        var r = real[k];
        var orig = r.remove;
        r.remove = function () {
            if (/\r/.test(this.contents)) throw new Error("an Illustrator error occurred");
            orig.call(this);
        };
        return r;
    } });
    var w = [];
    AI.editDocument(doc, HASHIMOTO, w);
    assert.strictEqual(tf.contents, "千葉県市川市北方町1-2-3\rTel：047-123-4567");
    assert.ok(w.join("\n").indexOf("書式が一部くずれた") >= 0);
});

test("備考: 中心から5cm下に 7pt・MSゴシック・中央揃えで入れる", function () {
    var doc = makeDoc([["鈴\u3000木\u3000花\u3000子", [0, 0, 10, -10]]]);
    var added = [];
    doc.artboards = [{ artboardRect: [0, 858.9, 612.3, 0] }];
    doc.artboards.getActiveArtboardIndex = function () { return 0; };
    doc.layers = { add: function () {
        var layer = { name: "", textFrames: { add: function () {
            var t = { contents: "", width: 100, position: null,
                      textRange: { characterAttributes: {}, paragraphAttributes: {} } };
            added.push(t); return t;
        } } };
        return layer;
    } };
    global.app = { textFonts: { getByName: function (n) { if (n === "MS-Gothic") return "MSG"; throw new Error("no"); } } };
    var w = [];
    AI.editDocument(doc, { "氏名": "山田 太郎", "備考": "裏面は無しで\nお願いします" }, w);
    assert.strictEqual(added.length, 1);
    var t = added[0];
    assert.strictEqual(t.contents, "裏面は無しで\rお願いします");
    assert.strictEqual(t.textRange.characterAttributes.size, 7);
    assert.strictEqual(t.textRange.characterAttributes.textFont, "MSG");
    assert.strictEqual(t.textRange.paragraphAttributes.justification, "center");
    var cx = 612.3 / 2, cy = 858.9 / 2;
    assert.ok(Math.abs(t.position[0] - (cx - 50)) < 0.01);
    assert.ok(Math.abs(t.position[1] - (cy - 50 * 72 / 25.4)) < 0.01);   // 5cm = 141.73pt
    assert.ok(w.join("\n").indexOf("備考を名刺の下") >= 0);
});

test("備考: お店の案内文だけなら何も入れない", function () {
    var doc = makeDoc([["鈴\u3000木\u3000花\u3000子", [0, 0, 10, -10]]]);
    var added = 0;
    doc.layers = { add: function () { added++; return { textFrames: { add: function () { return {}; } } }; } };
    var w = [];
    AI.editDocument(doc, { "氏名": "山田 太郎", "備考": "【不明点など確認時のご連絡先 電話番号やアドレス】\n\n" +
        "★商品ページで入力できなかった項目やご要望等ございましたら、こちらにご入力下さい。\n\n------------" }, w);
    assert.strictEqual(added, 0);
    assert.ok(w.join("\n").indexOf("備考") < 0);
});

test("ふりがな: 氏名の上に、氏名と同じフォントで 5pt・中央そろえ", function () {
    var doc = makeDoc([["代表取締役鈴\u3000木\u3000太\u3000郎", [229, -400, 330, -410]]]);
    var nameFrame = doc.textFrames[0];
    nameFrame.fontAt = function (i) { return i >= 5 ? "RyuminPr5-Regular(氏名)" : "Ryumin(肩書)"; };
    var w = [];
    AI.editDocument(doc, { "肩書": "部長", "氏名": "山田 太郎", "ふりがな": "やまだ たろう" }, w);
    var f = doc.added[0];
    assert.strictEqual(f.contents, "やまだ たろう");
    assert.strictEqual(f.textRange.characterAttributes.size, 5);
    assert.strictEqual(f.textRange.characterAttributes.textFont, "RyuminPr5-Regular(氏名)");
    assert.deepStrictEqual(f.position, [(229 + 330) / 2 - 20, -400 + 1 + 6]);   // 中央・1pt 上
    assert.strictEqual(doc.addedLayers[0].name, "追加テキスト");           // 専用のレイヤーに入る
    assert.ok(w.join("\n").indexOf("差し込み先がない") < 0, w.join("\n"));
});

test("部署名: 肩書の上に、肩書と同じフォントで 8pt（肩書のそろえ方に合わせる）", function () {
    var doc = makeDoc([["店\u3000長", [264, -381, 290, -389]], ["鈴\u3000木\u3000花\u3000子", [264, -388, 348, -405]]]);
    doc.textFrames[0].fontAt = function () { return "肩書のフォント"; };
    doc.textFrames[0].justification = "right";
    var w = [];
    AI.editDocument(doc, { "部署": "営業部", "肩書": "部長", "氏名": "山田 太郎" }, w);
    var d = doc.added[0];
    assert.strictEqual(d.contents, "営業部");
    assert.strictEqual(d.textRange.characterAttributes.size, 8);
    assert.strictEqual(d.textRange.characterAttributes.textFont, "肩書のフォント");
    assert.deepStrictEqual(d.position, [290 - 40, -381 + 1 + 6]);   // 右そろえ・肩書の 1pt 上
    assert.strictEqual(doc.textFrames[0].contents, "部\u3000長");   // 肩書には部署を混ぜない
});

test("部署名: 肩書が空なら、肩書があった場所に肩書のフォントで入れる", function () {
    var doc = makeDoc([["店\u3000長", [264, -381, 290, -389]], ["鈴\u3000木\u3000花\u3000子", [264, -388, 348, -405]]]);
    doc.textFrames[0].fontAt = function () { return "肩書のフォント"; };
    var title = doc.textFrames[0];
    var w = [];
    AI.editDocument(doc, { "部署": "営業部", "氏名": "山田 太郎" }, w);
    assert.ok(title.removed);                     // 空になった肩書は消える
    assert.strictEqual(doc.added[0].textRange.characterAttributes.textFont, "肩書のフォント");
    assert.deepStrictEqual(doc.added[0].position, [264, -381]);
    assert.ok(w.join("\n").indexOf("肩書の場所に") >= 0);
});

test("部署名: 肩書の場所がないデザインは氏名の上", function () {
    var doc = makeDoc([["鈴\u3000木\u3000花\u3000子", [264, -388, 348, -405]]]);
    doc.textFrames[0].fontAt = function () { return "氏名のフォント"; };
    AI.editDocument(doc, { "部署": "営業部", "氏名": "山田 太郎" }, []);
    assert.strictEqual(doc.added[0].textRange.characterAttributes.textFont, "氏名のフォント");
    assert.deepStrictEqual(doc.added[0].position, [264, -388 + 1 + 6]);
});

test("縦書きの氏名: ふりがなは右どなりに縦書きで", function () {
    var doc = makeDoc([["鈴木\r\u3000花子", [300, -400, 310, -480]]]);
    doc.textFrames[0].orientation = "vertical";
    AI.editDocument(doc, { "氏名": "山田 太郎", "ふりがな": "やまだ たろう" }, []);
    assert.strictEqual(doc.textFrames[0].contents, "山田\r\u3000太郎");
    assert.strictEqual(doc.added[0].orientation, "vertical");
    assert.deepStrictEqual(doc.added[0].position, [311, -400]);
});

test("コロン: 見出しと値が別テキストなら1つにまとめて「E-mail：アドレス」に", function () {
    var doc = makeDoc([["E-mail", [312.8, -478.9, 332.0, -485.9]], ["  : ooooo@oooo.com", [325.5, -478.9, 399.7, -485.9]],
                       ["Tel : 000-000-0000", [312.8, -470, 380, -477]], ["URL", [312.8, -490, 330, -497]],
                       ["  : http://www.0123456.jp/", [325.5, -490, 400, -497]]]);
    var f = doc.textFrames.slice(0), valueFrame = f[1];
    AI.editDocument(doc, { "メール": "taro@example.co.jp", "TEL": "03-1234-5678", "URL": "https://example.co.jp/" }, []);
    assert.strictEqual(f[0].contents, "E-mail：taro@example.co.jp");
    assert.ok(valueFrame.removed);
    assert.strictEqual(f[2].contents, "Tel：03-1234-5678");
    assert.strictEqual(f[3].contents, "URL");                        // URL はまとめない・そのまま
    assert.strictEqual(f[4].contents, "  : https://example.co.jp/");
});

test("コロン: メールが未入力なら見出しも値も消える", function () {
    var doc = makeDoc([["E-mail", [312.8, -478.9, 332.0, -485.9]], ["  : ooooo@oooo.com", [325.5, -478.9, 399.7, -485.9]]]);
    var label = doc.textFrames[0], value = doc.textFrames[1];
    AI.editDocument(doc, { "氏名": "山田 太郎" }, []);
    assert.ok(label.removed && value.removed);
});

function withArtboard(doc) {
    doc.artboards = [{ artboardRect: [0, 858.9, 612.3, 0] }];
    doc.artboards.getActiveArtboardIndex = function () { return 0; };
    return doc;
}

test("部署名: 肩書も氏名も場所がなければ会社名の下", function () {
    var doc = makeDoc([["LOGO", [228, -368, 291, -393]]]);
    doc.textFrames[0].fontAt = function () { return "会社名のフォント"; };
    var w = [];
    AI.editDocument(doc, { "会社名": "株式会社サンプル", "ロゴデータ": "無し", "部署": "営業部" }, w);
    var d = doc.added[0];
    assert.strictEqual(d.contents, "営業部");
    assert.strictEqual(d.textRange.characterAttributes.size, 8);
    assert.deepStrictEqual(d.position, [228, -393 - 1]);         // 会社名の 1pt 下・左そろえ
    assert.ok(w.join("\n").indexOf("会社名の下") >= 0);
});

test("置き場所がない項目（ふりがな・部署名・テンプレートにない項目・自由記入）は中心から5cm上にまとめて", function () {
    var doc = withArtboard(makeDoc([["Tel : 000-000-0000", [0, 0, 10, -10]]]));
    var w = [];
    AI.editDocument(doc, { "部署": "営業部", "ふりがな": "やまだ", "TEL": "03-1", "FAX": "03-2",
                           "会社名": "株式会社A", "自由行": "一級建築士 / 宅建士" }, w);
    var cx = 612.3 / 2, cy = 858.9 / 2, up = 50 * 72 / 25.4;
    assert.strictEqual(doc.added.length, 1);                                 // 1つにまとめる（重ならない）
    var t = doc.added[0];
    assert.strictEqual(t.contents, "やまだ\r営業部\r株式会社A\rFAX：03-2\r一級建築士\r宅建士");
    assert.strictEqual(t.textRange.characterAttributes.size, 8);
    assert.strictEqual(t.textRange.characterAttributes.textFont, undefined);  // デフォルトのフォント
    assert.ok(Math.abs(t.position[0] - (cx - 20)) < 0.01);
    assert.ok(Math.abs(t.position[1] - (cy + up)) < 0.01);
    assert.ok(w.join("\n").indexOf("中心から5cm上") >= 0);
});

test("部署名: 肩書の上に入れられない（エラー）ときは次の場所、だめなら中心から5cm上", function () {
    var doc = withArtboard(makeDoc([["店\u3000長", [264, -381, 290, -389]], ["鈴\u3000木\u3000花\u3000子", [264, -388, 348, -405]]]));
    var calls = 0, realAdd = doc.textFrames.add;
    doc.textFrames.add = function () { calls++; if (calls <= 2) throw new Error("Target layer cannot be modified"); return realAdd(); };
    var w = [];
    AI.editDocument(doc, { "部署": "営業部", "肩書": "部長", "氏名": "山田 太郎" }, w);
    assert.strictEqual(doc.added.length, 1);
    assert.strictEqual(doc.added[0].contents, "営業部");
    assert.ok(w.join("\n").indexOf("中心から5cm上") >= 0, w.join("\n"));
});

test("コロン: 「Mobile」と「E-mail」が2行のテキストで、アドレスが別テキストに重なっているデザイン", function () {
    // スクリーンショットのテンプレート：2行のテキスト（Mobile / E-mail）＋ 2行目に重ねたアドレスのテキスト
    var doc = makeDoc([["Mobile:000-0000-0000\rE-mail", [47, -20, 690, -130]],
                       ["  : ooooo@oooo.com", [150, -80, 930, -130]]]);
    var block = doc.textFrames[0], value = doc.textFrames[1];
    AI.editDocument(doc, { "携帯": "090-9085-8613", "メール": "xxx3r.m.k0211@gmail.com" }, []);
    assert.strictEqual(block.contents, "Mobile：090-9085-8613\rE-mail：xxx3r.m.k0211@gmail.com");
    assert.ok(value.removed);
});

test("コロン: 1行目の見出しに、別テキストの値を合わせない（高さが違う）", function () {
    var doc = makeDoc([["E-mail\rMobile:000-0000-0000", [47, -20, 690, -130]],
                       ["  : ooooo@oooo.com", [150, -80, 930, -130]]]);
    AI.editDocument(doc, { "携帯": "090-1", "メール": "a@b.jp" }, []);
    assert.strictEqual(doc.textFrames[1].contents, "  : a@b.jp");                // 2行目の高さなので1行目の E-mail とはつながない
});

test("コロン: 詰めてあった文字間隔（カーニング・トラッキング）を「E」と同じに戻す", function () {
    // business006 など：「E-mail  : ooooo」の空白にマイナスの間隔を付けてコロンを寄せている
    var before = "Mobile: 000-0000-0000\rE-mail  : ooooo@oooo.com";
    var plan = C2.planEdits(before, { "携帯": "090-9085-8613", "メール": "xxx3r.m.k0211@gmail.com" });
    var after = C2.applyEditsToString(before, plan.edits);
    assert.strictEqual(after, "Mobile：090-9085-8613\rE-mail：xxx3r.m.k0211@gmail.com");
    // 置き換えたあとの文字（間隔の情報つき）
    var chars = [];
    for (var i = 0; i < after.length; i++) chars.push({ c: after.charAt(i), contents: after.charAt(i), kerning: -600, characterAttributes: { tracking: -300 } });
    var eIndex = after.indexOf("E-mail");
    chars[0].characterAttributes.tracking = 20;          // 「M」の間隔
    chars[eIndex].characterAttributes.tracking = 10;     // 「E」の間隔
    AI.fixSpacing({ characters: chars }, plan.edits);
    var colon = after.indexOf("：", eIndex);
    for (var j = colon - 1; j < after.length; j++) {      // 「l」から行の最後まで
        assert.strictEqual(chars[j].kerning, 0, "kerning " + j);
        assert.strictEqual(chars[j].characterAttributes.tracking, 10, "tracking " + j);
    }
    var mColon = after.indexOf("：");
    assert.strictEqual(chars[mColon].characterAttributes.tracking, 20);   // Mobile の行は「M」に合わせる
    assert.strictEqual(chars[eIndex + 1].kerning, -600);                 // 見出しの途中は触らない
    assert.strictEqual(chars[eIndex - 1].c, "\r");
    assert.strictEqual(chars[eIndex - 1].kerning, 0);                   // E の前の改行文字の間隔も 0 に
    assert.strictEqual(chars[eIndex].kerning, 0);
});

test("会社名は 13pt（LOGO・株式会社／〇〇商事の2行・英字の会社名）", function () {
    function sizes(before, rec) {
        var plan = C2.planEdits(before, rec);
        var after = C2.applyEditsToString(before, plan.edits);
        var chars = [];
        for (var i = 0; i < after.length; i++) chars.push({ c: after.charAt(i), characterAttributes: { size: 7 } });
        AI.applyFieldSizes({ characters: chars }, plan.edits);
        return after + " " + chars.map(function (c) { return c.characterAttributes.size; }).join(",");
    }
    assert.strictEqual(sizes("LOGO", { "会社名": "株式会社A", "ロゴデータ": "無し" }), "株式会社A 13,13,13,13,13");
    assert.strictEqual(sizes("株式会社\r\u3000〇〇〇〇商事", { "会社名": "株式会社AB", "ロゴデータ": "無し" }),
                       "株式会社\r\u3000AB 13,13,13,13,7,7,13,13");          // 改行・字下げはそのまま
    assert.strictEqual(sizes("Tel : 000-000-0000\rLOGO", { "会社名": "A", "TEL": "03-1" }),
                       "Tel：03-1\rA 7,7,7,7,7,7,7,7,7,13");                    // ほかの項目は変えない
    assert.strictEqual(sizes("artcode", { "会社名": "A社", "会社名英字": "A Inc." }), "A Inc. 13,13,13,13,13,13");
});

console.log(failures === 0 ? "\nすべて成功" : "\n失敗: " + failures + " 件");
process.exit(failures === 0 ? 0 : 1);
