#!/usr/bin/env python3
"""Generate preview.html: a three.js toolpath viewer with the bundled presets embedded."""
import json
import os
import sys

import wireprint

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = {"base": 0, "up": 1, "down": 2, "bridge": 3, "travel": 4}

PRESETS = [
    ("a1-cube", "A1 mini 3cmキューブ", ["--printer", "a1mini", "--shape", "grid", "--cols", "4", "--rows", "4", "--spacing", "10", "--levels", "8"]),
    ("a1-tiny", "A1 mini テスト① 2×2", ["--printer", "a1mini", "--shape", "grid", "--cols", "2", "--rows", "2", "--spacing", "10", "--levels", "3"]),
    ("a1-grid", "A1 mini テスト② 3×3", ["--printer", "a1mini", "--shape", "grid", "--cols", "3", "--rows", "3", "--spacing", "10", "--levels", "5"]),
    ("a1-tower", "A1 mini テスト③ 小タワー", ["--printer", "a1mini", "--shape", "tower", "--n", "10", "--radius", "12", "--bulge", "3", "--levels", "6"]),
    ("tower", "ラティス・タワー", ["--shape", "tower"]),
    ("twist", "ねじれタワー", ["--shape", "tower", "--twist", "6"]),
    ("grid", "柱のグリッド", ["--shape", "grid"]),
    ("pyramid", "ピラミッド", ["--shape", "grid", "--cols", "5", "--rows", "5", "--taper", "0.6", "--levels", "12"]),
]


def pack(path_json):
    d = json.load(open(path_json))
    cx, cy = d["bed"][0] / 2, d["bed"][1] / 2
    flat = []
    for s in d["segments"]:
        a, b = s["a"], s["b"]
        flat += [KINDS[s["t"]], round(a[0] - cx, 1), round(a[1] - cy, 1), round(a[2], 1),
                 round(b[0] - cx, 1), round(b[1] - cy, 1), round(b[2], 1)]
    return flat


def main(out_dir):
    data = {}
    for key, label, args in PRESETS:
        j = os.path.join(out_dir, f"{key}.json")
        g = os.path.join(out_dir, f"{key}.gcode")
        wireprint.main(args + ["-o", g, "--preview", j])
        head = open(g).readline() + open(g).readlines()[1]
        data[key] = {"label": label, "cmd": "python3 wireprint.py " + " ".join(args),
                     "info": head.replace("; ", "").strip().split("\n")[-1], "seg": pack(j)}
    tpl = open(os.path.join(HERE, "preview_template.html")).read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    out = os.path.join(out_dir, "preview.html")
    open(out, "w").write(html)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
