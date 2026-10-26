"""2段スリーブを 5 パーツの組み立て式にした STL を生成する (全部平置きで印刷)。

- kit_plate_top.stl     天板 (雫型の穴)
- kit_plate_middle.stl  中板 (雫型の穴)
- kit_plate_bottom.stl  底板 (穴なし)
- kit_side_bar.stl      側板 (同じものを 2 本印刷)。内側に板を差し込む溝つき

側板の溝に 3 枚の板の端を差し込み、接着剤で固定する。
使い方: python3 make_sleeve_kit.py
"""
import math

import numpy as np
import trimesh
from manifold3d import CrossSection, Manifold

from make_stack import HOLE_R, PAL_H, SEG, SIZE, to_trimesh

CLEAR_SIDE, CLEAR_TOP = 0.4, 0.3     # パレットとのすき間 (前と同じ)
PLATE_T = 1.6                        # 板の厚み
BAR_T = 3.0                          # 側板の厚み
GROOVE_D = 1.2                       # 溝の深さ
GROOVE_CLEAR = 0.2                   # 溝の高さ方向のすき間 (板厚 + 0.2)
LENGTH = SIZE                        # スライド方向の長さ

inner_w = SIZE + 2 * CLEAR_SIDE                  # 68.4 パレットが通る幅
tier_h = PAL_H + 2 * CLEAR_TOP                   # 7.1
total_h = 3 * PLATE_T + 2 * tier_h               # 19.0
plate_w = inner_w + 2 * (GROOVE_D - 0.1)         # 溝の奥に 0.1mm 余裕
outer_w = inner_w + 2 * BAR_T
plate_y = [0.0, PLATE_T + tier_h, 2 * (PLATE_T + tier_h)]  # 各板の下面の高さ


def teardrop(length):
    """雫型の穴 (とんがりは +Y = スライド方向の片側)。make_stack.py と同じ形。"""
    circle = CrossSection.circle(HOLE_R, SEG)
    apex = CrossSection.square([0.01, 0.01], center=True).translate([0, HOLE_R * math.sqrt(2)])
    tip = CrossSection.batch_hull([circle, apex])
    flat_y = min(HOLE_R * math.sqrt(2) - 3.0, length / 2 - 3.0)
    return tip - CrossSection.square([HOLE_R * 4, HOLE_R], center=True).translate([0, flat_y + HOLE_R / 2])


def plate(with_hole):
    """板 (平置き: XY = 板の面, Y = スライド方向)。"""
    cs = CrossSection.square([plate_w, LENGTH], center=True)
    if with_hole:
        cs = cs - teardrop(LENGTH)
    return Manifold.extrude(cs, PLATE_T)


def side_bar():
    """側板 (平置き: 外側の面が下、溝が上を向く)。X = 高さ方向, Y = スライド方向。"""
    bar = Manifold.cube([total_h, LENGTH, BAR_T])
    for y0 in plate_y:
        g0 = max(y0 - GROOVE_CLEAR / 2, -1)
        g1 = y0 + PLATE_T + GROOVE_CLEAR / 2
        if y0 == plate_y[-1]:
            g1 = total_h + 1
        if y0 == 0:
            g0 = -1
        groove = Manifold.cube([g1 - g0, LENGTH + 2, GROOVE_D + 1]).translate([g0, -1, BAR_T - GROOVE_D])
        bar = bar - groove
    return bar.translate([-total_h / 2, -LENGTH / 2, 0])


def assembly():
    """確認用の組み立て状態 (Z = 高さ, Y = スライド方向)。"""
    parts = {}
    for name, y0, hole in (("bottom", plate_y[0], False), ("middle", plate_y[1], True), ("top", plate_y[2], True)):
        parts[name] = plate(hole).translate([0, 0, y0])
    bar = side_bar()  # 外側の面 z=0, 溝が +z。これを立てて左右に置く
    # bar の X(高さ) -> Z, Z(厚み) -> 内向き X
    for side, rot in (("left", [0, 90, 0]), ("right", [0, -90, 0])):
        b = bar.rotate(rot)
        lo, hi = np.array(b.bounding_box()[:3]), np.array(b.bounding_box()[3:])
        b = b.translate([0, 0, -lo[2]])
        if side == "left":
            b = b.translate([-outer_w / 2 - lo[0], 0, 0])
        else:
            b = b.translate([outer_w / 2 - hi[0], 0, 0])
        parts[side] = b
    return parts


if __name__ == "__main__":
    outputs = {
        "kit_plate_top.stl": plate(True),
        "kit_plate_middle.stl": plate(True),
        "kit_plate_bottom.stl": plate(False),
        "kit_side_bar.stl": side_bar(),
    }
    for fn, m in outputs.items():
        t = to_trimesh(m)
        t.export(fn)
        print(f"{fn}: {np.round(t.extents, 1).tolist()} mm, watertight={t.is_watertight}")
    print(f"組み立て後: 幅 {outer_w:.1f} x 高さ {total_h:.1f} x 長さ {LENGTH:.1f} mm, 各段内寸 {inner_w:.1f} x {tier_h:.1f}")
