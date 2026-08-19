/*
 * KSD案件 ボーリング柱状図 PDF → Illustrator(.ai) 一括変換スクリプト（Step 3）
 *
 * 使い方（Illustrator を起動した状態で）:
 *   ファイル > スクリプト > その他のスクリプト... で本ファイルを選択
 *   → フォルダ選択ダイアログが出るので、PDFの入ったフォルダを指定する
 *
 * 実行前に preflight.py を通し、未埋め込みフォントが出たものは
 * 対応フォントをPCにインストールしてから実行すること（README参照）。
 *
 * ExtendScript(ES3)で書いてある。const/let・アロー関数・JSON は使えない。
 */

#target illustrator

// ============================== 設定 ==============================
var CONFIG = {
    // 空文字にするとフォルダ選択ダイアログを出す。固定したい場合はフルパスを書く。
    // 例: "C:\\Users\\tsoma\\Documents\\KSD_地盤調査\\柱状図_最終版"
    SRC_FOLDER: "",

    // 出力先。"" ならSRC_FOLDER直下の DEST_SUBFOLDER に出す。
    DEST_FOLDER: "",
    DEST_SUBFOLDER: "ai",

    // 既存の .ai を上書きするか。false ならスキップする。
    OVERWRITE: false,

    // 目視確認用のPNGを preview/ に書き出すか（Step 4のチェック用）。
    EXPORT_PREVIEW_PNG: true,
    PREVIEW_SCALE: 50,        // %。A3原寸の50%程度で十分読める。

    // .ai の互換バージョン。"ILLUSTRATOR17"(CC) は受け渡し互換性が高い。
    // 実行中のIllustratorが対応しない値ならCS6→既定値の順に自動フォールバックする。
    AI_COMPATIBILITY: "ILLUSTRATOR17",

    // .ai にPDF互換データを持たせる。他アプリでの配置・verify_ai.py での自動検証に必要。
    PDF_COMPATIBLE: true,

    // PDFのどの領域を取り込むか。通常は用紙サイズそのままの MEDIABOX。
    CROP_BOX: "PDFMEDIABOX",

    // 変換中にフォント置換などのダイアログで止まらないようにする。
    // false にすると1件ごとにダイアログが出るが、置換の有無をその場で確認できる。
    SUPPRESS_DIALOGS: true
};
// ==================================================================

function two(n) { return (n < 10 ? "0" : "") + n; }

function timestamp() {
    var d = new Date();
    return "" + d.getFullYear() + two(d.getMonth() + 1) + two(d.getDate())
        + "_" + two(d.getHours()) + two(d.getMinutes()) + two(d.getSeconds());
}

function baseName(file) {
    var name = decodeURI(file.name);
    var dot = name.lastIndexOf(".");
    return dot > 0 ? name.substring(0, dot) : name;
}

function Logger(file) {
    this.file = file;
    this.lines = [];
}
Logger.prototype.write = function (line) {
    this.lines.push(line);
    $.writeln(line);
};
Logger.prototype.save = function () {
    this.file.encoding = "UTF-8";
    if (this.file.open("w")) {
        this.file.write(this.lines.join("\r\n") + "\r\n");
        this.file.close();
    }
};

function resolveCompatibility(name) {
    var order = [name, "ILLUSTRATOR17", "ILLUSTRATOR16", "ILLUSTRATOR15"];
    for (var i = 0; i < order.length; i++) {
        if (Compatibility[order[i]] !== undefined) {
            return { value: Compatibility[order[i]], name: order[i] };
        }
    }
    return null; // 既定値のまま使う
}

/* 開いたドキュメントで実際に使われているフォント名を集める。
 * 元PDFのフォント一覧（preflight_report）と突き合わせると、
 * Illustrator側でフォントが置換されたかどうかが分かる。 */
function usedFontNames(doc) {
    var names = {};
    var frames = doc.textFrames;
    for (var i = 0; i < frames.length; i++) {
        var name = null;
        try {
            name = frames[i].textRange.characterAttributes.textFont.name;
        } catch (e) {
            name = "(フォント混在または取得不可)";
        }
        if (name) { names[name] = true; }
    }
    var list = [];
    for (var key in names) {
        if (names.hasOwnProperty(key)) { list.push(key); }
    }
    list.sort();
    return list;
}

function exportPreview(doc, pngFile, scale) {
    var options = new ExportOptionsPNG24();
    options.artBoardClipping = true;
    options.antiAliasing = true;
    options.transparency = false;
    options.horizontalScale = scale;
    options.verticalScale = scale;
    doc.exportFile(pngFile, ExportType.PNG24, options);
}

