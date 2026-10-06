// meishi_core.jsx のテスト（Illustrator がなくても動きます）
//   実行方法:  node meishi-app/test/test_core.js
// テンプレートの文字は、いただいたサンプル（business008 / abstract001 / 裏面B）から取り出したものです。

var assert = require("assert");
var path = require("path");
var C = require(path.join(__dirname, "..", "meishi_core.jsx"));

var failures = 0;
function test(name, fn) {
    try { fn(); console.log("ok   " + name); }
    catch (e) { failures++; console.log("FAIL " + name + "\n     " + e.message); }
}
function run(contents, rec) {
    var plan = C.planEdits(contents, rec);
    return { text: C.applyEditsToString(contents, plan.edits), used: plan.used };
}

var FULL = {
    "注文番号": "123456-20261006-0000000001",
    "デザイン番号": "business008",
    "肩書": "営業部長",
    "氏名": "山田 花子",
    "郵便番号": "123-4567",
    "住所1": "東京都千代田区丸の内1-2-3",
    "住所2": "サンプルビル5F",
    "TEL": "03-1234-5678",
    "FAX": "03-1234-5679",
    "携帯": "090-1111-2222",
    "メール": "hanako@example.co.jp",
    "URL": "https://example.co.jp/"
};

// ---- business008 -----------------------------------------------------
test("business008: 肩書と1文字ずつ空けた氏名", function () {
    var r = run("代表取締役鈴\u3000木\u3000太\u3000郎", FULL);
    assert.strictEqual(r.text, "営業部長山\u3000田\u3000花\u3000子");
});

test("business008: 郵便番号（〒は残す）", function () {
    assert.strictEqual(run("〒000-0000", FULL).text, "〒123-4567");
});

var B008 = "○○○県○○市○○町00-00-0\r○○○○○000号\rTe l : 000-000-0000\rFax : 000-000-0000\r" +
           "Mobile: 000-0000-0000\rE-mail\t: ooooo@oooo.com\rhttp://www.0123456.jp/";

test("business008: 住所・電話・メール・URL", function () {
    var r = run(B008, FULL);
    assert.strictEqual(r.text,
        "東京都千代田区丸の内1-2-3\rサンプルビル5F\rTe l : 03-1234-5678\rFax : 03-1234-5679\r" +
        "Mobile: 090-1111-2222\rE-mail\t: hanako@example.co.jp\rhttps://example.co.jp/");
    assert.ok(!C.hasLeftover(r.text));
});

test("business008: 空欄の項目は行ごと消える（FAX・住所2・URL）", function () {
    var rec = {};
    for (var k in FULL) rec[k] = FULL[k];
    rec["FAX"] = ""; rec["住所2"] = ""; rec["URL"] = "";
    var r = run(B008, rec);
    assert.strictEqual(r.text,
        "東京都千代田区丸の内1-2-3\rTe l : 03-1234-5678\r" +
        "Mobile: 090-1111-2222\rE-mail\t: hanako@example.co.jp");
});

// ---- abstract001 -----------------------------------------------------
test("abstract001: 字下げされた住所2の前の空白は残す", function () {
    var r = run("〒000-0000\r○○○県○○市○○町00-00-0\r\u3000\u3000\u3000\u3000\u3000  ○○○○○000号", FULL);
    assert.strictEqual(r.text, "〒123-4567\r東京都千代田区丸の内1-2-3\r\u3000\u3000\u3000\u3000\u3000  サンプルビル5F");
});

test("abstract001: E-mail の値が別の行にあっても置き換わる", function () {
    var r = run("E-mail\r  : ooooo@oooo.com\rURL : http://www.0123456.jp/", FULL);
    assert.strictEqual(r.text, "E-mail\r  : hanako@example.co.jp\rURL : https://example.co.jp/");
});

// ---- 裏面B（英語） ---------------------------------------------------
var BACK_B = "6-1-1-3 Hirasaku,Yokosuka city,\rKanagawa 238-0032,Japan\r" +
             "Tel:046-874-4234 Fax:020-4669-2749\rMobile:000-0000-0000\rE-mail:shop@artcode.jp";
var EN = {
    "注文番号": "artcode-10000123", "氏名英字": "Hanako Yamada", "肩書英字": "Sales Manager",
    "会社名英字": "Example Inc.", "英字住所1": "1-2-3 Marunouchi, Chiyoda-ku,",
    "英字住所2": "Tokyo 100-0005, Japan", "TEL": "+81-3-1234-5678", "FAX": "", "携帯": "",
    "メール": "hanako@example.co.jp"
};

test("裏面B: 英字住所と、1行に2つある Tel/Fax（Fax は空欄なので消える）", function () {
    var r = run(BACK_B, EN);
    assert.strictEqual(r.text,
        "1-2-3 Marunouchi, Chiyoda-ku,\rTokyo 100-0005, Japan\rTel:+81-3-1234-5678\rE-mail:hanako@example.co.jp");
});

