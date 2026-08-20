#!/usr/bin/env python3
"""変換後の .ai を元PDFと自動照合する（Step 4）。

    python verify_ai.py --src "…\\柱状図_最終版" --ai "…\\柱状図_最終版\\ai"

pdf_to_ai.jsx が「PDF互換ファイルを作成」を有効にして保存している前提で、
.ai をPDFとして読み、元PDFとの間で

  - 用紙サイズ・ページ数が一致しているか
  - 文字が欠落していないか（文字単位の網羅率＋消えた語句のサンプル）
  - 文字化けの兆候がないか（元PDFに無い文字が増えていないか）

を照合する。目視確認を置き換えるものではなく、目視で見るべき箇所を絞るためのもの。
"""
import argparse
import collections
import datetime as _dt
import json
import logging
import os
import re
import sys
import unicodedata

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    sys.exit("pypdf が見つかりません。`pip install -r requirements.txt` を実行してください。")

from preflight import PT_TO_MM, collect_fonts, load_manifest, render_table

# 壊れたファイルを開こうとしたときの pypdf 自身のログは、こちらの判定文と重複するので抑制する。
logging.getLogger("pypdf").setLevel(logging.CRITICAL)

# 文字の網羅率がこれ以上なら合格、下の閾値未満なら不合格。
COVERAGE_OK = 0.98
COVERAGE_WARN = 0.90
# 用紙サイズの許容差（mm）。
SIZE_TOLERANCE_MM = 1.0
CJK_RE = re.compile(r"[　-ヿ㐀-鿿＀-￯]")


def normalize(text):
    """比較用に正規化する。全角/半角の揺れは吸収し、空白は落とす。"""
    return "".join(unicodedata.normalize("NFKC", text or "").split())


def tokens(text):
    """語句単位の照合用。空白・記号で区切った断片を返す。"""
    raw = unicodedata.normalize("NFKC", text or "")
    return [t for t in re.split(r"[\s|,;:]+", raw) if len(t) >= 2]


def read_pdf_text(path):
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
    chunks = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    return reader, "\n".join(chunks)


