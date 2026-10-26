"""パレットを差し込むマッチ箱式のスリーブ (断面ロの字の筒) の STL を生成する。

縦置き印刷用: 筒の軸 (= パレットを滑らせる方向) を Z 軸にしてあり、
ロの字の断面がそのままベッドに乗る向きで出力する。

使い方: python3 make_sleeve.py [マスの一辺mm]   (既定 15)
依存: pip install trimesh manifold3d numpy
"""
import sys

import numpy as np
import trimesh
from manifold3d import Manifold

# ---- パレット側の寸法 (make_palette.py と同じ値) ----
CELL = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
ROWS, COLS = 4, 4
INNER_WALL = 1.2
OUTER_WALL = 2.0
PALETTE_H = 1.5 + 5.0  # 底 + 深さ
PALETTE_W = COLS * CELL + (COLS - 1) * INNER_WALL + 2 * OUTER_WALL
PALETTE_L = ROWS * CELL + (ROWS - 1) * INNER_WALL + 2 * OUTER_WALL

# ---- スリーブのパラメータ (単位: mm) ----
CLEAR_SIDE = 0.4     # 左右それぞれのすき間
CLEAR_TOP = 0.3      # 上下それぞれのすき間
WALL = 1.6           # 壁厚 (0.4mmノズルで4周)
OUTER_RADIUS = 1.5   # 外側の角丸 (断面)
CHAMFER = 0.6        # 入口の内側面取り (差し込みやすさ + エレファントフット対策)
LENGTH = PALETTE_L   # 筒の長さ = パレットと同じ長さ
SEGMENTS = 48

inner_w = PALETTE_W + 2 * CLEAR_SIDE
inner_h = PALETTE_H + 2 * CLEAR_TOP
outer_w = inner_w + 2 * WALL
outer_h = inner_h + 2 * WALL


def rounded_prism(w, h, length, r):
    hx, hy = w / 2 - r, h / 2 - r
    corners = [Manifold.cylinder(length, r, r, SEGMENTS).translate([x, y, 0])
               for x in (-hx, hx) for y in (-hy, hy)]
    return Manifold.batch_hull(corners)


def slab(w, h, z, t=0.01):
    return Manifold.cube([w, h, t], center=True).translate([0, 0, z])


body = rounded_prism(outer_w, outer_h, LENGTH, OUTER_RADIUS)
hole = Manifold.cube([inner_w, inner_h, LENGTH + 2], center=True).translate([0, 0, LENGTH / 2])
# 両端の入口を 45° に広げる
flare = [
    Manifold.batch_hull([slab(inner_w + 2 * CHAMFER + 0.02, inner_h + 2 * CHAMFER + 0.02, z_end),
                         slab(inner_w, inner_h, z_in)])
    for z_end, z_in in ((-0.005, CHAMFER), (LENGTH + 0.005, LENGTH - CHAMFER))
]
sleeve = body - hole - flare[0] - flare[1]

mesh = sleeve.to_mesh()
tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
out = f"watercolor_sleeve_4x4_{int(CELL)}mm.stl"
tm.export(out)
print(f"{out}: 断面 {outer_w:.1f} x {outer_h:.1f} mm, 高さ(長さ) {LENGTH:.1f} mm, "
      f"内寸 {inner_w:.1f} x {inner_h:.1f} mm (パレット {PALETTE_W:.1f} x {PALETTE_H:.1f}), "
      f"watertight={tm.is_watertight}")