function main() {
    var srcFolder = CONFIG.SRC_FOLDER
        ? new Folder(CONFIG.SRC_FOLDER)
        : Folder.selectDlg("柱状図PDFの入ったフォルダを選んでください");
    if (!srcFolder || !srcFolder.exists) {
        alert("フォルダが指定されなかったため中止した。");
        return;
    }

    var pdfFiles = srcFolder.getFiles(function (f) {
        return f instanceof File && /\.pdf$/i.test(decodeURI(f.name));
    });
    if (!pdfFiles.length) {
        alert("PDFが1つも見つからない:\n" + srcFolder.fsName);
        return;
    }
    pdfFiles.sort(function (a, b) {
        return decodeURI(a.name) < decodeURI(b.name) ? -1 : 1;
    });

    var destFolder = CONFIG.DEST_FOLDER
        ? new Folder(CONFIG.DEST_FOLDER)
        : new Folder(srcFolder.fsName + "/" + CONFIG.DEST_SUBFOLDER);
    if (!destFolder.exists && !destFolder.create()) {
        alert("出力フォルダを作れない:\n" + destFolder.fsName);
        return;
    }
    var previewFolder = new Folder(destFolder.fsName + "/preview");
    if (CONFIG.EXPORT_PREVIEW_PNG && !previewFolder.exists) {
        previewFolder.create();
    }

    var log = new Logger(new File(destFolder.fsName + "/conversion_log_" + timestamp() + ".txt"));
    log.write("KSD案件 柱状図PDF → .ai 変換ログ");
    log.write("実行日時 : " + new Date().toString());
    log.write("Illustrator : " + app.name + " " + app.version);
    log.write("入力 : " + srcFolder.fsName);
    log.write("出力 : " + destFolder.fsName);
    log.write("対象 : " + pdfFiles.length + " ファイル");
    log.write("");

    var openOptions = new PDFOpenOptions();
    openOptions.pageToOpen = 1;
    if (PDFBoxType[CONFIG.CROP_BOX] !== undefined) {
        openOptions.pdfCropToBox = PDFBoxType[CONFIG.CROP_BOX];
    }

    var saveOptions = new IllustratorSaveOptions();
    var compat = resolveCompatibility(CONFIG.AI_COMPATIBILITY);
    if (compat) {
        saveOptions.compatibility = compat.value;
        log.write("保存互換 : " + compat.name);
    } else {
        log.write("保存互換 : Illustrator既定値");
    }
    saveOptions.pdfCompatible = CONFIG.PDF_COMPATIBLE;
    saveOptions.embedICCProfile = true;
    try { saveOptions.embedLinkedFiles = true; } catch (e) {}
    saveOptions.compressed = true;
    log.write("");

    var previousLevel = app.userInteractionLevel;
    if (CONFIG.SUPPRESS_DIALOGS) {
        app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
    }

    var succeeded = 0, skipped = 0, failed = 0;
    var failures = [];

    try {
        for (var i = 0; i < pdfFiles.length; i++) {
            var pdf = pdfFiles[i];
            var stem = baseName(pdf);
            var aiFile = new File(destFolder.fsName + "/" + stem + ".ai");
            var label = "[" + (i + 1) + "/" + pdfFiles.length + "] " + stem;

            if (aiFile.exists && !CONFIG.OVERWRITE) {
                skipped++;
                log.write(label + " : スキップ（同名の.aiが既にある。上書きするなら CONFIG.OVERWRITE = true）");
                continue;
            }

            var doc = null;
            try {
                doc = app.open(pdf, undefined, openOptions);
                var fonts = usedFontNames(doc);
                doc.saveAs(aiFile, saveOptions);
                if (CONFIG.EXPORT_PREVIEW_PNG) {
                    exportPreview(doc, new File(previewFolder.fsName + "/" + stem + ".png"),
                                  CONFIG.PREVIEW_SCALE);
                }
                succeeded++;
                log.write(label + " : OK");
                log.write("    アートボード : " + doc.artboards.length
                    + " / テキスト : " + doc.textFrames.length
                    + " / パス : " + doc.pathItems.length
                    + " / 配置画像 : " + doc.placedItems.length
                    + " / ラスター : " + doc.rasterItems.length);
                log.write("    使用フォント : " + (fonts.length ? fonts.join("、") : "なし"));
                log.write("    出力 : " + aiFile.fsName);
            } catch (err) {
                failed++;
                failures.push(stem + " : " + err);
                log.write(label + " : 失敗 → " + err);
            } finally {
                if (doc) {
                    try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
                }
            }
        }
    } finally {
        app.userInteractionLevel = previousLevel;
    }

    log.write("");
    log.write("成功 " + succeeded + " / スキップ " + skipped + " / 失敗 " + failed);
    if (failures.length) {
        log.write("失敗したファイル:");
        for (var k = 0; k < failures.length; k++) { log.write("  - " + failures[k]); }
    }
    log.write("");
    log.write("次の手順: verify_ai.py で .ai の中身（文字欠落・文字化け）を自動照合すること。");
    log.save();

    var summary = "変換が終わった。\n\n成功 " + succeeded + " / スキップ " + skipped
        + " / 失敗 " + failed + "\n\n出力先:\n" + destFolder.fsName
        + "\n\nログ:\n" + log.file.fsName;
    if (failures.length) {
        summary += "\n\n失敗:\n" + failures.join("\n");
    }
    alert(summary);
}

main();
