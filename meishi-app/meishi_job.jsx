// =====================================================================
//  名刺自動作成（注文通知アプリの［名刺を作成］ボタンから呼ばれるスクリプト）
//
//  注文通知アプリが書き出した「meishi_job.csv」を読み、1行ごとに
//    1. 指定されたテンプレート(.ai)を開く
//    2. 注文内容を流し込む
//    3. 指定された名前で別名保存する
//    4. そのまま Illustrator で開いておく
//  最後に、確認してほしいこと（要確認）があれば表示します。
//
//  meishi_core.jsx・meishi_ai.jsx を同じフォルダに置いてください。
// =====================================================================

#target illustrator
#include "meishi_core.jsx"
#include "meishi_ai.jsx"

(function () {
    var C = MeishiCore;
    var JOB_FILE = new File(Folder.userData + "/meishi_job.csv");

    if (!JOB_FILE.exists) {
        alert("名刺作成の指示ファイルが見つかりません。\n注文通知アプリの［名刺を作成］ボタンから実行してください。");
        return;
    }
    var records = C.rowsToRecords(C.parseCSV(MeishiAI.readTextFile(JOB_FILE))).records;
    JOB_FILE.remove();   // 同じ指示で二度作らないように消す

    var report = [];
    var oldLevel = app.userInteractionLevel;
    app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;   // フォント不足などの確認を出さない
    try {
        for (var i = 0; i < records.length; i++) {
            var rec = records[i];
            var warnings = [];
            var tpl = new File(rec["テンプレート"] || "");
            var out = new File(rec["保存先"] || "");
            var title = (rec["注文番号"] || "") + "  " + decodeURI(out.name);
            if (!tpl.exists) {
                report.push("✕ " + (rec["注文番号"] || "") + "\n   テンプレートが見つかりません: " + tpl.fsName);
                continue;
            }
            try {
                var doc = app.open(tpl);
                MeishiAI.editDocument(doc, rec, warnings);
                if (!out.parent.exists) out.parent.create();
                var opts = new IllustratorSaveOptions();
                opts.pdfCompatible = true;
                doc.saveAs(out, opts);       // 別名保存。書類は開いたままにする
            } catch (err) {
                report.push("✕ " + title + "\n   エラー: " + err.message);
                continue;
            }
            if (warnings.length > 0) {
                report.push("△ " + title + "\n   - " + warnings.join("\n   - "));
            }
        }
    } finally {
        app.userInteractionLevel = oldLevel;
    }

    if (report.length > 0) {
        alert("名刺を作成しました。次の点を確認してください。\n\n" + report.join("\n\n"));
    }
})();