test("裏面B: 社名・肩書・氏名（その行だけの文字）", function () {
    assert.strictEqual(run("artcode", EN).text, "Example Inc.");
    assert.strictEqual(run("President", EN).text, "Sales Manager");
    assert.strictEqual(run("Ichiro Suzuki", EN).text, "Hanako Yamada");
    // shop@artcode.jp の中の artcode は社名として置き換えない
    assert.strictEqual(run("E-mail:shop@artcode.jp", EN).text, "E-mail:hanako@example.co.jp");
});

test("文字の間に空白が入っていても見出しを見つける（T e l :）", function () {
    assert.strictEqual(run("T e l : 0 4 6 - 8 7 4 - 4 2 3 4", EN).text, "T e l : +81-3-1234-5678");
});

// ---- 裏面A（業務内容）は差し込み先がないので何も変えない -------------
test("裏面A: 業務内容のテキストは変えない", function () {
    var a = "業務内容\rWEBデザイン・グラフィックデザイン\r映像編集・３DCG・写真撮影";
    assert.strictEqual(run(a, FULL).text, a);
});

// ---- LOGO（ロゴデータ無しなら会社名が入る） ---------------------------
test("LOGO: ロゴデータ無しなら会社名に置き換わる", function () {
    var r = run("LOGO", { "会社名": "株式会社サンプル", "ロゴデータ": "無し" });
    assert.strictEqual(r.text, "株式会社サンプル");
});

test("LOGO: ロゴデータ有りならそのまま（差し込み先なしの警告も出さない）", function () {
    var rec = { "会社名": "株式会社サンプル", "ロゴデータ": "有り" };
    var plan = C.planEdits("LOGO", rec);
    assert.strictEqual(C.applyEditsToString("LOGO", plan.edits), "LOGO");
    assert.deepStrictEqual(C.unusedFields(rec, plan.used), []);
});

test("名刺に入れない項目（備考・自由行など）は差し込み先なしの警告に出さない", function () {
    var rec = { "氏名": "山田太郎", "備考": "急ぎ", "自由行": "一級建築士", "ふりがな": "やまだ", "モール": "楽天" };
    var plan = C.planEdits("鈴木太郎", rec);
    assert.deepStrictEqual(C.unusedFields(rec, plan.used), []);
});

// ---- LOGO 横のマーク（meishi_ai.jsx） --------------------------------
global.MeishiCore = C;
var fs = require("fs");
var AI = eval(fs.readFileSync(path.join(__dirname, "..", "meishi_ai.jsx"), "utf8").replace(/^\uFEFF/, "") + "; MeishiAI");
// Illustrator の座標は [左, 上, 右, 下]（上が大きい）。business008 の実寸から
var LOGO_B = [228, -368, 291, -393];
test("LOGO マーク: business008 の左隣の画像は消す対象", function () {
    assert.ok(AI.isNextToLogo([197, -369, 224, -393], LOGO_B));
});
test("LOGO マーク: 候補が複数・背景の絵に重なる画像は消さない", function () {
    var mark = [197, -369, 224, -393];
    assert.deepStrictEqual(AI.pickMarks([mark, [196, -443, 252, -499]], LOGO_B), [0]);   // マークだけ選ぶ
    var info = {};
    assert.deepStrictEqual(AI.pickMarks([mark, [295, -369, 320, -393]], LOGO_B, info), []); // 左右に2つ → 消さない
    assert.ok(info.ambiguous);
    assert.deepStrictEqual(AI.pickMarks([mark, [150, -300, 400, -450]], LOGO_B), []);       // 背景の絵に重なる
});

test("LOGO マーク: 遠いもの・大きい背景・QRコードは消さない", function () {
    assert.ok(!AI.isNextToLogo([196, -443, 252, -499], LOGO_B));   // QRコード
    assert.ok(!AI.isNextToLogo([0, 0, 260, -560], LOGO_B));         // 名刺全体の背景
    assert.ok(!AI.isNextToLogo([100, -368, 130, -393], LOGO_B));    // 離れている
});

// ---- 見出しだけのテキスト（E-mail の値が別テキストのデザイン 372 個） ----
test("見出しだけ: 値が空なら消す、値があれば残す", function () {
    assert.strictEqual(run("E-mail", { "メール": "" }).text, "");
    assert.strictEqual(run("E-mail", { "メール": "a@b.jp" }).text, "E-mail");
    assert.strictEqual(run("〒", { "郵便番号": "" }).text, "");
    assert.strictEqual(run("  : ooooo@ oooo. com", { "メール": "a@b.jp" }).text, "  : a@b.jp");
    assert.strictEqual(run("  : ooooo@ oooo. com", { "メール": "" }).text, "");
});

