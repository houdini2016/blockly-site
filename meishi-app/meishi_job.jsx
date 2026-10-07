// =====================================================================
//  名刺自動作成（注文通知アプリの［名刺を作成］ボタンから呼ばれるスクリプト）
//
//  注文通知アプリが書き出した「meishi_job.txt」を読み、注文ごとに
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
    var JOB_FILE = new File(Folder.userData + "/meishi_job.txt");

    if (!JOB_FILE.exists) {
        alert("名刺作成の指示ファイルが見つかりません。\n注文通知アプリの［名刺を作成］ボタンから実行してください。");
        return;
    }
    JOB_FILE.encoding = "UTF-8";   // 中身は英数字だけ
    JOB_FILE.open("r");
    var records = C.parseJob(JOB_FILE.read());
    JOB_FILE.close();
    JOB_FILE.remove();   // 同じ指示で二度作らないように消す
    if (!records) {
        alert("名刺作成の指示ファイルの形が違います。注文通知アプリを最新版にしてください。");
        return;
    }

    var report = [];
    var oldLevel = app.userInteractionLevel;
    app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;   // フォント不足などの確認を出さない
    try {
        for (var i = 0; i < records.length; i++) {
            var rec = records[i];
            var warnings = [];
            if (!rec["テンプレート"] || !rec["保存先"]) {
                var keys = [];
                for (var k in rec) if (rec.hasOwnProperty(k)) keys.push(k);
                report.push("✕ " + (rec["注文番号"] || "") + "\n   テンプレートか保存先が指定されていません（受け取った項目: " + keys.join("、") + "）");
                continue;
            }
            var tpl = new File(rec["テンプレート"]);
            var out = new File(rec["保存先"]);
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

    // 確認用ログ（うまくいかないときに送ってもらう）：デスクトップの「名刺作成ログ.txt」
    try {
        var log = new File(Folder.desktop + "/名刺作成ログ.txt");
        log.encoding = "UTF-8";
        log.open("w");
        log.write("\uFEFF" + report.join("\n\n") + "\n\n--- 文字の間隔（k=カーニング, t=トラッキング） ---\n" +
                  MeishiAI.debugLog.join("\n"));
        log.close();
    } catch (logErr) { /* ログが書けなくても名刺づくりには関係ない */ }

    if (report.length > 0) {
        alert("名刺を作成しました。次の点を確認してください。\n\n" + report.join("\n\n"));
    }
})();
