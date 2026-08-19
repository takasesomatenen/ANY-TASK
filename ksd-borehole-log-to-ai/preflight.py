#!/usr/bin/env python3
"""KSD案件 ボーリング柱状図PDF プリフライトチェック（Step 1 / Step 2）。

    python preflight.py --dir "C:\\Users\\tsoma\\Documents\\KSD_地盤調査\\柱状図_最終版"

manifest.json に書かれた8ファイルが揃っているかを確認し、各PDFについて
Illustrator変換前に問題になる点（ページ数・スキャン画像かベクターか・
フォントの埋め込み状況）を洗い出して、コンソールと reports/ に出力する。

外部通信は一切行わない。必要なのは pypdf のみ（requirements.txt）。
"""
import argparse
import datetime as _dt
import json
import logging
import os
import re
import sys
import unicodedata

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - 環境セットアップ用の案内
    sys.exit("pypdf が見つかりません。`pip install -r requirements.txt` を実行してください。")

# 壊れたファイルを開こうとしたときの pypdf 自身のログは、こちらの判定文と重複するので抑制する。
logging.getLogger("pypdf").setLevel(logging.CRITICAL)

PT_TO_MM = 25.4 / 72.0
# ページ内にテキストがこれ未満しか無ければ、ベクターPDFではなくスキャン画像の疑い。
MIN_TEXT_CHARS = 50
# 柱状図の本文から孔番号と総掘進長を拾って、manifest と食い違っていないか見るための正規表現。
BOREHOLE_NAME_RE = re.compile(r"ボーリング名\s*No\.?\s*(\d+)")
TOTAL_DEPTH_RE = re.compile(r"総掘進長\s*([0-9]+\.[0-9]+)\s*m")