test("増やした仮の文字: ROGO・店長・2行の住所・縦書きの電話・株式会社の分割", function () {
    var rec = { "会社名": "有限会社テスト", "ロゴデータ": "無し", "肩書": "部長", "住所1": "東京都港区1-2-3",
                "住所2": "ABCビル2F", "TEL": "03-1111-2222", "FAX": "" };
    assert.strictEqual(run("ROGO", rec).text, "有限会社テスト");
    assert.strictEqual(run("店\u3000長", rec).text, "部\u3000長");
    assert.strictEqual(run("○○○県○○市○○町\r00-00-0○○○○000号", rec).text, "東京都港区1-2-3\rABCビル2F");
    assert.strictEqual(run("電\u3000話\u3000〇〇〇ー〇〇〇ー〇〇〇〇\rFAX\u3000〇〇〇ー〇〇〇ー〇〇〇〇", rec).text,
                       "電\u3000話\u300003-1111-2222");
    assert.strictEqual(run("株式会社\r〇〇商事", rec).text, "有限会社\rテスト");
    assert.strictEqual(run("TEL 000-000-0000", rec).text, "TEL 03-1111-2222");
    assert.strictEqual(run("Web デザイン", rec).text, "Web デザイン");   // 見出しに見えても値でなければ触らない
});

// ---- 注文通知アプリからの指示ファイル --------------------------------
test("指示ファイル: パーセント表記を元に戻す・空行で次の注文", function () {
    var text = "MEISHIJOB1\n" +
        encodeURIComponent("注文番号") + "\t1\n" +
        encodeURIComponent("テンプレート") + "\t" + encodeURIComponent("/Dropbox/名刺/business008.ai") + "\n" +
        encodeURIComponent("会社名") + "\t" + encodeURIComponent("A&B, \"テスト\"\t%") + "\n\n" +
        encodeURIComponent("注文番号") + "\t2\n";
    var r = C.parseJob(text);
    assert.strictEqual(r.length, 2);
    assert.strictEqual(r[0]["テンプレート"], "/Dropbox/名刺/business008.ai");
    assert.strictEqual(r[0]["会社名"], "A&B, \"テスト\"\t%");
    assert.strictEqual(r[1]["注文番号"], "2");
    assert.strictEqual(C.parseJob("注文番号,氏名\n1,a"), null);   // 古い形は読まない
});

// ---- その他 ---------------------------------------------------------
test("部署は肩書の前に付く", function () {
    var r = run("代表取締役", { "部署": "営業部", "肩書": "部長" });
    assert.strictEqual(r.text, "営業部\u3000部長");
});

test("差し込み先がない項目を見つける", function () {
    var plan = C.planEdits("〒000-0000", FULL);
    var unused = C.unusedFields(FULL, plan.used);
    assert.ok(unused.indexOf("氏名") >= 0 && unused.indexOf("郵便番号") < 0);
});

test("CSV: 見出しの別名・引用符・BOM・空行", function () {
    var csv = "\uFEFF受注番号,デザイン番号,お名前,電話番号,住所,謎の列\r\n" +
              "\"111-222\",business008,\"山田 太郎\",03-0000-1111,\"東京都, 港区\",x\r\n\r\n";
    var res = C.rowsToRecords(C.parseCSV(csv));
    assert.strictEqual(res.records.length, 1);
    assert.strictEqual(res.records[0]["注文番号"], "111-222");
    assert.strictEqual(res.records[0]["氏名"], "山田 太郎");
    assert.strictEqual(res.records[0]["住所1"], "東京都, 港区");
    assert.deepStrictEqual(res.unknownHeaders, ["謎の列"]);
});

test("ファイル名は 注文番号_名前.ai（空白や使えない文字は除く）", function () {
    assert.strictEqual(C.makeFileName({ "注文番号": "123/45", "氏名": "山田 太郎" }), "12345_山田太郎.ai");
    assert.strictEqual(C.makeFileName({ "注文番号": "9", "氏名英字": "Taro Yamada" }), "9_TaroYamada.ai");
});

test("文字コードの判定", function () {
    var utf8 = Buffer.from("注文番号", "utf8").toString("latin1");
    var sjis = String.fromCharCode(0x92, 0x8D, 0x95, 0xB6);  // 「注文」の Shift_JIS
    assert.strictEqual(C.detectEncoding(utf8), "UTF-8");
    assert.strictEqual(C.detectEncoding(sjis), "Shift_JIS");
});

test("デザイン番号の表記ゆれ", function () {
    assert.strictEqual(C.normalizeKey("ＢＵＳＩＮＥＳＳ００８"), "business008");
    assert.strictEqual(C.normalizeKey(" business008.ai "), "business008");
});

console.log(failures === 0 ? "\nすべて成功" : "\n失敗: " + failures + " 件");
process.exit(failures === 0 ? 0 : 1);
