// scan_templates.py が作った JSON を読み、テンプレートごとに
// 「どの文字がどの項目として置き換わるか」「置き換わらない仮の文字はないか」を一覧にする。
//   node scan_report.js templates.json > report.md

var fs = require("fs");
var path = require("path");
var C = require(path.join(__dirname, "..", "meishi_core.jsx"));

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
        var plan = C.planEdits(l.text, dummy);
        var after = C.applyEditsToString(l.text, plan.edits);
        plan.used.forEach(function (u) { if (fields.indexOf(u) < 0) fields.push(u); });
        var mark = plan.edits.length === 0 ? "\u3000" : "✓";
        if (C.hasLeftover(after)) { mark = "⚠"; problems++; }
        out.push("- " + mark + " `" + l.text + "`" + (plan.edits.length ? " → `" + after + "`" : "") +
                 "  (" + l.font + " " + l.size + "pt)");
    });
    out.push("", "差し込み先: " + (fields.length ? fields.join("、") : "なし"), "");
});
out.push("---", "⚠ の数: " + problems + "（仮の文字が置き換わらずに残る行）");
console.log(out.join("\n"));