def load_manifest(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _obj(value):
    """間接参照を解決して実体を返す。"""
    return value.get_object() if hasattr(value, "get_object") else value


def _font_is_embedded(font):
    """フォント辞書から FontDescriptor をたどり、フォントファイルの有無を返す。"""
    subtype = str(font.get("/Subtype", ""))
    if subtype == "/Type0":
        descendants = _obj(font.get("/DescendantFonts"))
        if not descendants:
            return False, None
        descriptor = _obj(_obj(descendants[0]).get("/FontDescriptor"))
    else:
        descriptor = _obj(font.get("/FontDescriptor"))
    if not descriptor:
        # 標準14フォントなど。埋め込みなしとして扱う。
        return False, None
    for key in ("/FontFile", "/FontFile2", "/FontFile3"):
        if key in descriptor:
            return True, key.lstrip("/")
    return False, None


def collect_fonts(resources, seen_xobjects=None, out=None):
    """/Resources を再帰的に walk して使用フォント情報を集める。"""
    out = {} if out is None else out
    seen_xobjects = set() if seen_xobjects is None else seen_xobjects
    resources = _obj(resources)
    if not resources:
        return out

    fonts = _obj(resources.get("/Font")) or {}
    for _key, ref in fonts.items():
        font = _obj(ref)
        if not font:
            continue
        base = str(font.get("/BaseFont", "(BaseFont未設定)")).lstrip("/")
        embedded, kind = _font_is_embedded(font)
        entry = out.setdefault(base, {
            "base_font": base,
            "subtype": str(font.get("/Subtype", "")).lstrip("/"),
            "encoding": str(_obj(font.get("/Encoding")) or ""),
            "embedded": embedded,
            "font_file": kind,
            # サブセット埋め込みは "ABCDEF+FontName" の形になる
            "subset": len(base) > 7 and base[6] == "+" and base[:6].isalpha() and base[:6].isupper(),
        })
        # 同名フォントが複数出てきた場合、埋め込みありを優先で残す
        if embedded and not entry["embedded"]:
            entry["embedded"] = True
            entry["font_file"] = kind

    xobjects = _obj(resources.get("/XObject")) or {}
    for _key, ref in xobjects.items():
        xobj = _obj(ref)
        if not xobj:
            continue
        ident = id(xobj)
        if ident in seen_xobjects:
            continue
        seen_xobjects.add(ident)
        if str(xobj.get("/Subtype", "")) == "/Form":
            collect_fonts(xobj.get("/Resources"), seen_xobjects, out)
    return out


def count_images(resources, seen_xobjects=None):
    resources = _obj(resources)
    if not resources:
        return 0
    seen_xobjects = set() if seen_xobjects is None else seen_xobjects
    total = 0
    xobjects = _obj(resources.get("/XObject")) or {}
    for _key, ref in xobjects.items():
        xobj = _obj(ref)
        if not xobj:
            continue
        ident = id(xobj)
        if ident in seen_xobjects:
            continue
        seen_xobjects.add(ident)
        subtype = str(xobj.get("/Subtype", ""))
        if subtype == "/Image":
            total += 1
        elif subtype == "/Form":
            total += count_images(xobj.get("/Resources"), seen_xobjects)
    return total


def inspect_pdf(path, entry=None):
    """1ファイル分の検査結果を dict で返す。errors は致命的、warnings は要確認。

    entry に manifest の1件を渡すと、PDF本文の孔番号・総掘進長と突き合わせて
    「別の孔／別の深度の版を掴んでいないか」まで確認する。
    """
    result = {
        "path": path,
        "size_bytes": os.path.getsize(path),
        "pages": None,
        "encrypted": False,
        "page_size_mm": None,
        "rotation": 0,
        "text_chars": 0,
        "image_count": 0,
        "borehole_no_in_pdf": None,
        "total_depth_in_pdf": None,
        "fonts": [],
        "non_embedded_fonts": [],
        "errors": [],
        "warnings": [],
    }
    try:
        reader = PdfReader(path)
    except Exception as exc:
        result["errors"].append("PDFとして開けない: %s" % exc)
        return result

    if reader.is_encrypted:
        result["encrypted"] = True
        try:
            # 空パスワードで開ける（閲覧制限のみ）ケースを救う
            reader.decrypt("")
        except Exception:
            pass
        result["warnings"].append(
            "暗号化されている。Illustratorで開けない／編集不可の可能性があるため要確認")

    try:
        result["pages"] = len(reader.pages)
    except Exception as exc:
        result["errors"].append("ページを読めない: %s" % exc)
        return result

    if result["pages"] != 1:
        result["warnings"].append(
            "1ページ構成の想定に対して %d ページある。jsxは先頭ページのみ変換する" % result["pages"])

    page = reader.pages[0]
    box = page.mediabox
    width_mm = float(box.width) * PT_TO_MM
    height_mm = float(box.height) * PT_TO_MM
    result["page_size_mm"] = [round(width_mm, 1), round(height_mm, 1)]
    try:
        result["rotation"] = int(page.get("/Rotate", 0) or 0)
    except Exception:
        result["rotation"] = 0

    try:
        text = page.extract_text() or ""
    except Exception as exc:
        text = ""
        result["warnings"].append("テキスト抽出に失敗: %s" % exc)
    result["text_chars"] = len("".join(text.split()))

    resources = page.get("/Resources")
    result["image_count"] = count_images(resources)
    fonts = collect_fonts(resources)
    result["fonts"] = sorted(fonts.values(), key=lambda f: f["base_font"])
    result["non_embedded_fonts"] = [f["base_font"] for f in result["fonts"] if not f["embedded"]]

    # ファイル名と中身の食い違い（別の孔・浅い版を掴んでいないか）を見る。
    # 書式が違って拾えないこともあるので、拾えたときだけ判定する。
    name_match = BOREHOLE_NAME_RE.search(text)
    depth_match = TOTAL_DEPTH_RE.search(text)
    if name_match:
        result["borehole_no_in_pdf"] = int(name_match.group(1))
    if depth_match:
        result["total_depth_in_pdf"] = float(depth_match.group(1))
    if entry:
        if result["borehole_no_in_pdf"] is not None and result["borehole_no_in_pdf"] != entry["no"]:
            result["errors"].append(
                "中身の孔番号が違う（PDF本文は No.%d、manifestは No.%d）。ファイルを取り違えている"
                % (result["borehole_no_in_pdf"], entry["no"]))
        if (result["total_depth_in_pdf"] is not None
                and abs(result["total_depth_in_pdf"] - float(entry["depth_m"])) > 0.005):
            result["errors"].append(
                "総掘進長がファイル名と違う（PDF本文は %.2fm、想定は %.2fm）。"
                "最終版ではない途中版の可能性がある"
                % (result["total_depth_in_pdf"], float(entry["depth_m"])))

    if result["text_chars"] < MIN_TEXT_CHARS:
        result["errors"].append(
            "テキストがほとんど抽出できない（%d文字 / 画像%d点）。スキャン画像PDFの疑いがあり、"
            "Illustratorで開いても文字が編集できない"
            % (result["text_chars"], result["image_count"]))
    if not result["fonts"] and result["text_chars"] >= MIN_TEXT_CHARS:
        result["warnings"].append("フォント情報が取得できなかった。文字がアウトライン化されている可能性")
    if result["non_embedded_fonts"]:
        result["warnings"].append(
            "未埋め込みフォントあり: %s" % "、".join(result["non_embedded_fonts"]))
    if result["image_count"] and result["text_chars"] >= MIN_TEXT_CHARS:
        result["warnings"].append(
            "画像が %d 点含まれる（ロゴ・網掛け等なら問題なし。要目視確認）" % result["image_count"])
    return result


def _w(text):
    """全角を2幅として数えた表示幅（曖昧幅は1として扱う）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text, width):
    return text + " " * max(0, width - _w(text))


def render_table(rows, headers):
    widths = [max([_w(h)] + [_w(str(r[i])) for r in rows]) for i, h in enumerate(headers)]
    lines = ["  ".join(_pad(h, widths[i]) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(_pad(str(cell), widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def build_markdown(report):
    out = ["# 柱状図PDF プリフライト結果", "",
           "- 実行日時: %s" % report["generated_at"],
           "- 対象フォルダ: `%s`" % report["directory"],
           "- 判定: **%s**" % ("OK" if report["ok"] else "要対応"), "",
           "## ファイル一覧", "",
           "| No. | ファイル | 状態 | ページ | 用紙(mm) | 抽出文字数 | 未埋め込みフォント |",
           "|---|---|---|---|---|---|---|"]
    for item in report["items"]:
        size = "-" if not item.get("page_size_mm") else "%s × %s" % tuple(item["page_size_mm"])
        missing_row = item["status"] == "MISSING"
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            item["no"], item["file"], item["status"],
            item.get("pages") or "-", size,
            "-" if missing_row else item.get("text_chars", 0),
            "-" if missing_row else ("、".join(item.get("non_embedded_fonts") or []) or "なし")))
    out.append("")
    out.append("## 詳細")
    for item in report["items"]:
        out.append("")
        out.append("### No.%s %s" % (item["no"], item["file"]))
        if item["status"] == "MISSING":
            out.append("- **ファイルが見つからない**")
            continue
        for err in item.get("errors", []):
            out.append("- ❌ %s" % err)
        for warn in item.get("warnings", []):
            out.append("- ⚠️ %s" % warn)
        if not item.get("errors") and not item.get("warnings"):
            out.append("- 問題なし")
        if item.get("total_depth_in_pdf") is not None or item.get("borehole_no_in_pdf") is not None:
            out.append("- 本文との照合: 孔番号 %s / 総掘進長 %s" % (
                ("No.%d" % item["borehole_no_in_pdf"]) if item.get("borehole_no_in_pdf") else "取得不可",
                ("%.2fm" % item["total_depth_in_pdf"]) if item.get("total_depth_in_pdf") else "取得不可"))
        if item.get("fonts"):
            out.append("- 使用フォント:")
            for font in item["fonts"]:
                out.append("    - `%s`（%s / %s%s）" % (
                    font["base_font"], font["subtype"],
                    "埋め込みあり" if font["embedded"] else "**埋め込みなし**",
                    "・サブセット" if font["subset"] else ""))
    if report["extra_files"]:
        out.append("")
        out.append("## manifest に無いPDF")
        for name in report["extra_files"]:
            out.append("- `%s`" % name)
    out.append("")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description="柱状図PDFのプリフライトチェック")
    parser.add_argument("--dir", default=".", help="PDFが置いてあるフォルダ（既定: カレント）")
    parser.add_argument("--manifest",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json"),
                        help="対象ファイル一覧のJSON")
    parser.add_argument("--out", default=None,
                        help="レポート出力先フォルダ（既定: <dir>/reports）")
    args = parser.parse_args(argv)

    src_dir = os.path.abspath(args.dir)
    if not os.path.isdir(src_dir):
        sys.exit("フォルダが見つかりません: %s" % src_dir)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(src_dir, "reports")

    manifest = load_manifest(args.manifest)
    present = {name for name in os.listdir(src_dir) if name.lower().endswith(".pdf")}

    items = []
    for entry in manifest["files"]:
        item = {"no": entry["no"], "file": entry["file"], "note": entry.get("note", "")}
        path = os.path.join(src_dir, entry["file"])
        if not os.path.isfile(path):
            # 名前が微妙に違うだけのケースを拾って提案する
            prefix = "No%d" % entry["no"]
            candidates = sorted(n for n in present if n.startswith(prefix))
            item["status"] = "MISSING"
            item["candidates"] = candidates
            items.append(item)
            continue
        item.update(inspect_pdf(path, entry))
        item["status"] = "ERROR" if item["errors"] else ("WARN" if item["warnings"] else "OK")
        items.append(item)

    listed = {entry["file"] for entry in manifest["files"]}
    extra = sorted(present - listed)

    report = {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "directory": src_dir,
        "manifest_revision": manifest.get("revision"),
        "items": items,
        "extra_files": extra,
        "ok": all(i["status"] in ("OK", "WARN") for i in items),
    }

    rows = []
    for item in items:
        size = "-"
        if item.get("page_size_mm"):
            size = "%s × %s" % tuple(item["page_size_mm"])
        missing_row = item["status"] == "MISSING"
        rows.append([
            item["no"], item["file"], item["status"],
            item.get("pages") or "-", size,
            "-" if missing_row else item.get("text_chars", 0),
            "-" if missing_row else ("、".join(item.get("non_embedded_fonts") or []) or "なし"),
        ])
    print(render_table(rows, ["No.", "ファイル", "状態", "頁", "用紙(mm)", "文字数", "未埋め込みフォント"]))
    print()

    for item in items:
        if item["status"] == "MISSING":
            print("❌ No.%s %s : ファイルが見つからない" % (item["no"], item["file"]))
            for cand in item.get("candidates", []):
                print("     ヒント: 似た名前のファイルがある → %s" % cand)
        for err in item.get("errors", []):
            print("❌ No.%s %s : %s" % (item["no"], item["file"], err))
        for warn in item.get("warnings", []):
            print("⚠️  No.%s %s : %s" % (item["no"], item["file"], warn))
    if extra:
        print()
        print("ℹ️  manifest に無いPDFがフォルダ内にある: %s" % "、".join(extra))

    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "preflight_report.json")
    md_path = os.path.join(out_dir, "preflight_report.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(build_markdown(report))
    print()
    print("レポートを書き出した:")
    print("  %s" % json_path)
    print("  %s" % md_path)

    missing = [i for i in items if i["status"] == "MISSING"]
    errors = [i for i in items if i["status"] == "ERROR"]
    if missing or errors:
        print()
        print("→ 未取得 %d件 / エラー %d件。解消してから Step 3（Illustrator変換）へ進むこと。"
              % (len(missing), len(errors)))
        return 1
    print()
    print("→ Step 3（pdf_to_ai.jsx でのIllustrator変換）へ進んでよい。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