def compare(src_path, ai_path):
    result = {
        "ai_size_bytes": os.path.getsize(ai_path),
        "pdf_compatible": True,
        "pages": None,
        "page_size_mm": None,
        "coverage": None,
        "missing_char_count": 0,
        "missing_chars": "",
        "missing_tokens": [],
        "added_cjk_chars": "",
        "non_embedded_fonts": [],
        "errors": [],
        "warnings": [],
    }
    try:
        src_reader, src_text = read_pdf_text(src_path)
    except Exception as exc:
        result["errors"].append("元PDFを読めない: %s" % exc)
        return result
    with open(ai_path, "rb") as fh:
        header = fh.read(5)
    try:
        ai_reader, ai_text = read_pdf_text(ai_path)
    except Exception as exc:
        result["pdf_compatible"] = False
        if header != b"%PDF-":
            # .ai は中身がPDFコンテナなので、ヘッダが違うのは保存失敗か破損。
            result["errors"].append(
                ".ai が壊れているか、Illustrator形式で保存されていない"
                "（先頭が %%PDF- でない）: %s" % exc)
        else:
            # PDF互換オフで保存された .ai はここに来る（Illustratorでは正常に開ける）
            result["warnings"].append(
                ".ai をPDFとして読めないため自動照合できない（保存時に「PDF互換ファイルを作成」が"
                "オフだった可能性）。目視確認するか、jsxの CONFIG.PDF_COMPATIBLE を true にして"
                "再変換すること: %s" % exc)
        return result

    result["pages"] = len(ai_reader.pages)
    if result["pages"] != 1:
        result["warnings"].append("出力が %d ページある（1ページの想定）" % result["pages"])

    src_box = src_reader.pages[0].mediabox
    ai_box = ai_reader.pages[0].mediabox
    src_size = (float(src_box.width) * PT_TO_MM, float(src_box.height) * PT_TO_MM)
    ai_size = (float(ai_box.width) * PT_TO_MM, float(ai_box.height) * PT_TO_MM)
    result["page_size_mm"] = [round(ai_size[0], 1), round(ai_size[1], 1)]
    if (abs(src_size[0] - ai_size[0]) > SIZE_TOLERANCE_MM
            or abs(src_size[1] - ai_size[1]) > SIZE_TOLERANCE_MM):
        result["warnings"].append(
            "用紙サイズが元PDFと違う（元 %.1f×%.1fmm → 出力 %.1f×%.1fmm）。"
            "jsxの CONFIG.CROP_BOX を見直すこと" % (src_size + ai_size))

    src_norm, ai_norm = normalize(src_text), normalize(ai_text)
    if not src_norm:
        result["warnings"].append("元PDFからテキストを抽出できないため文字の照合は行わない")
    else:
        src_counter = collections.Counter(src_norm)
        missing = src_counter - collections.Counter(ai_norm)
        missing_total = sum(missing.values())
        result["missing_char_count"] = missing_total
        result["coverage"] = round(1.0 - missing_total / float(len(src_norm)), 4)
        result["missing_chars"] = "".join(
            ch for ch, _n in sorted(missing.items(), key=lambda kv: -kv[1])[:30])

        ai_tokens_blob = ai_norm
        seen = set()
        for token in tokens(src_text):
            key = normalize(token)
            if not key or key in seen:
                continue
            seen.add(key)
            if key not in ai_tokens_blob:
                result["missing_tokens"].append(token)
        result["missing_tokens"] = result["missing_tokens"][:15]

        added = collections.Counter(ai_norm) - src_counter
        added_cjk = "".join(ch for ch in added if CJK_RE.match(ch))
        result["added_cjk_chars"] = added_cjk[:30]

        if result["coverage"] < COVERAGE_WARN:
            result["errors"].append(
                "文字の欠落が大きい（網羅率 %.1f%% / 欠落 %d文字）。フォント置換や"
                "アウトライン化で文字が失われた可能性が高い"
                % (result["coverage"] * 100, missing_total))
        elif result["coverage"] < COVERAGE_OK:
            result["warnings"].append(
                "文字が一部欠落している（網羅率 %.1f%% / 欠落 %d文字）"
                % (result["coverage"] * 100, missing_total))
        if "�" in ai_text:
            result["errors"].append("出力に置換文字(U+FFFD)が含まれる。文字化けしている")
        elif added_cjk:
            result["warnings"].append(
                "元PDFに無い日本語文字が出力に増えている（文字化けの疑い）: %s" % added_cjk)

    fonts = collect_fonts(ai_reader.pages[0].get("/Resources"))
    result["non_embedded_fonts"] = sorted(
        f["base_font"] for f in fonts.values() if not f["embedded"])
    if result["non_embedded_fonts"]:
        result["warnings"].append(
            "出力の未埋め込みフォント: %s（このPCでは正しく見えても、"
            "他PCで開くと置換される）" % "、".join(result["non_embedded_fonts"]))
    return result


