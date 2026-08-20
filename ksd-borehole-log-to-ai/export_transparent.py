#!/usr/bin/env python3
"""柱状図PDFを背景透過のSVG / PNGで書き出す（報告書に貼る素材用）。

    python export_transparent.py --dir "<PDFのフォルダ>"

Illustratorが無くても動く。PyMuPDF（requirements.txt）だけで完結し、外部通信もしない。

- SVG : ベクターのまま。線・文字がパスとして残るので拡大しても劣化しない。
        Illustrator / Inkscape / Affinity / Figma で開いて編集できる。
- PNG : 指定DPIのラスター。背景はアルファ0（完全透過）。Word・PowerPointに
        そのまま貼れる。

元PDFの柱状図は背景を塗っていないため、どちらも罫線と文字だけが残り、
下地は透明になる。
"""
import argparse
import datetime as _dt
import json
import os
import sys

try:
    import pymupdf
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # 古いPyMuPDFの名前
    except ImportError:
        sys.exit("PyMuPDF が見つかりません。`pip install -r requirements.txt` を実行してください。")

from preflight import load_manifest, render_table

PT_TO_MM = 25.4 / 72.0


def content_bbox(page, margin_mm):
    """実際に描画がある範囲を求める。余白を落とすのに使う。"""
    bbox = pymupdf.Rect()  # 空の矩形から union していく
    for drawing in page.get_drawings():
        bbox |= drawing["rect"]
    for block in page.get_text("dict")["blocks"]:
        bbox |= pymupdf.Rect(block["bbox"])
    if bbox.is_empty or bbox.is_infinite:
        return page.rect
    margin = margin_mm / PT_TO_MM
    bbox = pymupdf.Rect(bbox.x0 - margin, bbox.y0 - margin,
                        bbox.x1 + margin, bbox.y1 + margin)
    bbox &= page.rect
    return bbox


