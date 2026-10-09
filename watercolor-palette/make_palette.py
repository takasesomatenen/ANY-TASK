"""水彩用ミニハンディパレット (4x4マス) の STL を生成する。

使い方: python3 make_palette.py [マスの一辺mm]
依存: pip install trimesh manifold3d numpy
"""
import sys

import numpy as np
import trimesh
from manifold3d import Manifold

# ---- パラメータ (単位: mm) ----
CELL = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0  # マス内寸
ROWS, COLS = 4, 4
DEPTH = 5.0          # マスの深さ
INNER_WALL = 1.2     # マス間の仕切り厚 (0.4mmノズルで3周)
OUTER_WALL = 2.0     # 外周の壁厚
FLOOR = 1.5          # 底の厚み
OUTER_RADIUS = 3.0   # 外形の角丸
CELL_RADIUS = 2.0    # マスの角・底の丸み (絵の具が溜まりにくく洗いやすい)
SEGMENTS = 48

width = COLS * CELL + (COLS - 1) * INNER_WALL + 2 * OUTER_WALL
length = ROWS * CELL + (ROWS - 1) * INNER_WALL + 2 * OUTER_WALL
height = FLOOR + DEPTH


def rounded_rect_prism(w, l, h, r):
    """角丸の直方体 (原点中心, z=0..h)。"""
    hx, hy = w / 2 - r, l / 2 - r
    corners = [Manifold.cylinder(h, r, r, SEGMENTS).translate([x, y, 0])
               for x in (-hx, hx) for y in (-hy, hy)]
    return Manifold.batch_hull(corners)


def pocket(cx, cy):
    """底のフチが丸いマス (球と円柱のハル)。"""
    r = CELL_RADIUS
    half = CELL / 2 - r
    parts = []
    for dx in (-half, half):
        for dy in (-half, half):
            parts.append(Manifold.sphere(r, SEGMENTS).translate([cx + dx, cy + dy, FLOOR + r]))
            parts.append(
                Manifold.cylinder(height - FLOOR - r + 1.0, r, r, SEGMENTS)
                .translate([cx + dx, cy + dy, FLOOR + r])
            )
    return Manifold.batch_hull(parts)


body = rounded_rect_prism(width, length, height, OUTER_RADIUS)

pitch = CELL + INNER_WALL
x0 = -(COLS - 1) * pitch / 2
y0 = -(ROWS - 1) * pitch / 2
pockets = [pocket(x0 + c * pitch, y0 + r * pitch) for r in range(ROWS) for c in range(COLS)]
palette = body
for p in pockets:
    palette = palette - p

mesh = palette.to_mesh()
tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
out = f"watercolor_palette_4x4_{int(CELL)}mm.stl"
tm.export(out)
print(f"{out}: {width:.1f} x {length:.1f} x {height:.1f} mm, watertight={tm.is_watertight}, "
      f"cell volume ≈ {(CELL**2*DEPTH)/1000:.2f} ml")
