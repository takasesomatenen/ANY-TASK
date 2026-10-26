"""2段スリーブ + 無印クリームケースL用の穴あきパレットの STL を生成する。

- holed_palette_15mm.stl : 中央にクリームケースが通る穴、四隅に 4 マス
- sleeve_2tier_15mm.stl  : 断面「日」の字の 2 段スリーブ。天板と中段の仕切りに
                           同じ穴、底板はただの板。縦置き印刷の向きで出力
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
OUTER_WALL, INNER_WALL = 2.0, 1.2
OUTER_R = 3.0
CELL_R = 2.0                          # マスの角と底フチの丸み

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


def round_all(cs, r):
    """凸角・凹角の両方を半径 r で丸める。"""
    return (cs.offset(-r, JoinType.Round, circular_segments=SEG)
              .offset(2 * r, JoinType.Round, circular_segments=SEG)
              .offset(-r, JoinType.Round, circular_segments=SEG))


# ================= 穴あきパレット =================
def holed_palette():
    body = Manifold.extrude(rounded_square(SIZE, SIZE, OUTER_R), PAL_H)
    ring_r = HOLE_R + INNER_WALL
    inner = SIZE / 2 - OUTER_WALL
    pockets = []
    for sx in (1, -1):
        for sy in (1, -1):
            quad = CrossSection.square([inner - INNER_WALL / 2] * 2).translate([INNER_WALL / 2] * 2)
            quad = quad.scale([sx, sy])
            cell = round_all(quad - CrossSection.circle(ring_r, SEG), CELL_R)
            # 底フチの丸み: 段階的に内側へオフセットした柱を重ねる (階段状に近似)
            steps = 10
            for i in range(steps):
                z0 = FLOOR + CELL_R * i / steps
                dz = CELL_R - CELL_R * (i + 0.5) / steps
                inset = CELL_R - math.sqrt(max(CELL_R**2 - dz**2, 0))
                layer = cell.offset(-inset, JoinType.Round, circular_segments=SEG)
                pockets.append(Manifold.extrude(layer, PAL_H + 1 - z0).translate([0, 0, z0]))
            pockets.append(Manifold.extrude(cell, PAL_H).translate([0, 0, FLOOR + CELL_R]))
    hole = Manifold.cylinder(PAL_H + 2, HOLE_R, HOLE_R, SEG).translate([0, 0, -1])
    out = body - hole
    for p in pockets:
        out = out - p
    return out.simplify(0.005)  # 近接した頂点をまとめて縮退面をなくす


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
    tip = CrossSection.batch_hull([circle, apex])
    # とんがりの先は平らに切って、筒の端に 3mm 以上の壁を残す (短いブリッジで済む)
    flat_y = min(HOLE_R * math.sqrt(2) - 3.0, length / 2 - 3.0)
    tip = tip - CrossSection.square([HOLE_R * 4, HOLE_R], center=True).translate([0, flat_y + HOLE_R / 2])
    teardrop = Manifold.extrude(tip, outer_h)            # XY 平面の形を Z 方向に押し出し
    teardrop = teardrop.rotate([90, 0, 0])               # 穴の軸を Y に、とんがりを +Z に
    y_start = tiers[0] + tier_h / 2 - 0.01               # 中段の仕切りの下面から上に開ける (底板は残す)
    teardrop = teardrop.translate([0, y_start + outer_h, length / 2])
    body = body - (teardrop ^ Manifold.cube([outer_w * 2, outer_h, length * 2], center=True)
                   .translate([0, y_start + outer_h / 2, length / 2]))
    return body.simplify(0.005), (outer_w, outer_h, length, tiers, tier_h)


if __name__ == "__main__":
    p = to_trimesh(holed_palette())
    p.export("holed_palette_15mm.stl")
    print(f"holed_palette_15mm.stl: {SIZE} x {SIZE} x {PAL_H} mm, hole Ø{2*HOLE_R}, watertight={p.is_watertight}")
    s_man, (w, h, l, tiers, th) = sleeve_2tier()
    s = to_trimesh(s_man)
    s.export("sleeve_2tier_15mm.stl")
    print(f"sleeve_2tier_15mm.stl: 断面 {w:.1f} x {h:.1f} mm, 高さ {l:.1f} mm, 各段内寸 {SIZE+2*CLEAR_SIDE:.1f} x {th:.1f}, "
          f"watertight={s.is_watertight}")
    print("case top above sleeve top:", round(WALL + 24.0 - h, 2), "mm")
