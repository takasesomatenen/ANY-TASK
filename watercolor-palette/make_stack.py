"""15mm マスのパレットを 2 枚入れる 2 段スリーブの STL を生成する。

- sleeve_2tier_15mm.stl : 断面「日」の字の 2 段スリーブ。天板と中段の仕切りに
                          雫型の穴、底板はただの板。縦置き印刷の向きで出力
パレットを抜いた空のスリーブには、無印良品のクリームケース L が穴に
はまって立つ (滑り止めの固定台として流用できる)。
使い方: python3 make_stack.py
依存: pip install trimesh manifold3d numpy
"""
import math

import numpy as np
import trimesh
from manifold3d import CrossSection, JoinType, Manifold

SEG = 96

# ---- クリームケース (無印良品 クリームケース L: 直径約50 x 高さ約24mm) ----
CASE_D = 50.0
HOLE_CLEAR = 0.5                      # 穴の半径方向のすき間
HOLE_R = CASE_D / 2 + HOLE_CLEAR      # = 25.5

# ---- パレット (15mm マス版と同じ外形) ----
SIZE = 4 * 15.0 + 3 * 1.2 + 2 * 2.0   # 67.6
FLOOR, DEPTH = 1.5, 5.0
PAL_H = FLOOR + DEPTH                 # 6.5

# ---- スリーブ ----
CLEAR_SIDE, CLEAR_TOP = 0.4, 0.3
WALL = 1.6
SLEEVE_R = 1.5
CHAMFER = 0.6


def to_trimesh(man):
    m = man.to_mesh()
    return trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts))


def rounded_square(w, h, r):
    return CrossSection.square([w - 2 * r, h - 2 * r], center=True).offset(r, JoinType.Round, circular_segments=SEG)


# ================= 2段スリーブ =================
def sleeve_2tier():
    inner_w = SIZE + 2 * CLEAR_SIDE
    tier_h = PAL_H + 2 * CLEAR_TOP
    outer_w = inner_w + 2 * WALL
    outer_h = 3 * WALL + 2 * tier_h
    length = SIZE
    # 断面 = XY (ベッド面)、筒の軸 (スライド方向) = Z。Y- が底板、Y+ が天板
    body = Manifold.extrude(rounded_square(outer_w, outer_h, SLEEVE_R), length)
    y_bottom = -outer_h / 2
    tiers = []
    for k in range(2):
        yc = y_bottom + WALL + tier_h / 2 + k * (tier_h + WALL)
        tiers.append(yc)
        tunnel = Manifold.cube([inner_w, tier_h, length + 2], center=True).translate([0, yc, length / 2])
        body = body - tunnel
        for z_end, z_in in ((-0.005, CHAMFER), (length + 0.005, length - CHAMFER)):
            a = Manifold.cube([inner_w + 2 * CHAMFER, tier_h + 2 * CHAMFER, 0.01], center=True).translate([0, yc, z_end])
            b = Manifold.cube([inner_w, tier_h, 0.01], center=True).translate([0, yc, z_in])
            body = body - Manifold.batch_hull([a, b])
    # 天板と中段に穴。縦置き印刷で穴の上側が垂れないよう、上端だけ 45° のとんがりにする
    circle = CrossSection.circle(HOLE_R, SEG)
    apex = CrossSection.square([0.01, 0.01], center=True).translate([0, HOLE_R * math.sqrt(2)])
    tip = CrossSection.batch_hull([circle, apex])       # 先端まで鋭くとがった雫型
    # 雫の先 (中心から R√2) まで入るよう、穴を筒の中で下寄せし上下の残り壁を揃える
    hole_z = (length - HOLE_R * math.sqrt(2) + HOLE_R) / 2
    teardrop = Manifold.extrude(tip, outer_h)            # XY 平面の形を Z 方向に押し出し
    teardrop = teardrop.rotate([90, 0, 0])               # 穴の軸を Y に、とんがりを +Z に
    y_start = tiers[0] + tier_h / 2 - 0.01               # 中段の仕切りの下面から上に開ける (底板は残す)
    teardrop = teardrop.translate([0, y_start + outer_h, hole_z])
    body = body - (teardrop ^ Manifold.cube([outer_w * 2, outer_h, length * 2], center=True)
                   .translate([0, y_start + outer_h / 2, length / 2]))
    return body.simplify(0.005), (outer_w, outer_h, length, tiers, tier_h)


if __name__ == "__main__":
    s_man, (w, h, l, tiers, th) = sleeve_2tier()
    s = to_trimesh(s_man)
    s.export("sleeve_2tier_15mm.stl")
    print(f"sleeve_2tier_15mm.stl: 断面 {w:.1f} x {h:.1f} mm, 高さ {l:.1f} mm, 各段内寸 {SIZE+2*CLEAR_SIDE:.1f} x {th:.1f}, "
          f"watertight={s.is_watertight}")
    print("case top above sleeve top:", round(WALL + 24.0 - h, 2), "mm")