def build_markdown(report):
    out = ["# 柱状図 .ai 変換結果 照合レポート", "",
           "- 実行日時: %s" % report["generated_at"],
           "- 元PDF: `%s`" % report["src_dir"],
           "- 変換後: `%s`" % report["ai_dir"],
           "- 判定: **%s**" % ("OK" if report["ok"] else "要対応"), "",
           "| No. | ファイル | 状態 | 用紙(mm) | 文字網羅率 | 欠落文字数 |",
           "|---|---|---|---|---|---|"]
    for item in report["items"]:
        size = "-" if not item.get("page_size_mm") else "%s × %s" % tuple(item["page_size_mm"])
        cov = "-" if item.get("coverage") is None else "%.1f%%" % (item["coverage"] * 100)
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            item["no"], item["ai_file"], item["status"], size, cov,
            item.get("missing_char_count", 0)))
    out.append("")
    out.append("## 詳細")
    for item in report["items"]:
        out.append("")
        out.append("### No.%s %s" % (item["no"], item["ai_file"]))
        if item["status"] == "MISSING":
            out.append("- **.ai が出力されていない**")
            for cand in item.get("candidates", []):
                out.append("    - 似た名前のファイルあり: `%s`" % cand)
            continue
        for err in item.get("errors", []):
            out.append("- ❌ %s" % err)
        for warn in item.get("warnings", []):
            out.append("- ⚠️ %s" % warn)
        if not item.get("errors") and not item.get("warnings"):
            out.append("- 問題なし")
        if item.get("missing_tokens"):
            out.append("- 出力側で見つからなかった語句（先頭%d件）:" % len(item["missing_tokens"]))
            for token in item["missing_tokens"]:
                out.append("    - `%s`" % token)
        if item.get("missing_chars"):
            out.append("- 欠落した文字（頻度順）: `%s`" % item["missing_chars"])
    out.append("")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description="変換後の .ai を元PDFと照合する")
    parser.add_argument("--src", default=".", help="元PDFのフォルダ（既定: カレント）")
    parser.add_argument("--ai", default=None, help="変換後.aiのフォルダ（既定: <src>/ai）")
    parser.add_argument("--manifest",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json"))
    parser.add_argument("--out", default=None, help="レポート出力先（既定: <ai>/reports）")
    args = parser.parse_args(argv)

    src_dir = os.path.abspath(args.src)
    ai_dir = os.path.abspath(args.ai) if args.ai else os.path.join(src_dir, "ai")
    for path, label in ((src_dir, "元PDF"), (ai_dir, "変換後.ai")):
        if not os.path.isdir(path):
            sys.exit("%sのフォルダが見つかりません: %s" % (label, path))
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(ai_dir, "reports")

    manifest = load_manifest(args.manifest)
    ai_present = [n for n in os.listdir(ai_dir) if n.lower().endswith(".ai")]

    items = []
    for entry in manifest["files"]:
        stem = os.path.splitext(entry["file"])[0]
        ai_name = stem + ".ai"
        item = {"no": entry["no"], "src_file": entry["file"], "ai_file": ai_name,
                "note": entry.get("note", "")}
        src_path = os.path.join(src_dir, entry["file"])
        ai_path = os.path.join(ai_dir, ai_name)

        if not os.path.isfile(ai_path):
            item["status"] = "MISSING"
            item["candidates"] = sorted(n for n in ai_present if n.startswith("No%d" % entry["no"]))
            # 指示書どおり No.6 は「修正」をファイル名に残す必要がある
            if "修正" in stem:
                bad = [c for c in item["candidates"] if "修正" not in c]
                if bad:
                    item["candidates"] = ["%s ← ファイル名に「修正」が残っていない" % c for c in bad] \
                        + [c for c in item["candidates"] if c not in bad]
            items.append(item)
            continue
        if not os.path.isfile(src_path):
            item["status"] = "ERROR"
            item["errors"] = ["照合相手の元PDFが見つからない: %s" % src_path]
            item["warnings"] = []
            items.append(item)
            continue

        item.update(compare(src_path, ai_path))
        item["status"] = "ERROR" if item["errors"] else ("WARN" if item["warnings"] else "OK")
        items.append(item)

    listed = {os.path.splitext(e["file"])[0] + ".ai" for e in manifest["files"]}
    extra = sorted(set(ai_present) - listed)

    report = {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "src_dir": src_dir,
        "ai_dir": ai_dir,
        "items": items,
        "extra_files": extra,
        "ok": all(i["status"] in ("OK", "WARN") for i in items),
    }

    rows = []
    for item in items:
        size = "-"
        if item.get("page_size_mm"):
            size = "%s × %s" % tuple(item["page_size_mm"])
        cov = "-" if item.get("coverage") is None else "%.1f%%" % (item["coverage"] * 100)
        rows.append([item["no"], item["ai_file"], item["status"], size, cov,
                     "-" if item["status"] == "MISSING" else item.get("missing_char_count", 0)])
    print(render_table(rows, ["No.", "出力ファイル", "状態", "用紙(mm)", "文字網羅率", "欠落文字数"]))
    print()

    for item in items:
        if item["status"] == "MISSING":
            print("❌ No.%s %s : .ai が出力されていない" % (item["no"], item["ai_file"]))
            for cand in item.get("candidates", []):
                print("     ヒント: 似た名前のファイルがある → %s" % cand)
        for err in item.get("errors", []):
            print("❌ No.%s %s : %s" % (item["no"], item["ai_file"], err))
        for warn in item.get("warnings", []):
            print("⚠️  No.%s %s : %s" % (item["no"], item["ai_file"], warn))
        if item.get("missing_tokens"):
            print("     消えた語句の例: %s" % "、".join(item["missing_tokens"][:5]))
    if extra:
        print()
        print("ℹ️  manifest に無い .ai がある: %s" % "、".join(extra))

    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "verify_report.json")
    md_path = os.path.join(out_dir, "verify_report.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(build_markdown(report))
    print()
    print("レポートを書き出した:")
    print("  %s" % json_path)
    print("  %s" % md_path)

    problems = [i for i in items if i["status"] in ("MISSING", "ERROR")]
    if problems:
        print()
        print("→ %d件に問題がある。原因を潰して再変換すること。" % len(problems))
        return 1
    print()
    print("→ 自動照合は通過。preview/ のPNGで最終目視確認をすること。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