def export_svg(page, path, text_as_path):
    svg = page.get_svg_image(text_as_path=text_as_path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return os.path.getsize(path)


def export_png(page, path, dpi, clip=None):
    # alpha=True で背景を塗らない＝透過PNGになる
    pixmap = page.get_pixmap(dpi=dpi, alpha=True, clip=clip)
    pixmap.save(path)
    return os.path.getsize(path), pixmap.width, pixmap.height


def check_png_transparent(path):
    """四隅のアルファが0か（＝背景が透けているか）を確認する。"""
    pixmap = pymupdf.Pixmap(path)
    if not pixmap.alpha:
        return False
    w, h = pixmap.width, pixmap.height
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    return all(pixmap.pixel(x, y)[-1] == 0 for x, y in corners)


def main(argv=None):
    parser = argparse.ArgumentParser(description="柱状図PDFを背景透過のSVG/PNGで書き出す")
    parser.add_argument("--dir", default=".", help="PDFが置いてあるフォルダ（既定: カレント）")
    parser.add_argument("--out", default=None, help="出力先（既定: <dir>/transparent）")
    parser.add_argument("--manifest",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json"),
                        help="対象ファイル一覧。--all-pdfs を付けると無視される")
    parser.add_argument("--all-pdfs", action="store_true",
                        help="manifestを使わず、フォルダ内の全PDFを対象にする")
    parser.add_argument("--formats", default="svg,png",
                        help="出力形式をカンマ区切りで（svg / png）。既定: svg,png")
    parser.add_argument("--dpi", type=int, default=300,
                        help="PNGの解像度。既定300（印刷用）。画面用なら150で十分")
    parser.add_argument("--trim", action="store_true",
                        help="描画のない余白を切り落とす（素材として貼るときに扱いやすい）")
    parser.add_argument("--trim-margin-mm", type=float, default=2.0,
                        help="--trim 時に残す余白（mm）。既定2.0")
    parser.add_argument("--keep-text", action="store_true",
                        help="SVG内の文字をテキストのまま残す（既定はパス化）。"
                             "編集はしやすいが、開く側に MS ゴシック等が無いと置換される")
    args = parser.parse_args(argv)

    src_dir = os.path.abspath(args.dir)
    if not os.path.isdir(src_dir):
        sys.exit("フォルダが見つかりません: %s" % src_dir)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(src_dir, "transparent")

    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in formats if f not in ("svg", "png")]
    if unknown:
        sys.exit("未対応の形式: %s（svg / png のみ）" % "、".join(unknown))

    if args.all_pdfs:
        names = sorted(n for n in os.listdir(src_dir) if n.lower().endswith(".pdf"))
        targets = [{"no": i + 1, "file": n} for i, n in enumerate(names)]
    else:
        targets = load_manifest(args.manifest)["files"]

    os.makedirs(out_dir, exist_ok=True)
    rows, items = [], []
    missing = []

    for entry in targets:
        path = os.path.join(src_dir, entry["file"])
        stem = os.path.splitext(entry["file"])[0]
        if not os.path.isfile(path):
            missing.append(entry["file"])
            rows.append([entry["no"], entry["file"], "見つからない", "-", "-", "-"])
            continue

        doc = pymupdf.open(path)
        page = doc[0]
        original_mm = "%.1f × %.1f" % (page.rect.width * PT_TO_MM, page.rect.height * PT_TO_MM)
        clip = None
        if args.trim:
            clip = content_bbox(page, args.trim_margin_mm)
            # SVGは cropbox に従うので、ページ側を切り詰めてしまうのが確実
            page.set_cropbox(clip)
            page = doc[0]
            clip = None  # cropbox を絞ったので pixmap 側の clip は不要
        size_mm = "%.1f × %.1f" % (page.rect.width * PT_TO_MM, page.rect.height * PT_TO_MM)
        if args.trim and size_mm != original_mm:
            size_mm = "%s（元 %s）" % (size_mm, original_mm)
        item = {"no": entry["no"], "source": entry["file"], "page_size_mm": size_mm, "outputs": {}}
        svg_cell = png_cell = "-"

        if "svg" in formats:
            svg_path = os.path.join(out_dir, stem + ".svg")
            size = export_svg(page, svg_path, text_as_path=not args.keep_text)
            item["outputs"]["svg"] = {"path": svg_path, "bytes": size,
                                      "text_as_path": not args.keep_text}
            svg_cell = "%.1f MB" % (size / 1024.0 / 1024.0)

        if "png" in formats:
            png_path = os.path.join(out_dir, stem + ".png")
            size, w, h = export_png(page, png_path, args.dpi, clip)
            transparent = check_png_transparent(png_path)
            item["outputs"]["png"] = {"path": png_path, "bytes": size,
                                      "pixels": [w, h], "dpi": args.dpi,
                                      "background_transparent": transparent}
            png_cell = "%d×%d px / %.1f MB%s" % (
                w, h, size / 1024.0 / 1024.0, "" if transparent else " ※背景が不透明")

        doc.close()
        items.append(item)
        rows.append([entry["no"], stem, "OK", size_mm, svg_cell, png_cell])

    print(render_table(rows, ["No.", "ファイル", "状態", "用紙(mm)", "SVG", "PNG"]))
    print()

    opaque = [i for i in items
              if i["outputs"].get("png") and not i["outputs"]["png"]["background_transparent"]]
    if opaque:
        print("⚠️  背景が透過していないPNGがある（元PDFが白い矩形を敷いている可能性）:")
        for i in opaque:
            print("     - %s" % i["source"])
    if missing:
        print("❌ 見つからないPDF: %s" % "、".join(missing))

    report = {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_dir": src_dir,
        "out_dir": out_dir,
        "formats": formats,
        "dpi": args.dpi,
        "trim": args.trim,
        "svg_text_as_path": not args.keep_text,
        "items": items,
        "missing": missing,
    }
    with open(os.path.join(out_dir, "export_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print()
    print("出力先: %s" % out_dir)
    return 1 if (missing or opaque) else 0


if __name__ == "__main__":
    sys.exit(main())
