// scan_templates.py が作った JSON から、全テンプレートの「要点だけ」をまとめる。
//   node scan_summary.js templates.json [一覧.csv]
// ・仮の文字が置き換わらずに残るテンプレート
// ・氏名の差し込み先が見つからないテンプレート
// ・LOGO 横のマーク画像を消すテンプレート / 候補が複数で消さないテンプレート

var fs = require("fs");
var path = require("path");
var C = require(path.join(__dirname, "..", "meishi_core.jsx"));
global.MeishiCore = C;
var AI = eval(fs.readFileSync(path.join(__dirname, "..", "meishi_ai.jsx"), "utf8").replace(/^﻿/, "") + "; MeishiAI");

function toAI(b) { return [b[0], -b[1], b[2], -b[3]]; }
function base(f) { return f.split("/").pop(); }

var data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
var dummy = {};
for (var f in C.FIELD_ALIASES) dummy[f] = "★";
delete dummy["部署"];

var leftovers = [], noName = [], marks = [], ambiguous = [], rows = [];
data.forEach(function (t) {
    if (t.error) { leftovers.push(base(t.file) + ": 読めませんでした"); return; }
    var used = [], left = [];
    t.lines.forEach(function (l) {
        var p = C.planEdits(l.text, dummy);
        p.used.forEach(function (u) { if (used.indexOf(u) < 0) used.push(u); });
        if (C.hasLeftover(C.applyEditsToString(l.text, p.edits))) left.push(l.text.replace(/\s+/g, " "));
    });
    var imgs = (t.images || []).filter(function (im) { return im.px_per_pt >= 2; }).map(function (im) { return toAI(im.bbox); });
    var n = 0, info = {};
    t.lines.forEach(function (l) { if (C.isLogoText(l.text)) n += AI.pickMarks(imgs, toAI(l.bbox), info).length; });
    if (left.length) leftovers.push(base(t.file) + ": " + left.join(" | "));
    if (used.indexOf("氏名") < 0 && used.indexOf("氏名英字") < 0) noName.push(base(t.file));
    if (n) marks.push(base(t.file));
    if (info.ambiguous) ambiguous.push(base(t.file));
    rows.push([t.file, used.join("・"), left.length, n]);
});

console.log("# テンプレート検査のまとめ（" + data.length + " 個）\n");
console.log("## 仮の文字が残る（" + leftovers.length + "）\n" + leftovers.map(function (s) { return "- " + s; }).join("\n") + "\n");
console.log("## 氏名の差し込み先が見つからない（" + noName.length + "）\n" + noName.join("、") + "\n");
console.log("## LOGO 横のマーク画像を消す（" + marks.length + "）\n" + marks.join("、") + "\n");
console.log("## LOGO 横に画像が複数あり消さない（" + ambiguous.length + "）\n" + ambiguous.join("、"));
if (process.argv[3]) {
    fs.writeFileSync(process.argv[3], "﻿ファイル,差し込み先,残る仮の文字(行),消すLOGOマーク(個)\r\n" + rows.map(function (r) {
        return r.map(function (x) { return '"' + String(x).replace(/"/g, '""') + '"'; }).join(",");
    }).join("\r\n"));
}
