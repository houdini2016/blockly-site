// scan_templates.py が作った JSON を読み、テンプレートごとに
// 「どの文字がどの項目として置き換わるか」「置き換わらない仮の文字はないか」を一覧にする。
//   node scan_report.js templates.json > report.md

var fs = require("fs");
var path = require("path");
var C = require(path.join(__dirname, "..", "meishi_core.jsx"));
global.MeishiCore = C;
var AI = eval(fs.readFileSync(path.join(__dirname, "..", "meishi_ai.jsx"), "utf8").replace(/^\uFEFF/, "") + "; MeishiAI");

// PDF の座標 [左, 上, 右, 下]（下が大きい）→ Illustrator の座標（上が大きい）
function toAI(b) { return [b[0], -b[1], b[2], -b[3]]; }

var data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

// すべての項目に「★項目名」を入れた架空の注文
var dummy = {};
for (var f in C.FIELD_ALIASES) dummy[f] = "★" + f;
delete dummy["部署"];

var out = ["# テンプレート検査結果", ""];
var problems = 0;
data.forEach(function (t) {
    out.push("## " + t.file);
    if (t.error) { out.push("- 読めませんでした: " + t.error, ""); problems++; return; }
    var fields = [];
    t.lines.forEach(function (l) {
        var plan = C.planEdits(l.text, dummy, { keepLeftover: true });
        var after = C.applyEditsToString(l.text, plan.edits);
        plan.used.forEach(function (u) { if (fields.indexOf(u) < 0) fields.push(u); });
        var mark = plan.edits.length === 0 ? "\u3000" : "✓";
        if (C.hasLeftover(after)) { mark = "⚠"; problems++; }
        out.push("- " + mark + " `" + l.text + "`" + (plan.edits.length ? " → `" + after + "`" : "") +
                 "  (" + l.font + " " + l.size + "pt)");
    });
    out.push("", "差し込み先: " + (fields.length ? fields.join("、") : "なし"));
    t.lines.forEach(function (l) {
        if (!C.isLogoText(l.text)) return;
        // 貼り込み画像（細かさ 2 以上）だけを対象にする（meishi_ai.jsx が消すのは画像だけ）
        var imgs = (t.images || []).filter(function (im) { return im.px_per_pt >= 2; });
        var info = {};
        var marks = AI.pickMarks(imgs.map(function (im) { return toAI(im.bbox); }), toAI(l.bbox), info)
            .map(function (i) { return imgs[i]; });
        if (info.ambiguous) out.push("LOGO 横に画像が複数あり、マークか分からないため消さない");
        out.push("LOGO 横の画像（ロゴ無しのとき消す）: " + marks.length + " 個" +
                 (marks.length ? "  " + JSON.stringify(marks.map(function (m) { return m.bbox; })) : ""));
    });
    out.push("");
});
out.push("---", "⚠ の数: " + problems + "（仮の文字が置き換わらずに残る行）");
console.log(out.join("\n"));
