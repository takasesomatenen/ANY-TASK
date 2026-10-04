#!/usr/bin/env python3
"""
Wire-print (空中プリント) G-code generator.

普通のスライサーのように「層を積む」のではなく、
  1. ノズルを Z 方向にだけ動かしながら押し出して「柱」を立てる
  2. 柱の上から斜めに降りて隣の柱の根元へ（三角形のブレース）
  3. 全部の柱が立ったら、柱の頂点どうしを空中で水平に「橋」でつなぐ
を繰り返して、ワイヤーフレーム状のオブジェを直接 G-code で描きます。

Usage:
  python3 wireprint.py --shape tower -o tower.gcode
  python3 wireprint.py --shape grid  -o grid.gcode --preview grid.json
  python3 wireprint.py --help
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field

Vec = tuple[float, float, float]


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
@dataclass
class Settings:
    # printer
    printer: str = "generic"      # generic | a1mini
    bed_x: float = 220.0
    bed_y: float = 220.0
    nozzle_temp: int = 210
    bed_temp: int = 60
    filament_d: float = 1.75
    retract: float = 0.8          # mm, 0 to disable (direct drive ~0.8, bowden ~4)
    # collision model of the hotend
    nozzle_clearance: float = 5.0  # ノズル先端〜ヒーターブロック下面の高さ (mm)
    hotend_radius: float = 12.0    # ヒーターブロック/ファンダクトの水平方向の半径 (mm)
    # base (normal printing to anchor the wires)
    base_layers: int = 3
    base_layer_h: float = 0.25
    base_line_w: float = 0.45
    base_speed: float = 25.0
    # wire printing
    level_h: float = 4.5           # 1段の高さ（柱の長さ）
    strand_d: float = 0.5          # 空中の糸の太さ相当で押し出し量を計算
    up_speed: float = 3.0          # 柱を立てる速度 mm/s
    down_speed: float = 6.0        # 斜めに降りる速度
    flat_speed: float = 6.0        # 橋をかける速度
    travel_speed: float = 120.0
    up_flow: float = 1.0
    down_flow: float = 0.9
    flat_flow: float = 1.0
    top_delay: float = 0.8         # 柱の頂点で冷やす秒数
    bottom_delay: float = 0.3      # 根元でくっつける秒数
    flat_delay: float = 0.3        # 橋の節点での秒数
    knot: float = 0.15             # 節点で追加する押し出し量 (mm of filament)
    overshoot: float = 0.3         # 柱は少し高めに引き上げる（垂れ補正）
    z_hop: float = 1.0


# --------------------------------------------------------------------------
# Shapes: each shape provides nodes for every level, the order the pillars
# are printed (path) and the polylines used for the horizontal bridges.
# --------------------------------------------------------------------------
@dataclass
class Shape:
    levels: int
    nodes: list[list[tuple[float, float]]]   # nodes[k][i] -> (x, y) at level k
    path: list[int]                            # pillar order inside a level
    bridges: list[list[int]]                   # polylines of node indices at a level top
    base: list[list[list[tuple[float, float]]]] = field(default_factory=list)  # [layer][polyline][pt]


def circle(cx, cy, r, n=120):
    return [(cx + r * math.cos(2 * math.pi * t / n), cy + r * math.sin(2 * math.pi * t / n)) for t in range(n + 1)]


def tower_shape(s: Settings, n=16, radius=22.0, bulge=8.0, twist_deg=0.0, levels=14) -> Shape:
    """円筒状のラティス・タワー。半径が高さに応じて膨らむ花瓶のような形。"""
    cx, cy = s.bed_x / 2, s.bed_y / 2
    nodes = []
    for k in range(levels + 1):
        t = k / levels
        r = radius + bulge * math.sin(math.pi * t)
        a0 = math.radians(twist_deg) * k
        nodes.append([(cx + r * math.cos(a0 + 2 * math.pi * i / n),
                       cy + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)])
    path = list(range(n))
    ring = list(range(n)) + [0]
    # base: annulus of concentric loops around the first ring
    loops = []
    rr = radius - 2.5
    while rr <= radius + 2.5 + 1e-9:
        loops.append(circle(cx, cy, rr))
        rr += s.base_line_w
    base = [loops for _ in range(s.base_layers)]
    return Shape(levels, nodes, path, [ring], base)


def grid_shape(s: Settings, cols=4, rows=4, spacing=12.0, taper=0.0, levels=10) -> Shape:
    """動画のような柱のグリッド。各段の頂点を縦横の橋でつなぐ。taper>0 でピラミッド状に。"""
    cx, cy = s.bed_x / 2, s.bed_y / 2
    nodes = []
    for k in range(levels + 1):
        sp = spacing * (1 - taper * k / levels)
        ox, oy = cx - sp * (cols - 1) / 2, cy - sp * (rows - 1) / 2
        nodes.append([(ox + c * sp, oy + r * sp) for r in range(rows) for c in range(cols)])
    idx = lambda c, r: r * cols + c
    path = []
    for r in range(rows):  # serpentine
        cs = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
        path += [idx(c, r) for c in cs]
    bridges = []
    # rows: one serpentine polyline would cross gaps, so use separate lines
    for r in range(rows):
        cs = list(range(cols)) if r % 2 == 0 else list(range(cols - 1, -1, -1))
        bridges.append([idx(c, rows - 1 - r) for c in cs])  # start near where the path ended
    for c in range(cols):
        rs = list(range(rows)) if c % 2 == 0 else list(range(rows - 1, -1, -1))
        bridges.append([idx(c, r) for r in rs])
    # base: solid plate under the grid
    m = 3.0
    x0, x1 = cx - spacing * (cols - 1) / 2 - m, cx + spacing * (cols - 1) / 2 + m
    y0, y1 = cy - spacing * (rows - 1) / 2 - m, cy + spacing * (rows - 1) / 2 + m
    base = []
    w = s.base_line_w
    for layer in range(s.base_layers):
        polys = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]
        zig = []
        if layer % 2 == 0:
            x, flip = x0 + w, False
            while x < x1 - w / 2:
                zig += [(x, y1 - w), (x, y0 + w)] if flip else [(x, y0 + w), (x, y1 - w)]
                x += w
                flip = not flip
        else:
            y, flip = y0 + w, False
            while y < y1 - w / 2:
                zig += [(x1 - w, y), (x0 + w, y)] if flip else [(x0 + w, y), (x1 - w, y)]
                y += w
                flip = not flip
        polys.append(zig)
        base.append(polys)
    return Shape(levels, nodes, path, bridges, base)


# --------------------------------------------------------------------------
# G-code writer with a simple hotend collision check
# --------------------------------------------------------------------------
class Writer:
    def __init__(self, s: Settings):
        self.s = s
        self.out: list[str] = []
        self.pos: Vec = (0.0, 0.0, 0.0)
        self.retracted = False
        self.segments: list[dict] = []      # for preview
        self.printed: list[Vec] = []        # high points of printed wires (for collision check)
        self.collisions: list[str] = []
        self.e_total = 0.0
        self.time = 0.0
        fa = math.pi * (s.filament_d / 2) ** 2
        self.e_wire = math.pi * (s.strand_d / 2) ** 2 / fa
        self.e_base = s.base_line_w * s.base_layer_h / fa

    def g(self, line: str):
        self.out.append(line)

    def comment(self, text: str):
        self.out.append(f"; {text}")

    def _check(self, a: Vec, b: Vec):
        s = self.s
        L = math.dist(a, b)
        steps = max(1, int(L / 1.0))
        for i in range(steps + 1):
            t = i / steps
            p = tuple(a[j] + (b[j] - a[j]) * t for j in range(3))
            for q in self.printed:
                if q[2] > p[2] + s.nozzle_clearance and math.hypot(q[0] - p[0], q[1] - p[1]) < s.hotend_radius:
                    self.collisions.append(
                        f"nozzle at ({p[0]:.1f},{p[1]:.1f},{p[2]:.1f}) would hit wire at ({q[0]:.1f},{q[1]:.1f},{q[2]:.1f})")
                    return

    def move(self, p: Vec, speed: float, e_per_mm: float = 0.0, kind: str = "travel"):
        a = self.pos
        L = math.dist(a, p)
        if L < 1e-6:
            return
        if kind not in ("base",):
            self._check(a, p)
        f = speed * 60
        if e_per_mm > 0:
            if self.retracted:
                self.g(f"G1 E{self.s.retract:.3f} F1800")
                self.retracted = False
            e = e_per_mm * L
            self.e_total += e
            self.g(f"G1 X{p[0]:.3f} Y{p[1]:.3f} Z{p[2]:.3f} E{e:.5f} F{f:.0f}")
        else:
            self.g(f"G0 X{p[0]:.3f} Y{p[1]:.3f} Z{p[2]:.3f} F{f:.0f}")
        self.time += L / speed
        self.segments.append({"t": kind, "a": [round(v, 2) for v in a], "b": [round(v, 2) for v in p]})
        self.pos = p

    def retract(self):
        if self.s.retract > 0 and not self.retracted:
            self.g(f"G1 E{-self.s.retract:.3f} F2400")
            self.retracted = True

    def dwell(self, sec: float):
        if sec > 0:
            self.g(f"G4 P{int(sec * 1000)}")
            self.time += sec

    def knot(self, amount: float):
        if amount > 0:
            if self.retracted:
                self.g(f"G1 E{self.s.retract:.3f} F1800")
                self.retracted = False
            self.g(f"G1 E{amount:.4f} F120")
            self.e_total += amount
            self.time += amount / 2

    def travel_to(self, p: Vec):
        """Lift, travel above everything already printed nearby, then lower."""
        s = self.s
        if math.dist(self.pos, p) < 1e-6:
            return
        self.retract()
        safe_z = max(self.pos[2], p[2]) + s.z_hop
        self.move((self.pos[0], self.pos[1], safe_z), s.travel_speed / 4)
        self.move((p[0], p[1], safe_z), s.travel_speed)
        self.move(p, s.travel_speed / 4)


# Printer profiles: values that differ from Settings defaults.
PRINTERS = {
    "generic": {},
    # Bambu Lab A1 mini: 180x180x180, bed slinger, compact hotend.
    # 背の低い柱から試すため、1段 3.5 mm / クリアランス 4 mm と控えめにしている。
    "a1mini": dict(bed_x=180.0, bed_y=180.0, nozzle_temp=220, bed_temp=60, retract=0.8,
                   nozzle_clearance=4.0, hotend_radius=10.0, level_h=3.5, travel_speed=80.0),
}


def fan(s: Settings, value: int) -> str:
    # Bambu firmware addresses the part-cooling fan as P1
    return f"M106 P1 S{value}" if s.printer == "a1mini" else f"M106 S{value}"


def fan_off(s: Settings) -> str:
    return "M106 P1 S0" if s.printer == "a1mini" else "M107"


def start_gcode(s: Settings) -> list[str]:
    if s.printer == "a1mini":
        return [
            "; ---- start (Bambu Lab A1 mini) ----",
            "; filament must already be loaded in the external spool / AMS lite slot in use",
            "G90 ; absolute XYZ",
            "M83 ; relative E",
            f"M140 S{s.bed_temp}",
            "M104 S150 ; warm nozzle without oozing while homing",
            "G28 ; home all axes",
            f"M190 S{s.bed_temp}",
            f"M109 S{s.nozzle_temp}",
            fan_off(s),
            "G0 Z2 F600",
            "G0 X20 Y3 F6000",
            "G1 Z0.3 F600",
            "G1 X100 Y3 E8 F1200 ; prime line along the front edge",
            "G1 X100 Y3.5 F1200",
            "G1 X20 Y3.5 E6 F1200",
            "G1 E-0.8 F2400",
            "G0 Z2 F600",
        ]
    return [
        "; ---- start (generic Marlin / Klipper) ----",
        "G90 ; absolute XYZ",
        "M83 ; relative E",
        f"M140 S{s.bed_temp}",
        f"M104 S{s.nozzle_temp}",
        "G28 ; home",
        f"M190 S{s.bed_temp}",
        f"M109 S{s.nozzle_temp}",
        fan_off(s),
        "G92 E0",
        "G0 Z2 F600",
        "G0 X5 Y20 F6000",
        "G1 Z0.3 F600",
        "G1 X5 Y120 E10 F1200 ; prime line",
        "G1 X5.5 Y120 F1200",
        "G1 X5.5 Y20 E8 F1200",
        "G1 E-0.8 F2400",
        "G0 Z2 F600",
    ]


def end_gcode(s: Settings, top_z: float) -> list[str]:
    if s.printer == "a1mini":
        return [
            "; ---- end ----",
            "G1 E-2 F2400",
            f"G0 Z{min(top_z + 15, 175):.2f} F600",
            "G0 X0 Y170 F4000 ; present the bed slowly (the bed is the Y axis)",
            "M104 S0",
            "M140 S0",
            fan_off(s),
            "M84",
        ]
    return [
        "; ---- end ----",
        "G1 E-2 F2400",
        f"G0 Z{min(top_z + 20, 250):.2f} F600",
        f"G0 X{s.bed_x / 2:.1f} Y{s.bed_y - 10:.1f} F6000",
        "M104 S0",
        "M140 S0",
        fan_off(s),
        "M84",
    ]


def generate(shape: Shape, s: Settings) -> Writer:
    w = Writer(s)
    for line in start_gcode(s):
        w.g(line)
    w.pos = (20.0, 3.5, 2.0) if s.printer == "a1mini" else (5.5, 20.0, 2.0)
    w.retracted = True

    # ---- base: printed normally so the pillars have something to stand on
    z = 0.0
    for li, layer in enumerate(shape.base):
        z = round(s.base_layer_h * (li + 1), 3)
        w.comment(f"BASE layer {li + 1}")
        if li == 1:
            w.g(fan(s, 128))
        for poly in layer:
            if len(poly) < 2:
                continue
            w.travel_to((poly[0][0], poly[0][1], z))
            for x, y in poly[1:]:
                w.move((x, y, z), s.base_speed if li else s.base_speed * 0.6, w.e_base, "base")
    base_top = z

    w.comment("WIRE PRINTING")
    w.g(fan(s, 255) + " ; full fan for wires")
    # Base nodes count as touch-down points (nothing tall there yet)
    for k in range(shape.levels):
        z0 = base_top + k * s.level_h
        z1 = z0 + s.level_h
        lo, hi = shape.nodes[k], shape.nodes[k + 1]
        w.comment(f"LEVEL {k + 1}/{shape.levels}  z {z0:.2f} -> {z1:.2f}")

        # 1) pillars + diagonal braces (zig-zag: up, down, up, down ...)
        first = shape.path[0]
        w.travel_to((lo[first][0], lo[first][1], z0))
        for j, i in enumerate(shape.path):
            w.knot(s.knot)
            w.dwell(s.bottom_delay)
            top = (hi[i][0], hi[i][1], z1)
            w.move((top[0], top[1], z1 + s.overshoot), s.up_speed, w.e_wire * s.up_flow, "up")
            w.dwell(s.top_delay)
            w.move(top, s.up_speed, 0, "up")
            w.printed.append(top)
            if j + 1 < len(shape.path):
                n = shape.path[j + 1]
                w.move((lo[n][0], lo[n][1], z0), s.down_speed, w.e_wire * s.down_flow, "down")

        # 2) horizontal bridges between the pillar tops (in the air)
        for poly in shape.bridges:
            p0 = hi[poly[0]]
            w.travel_to((p0[0], p0[1], z1))
            w.knot(s.knot)
            w.dwell(s.flat_delay)
            for i in poly[1:]:
                w.move((hi[i][0], hi[i][1], z1), s.flat_speed, w.e_wire * s.flat_flow, "bridge")
                w.knot(s.knot * 0.5)
                w.dwell(s.flat_delay)
        w.retract()

    top_z = base_top + shape.levels * s.level_h
    for line in end_gcode(s, top_z):
        w.g(line)
    w.top_z = top_z
    return w


def main(argv=None):
    ap = argparse.ArgumentParser(description="Wire-print G-code generator (pillars + aerial bridges)")
    ap.add_argument("--shape", choices=["tower", "grid"], default="tower")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--preview", help="write toolpath JSON for the 3D preview")
    ap.add_argument("--levels", type=int)
    ap.add_argument("--level-h", type=float, help="height of one level / pillar (mm)")
    # tower
    ap.add_argument("--n", type=int, default=16, help="tower: pillars around")
    ap.add_argument("--radius", type=float, default=22.0)
    ap.add_argument("--bulge", type=float, default=8.0)
    ap.add_argument("--twist", type=float, default=0.0, help="tower: degrees of twist per level")
    # grid
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--spacing", type=float, default=12.0)
    ap.add_argument("--taper", type=float, default=0.0, help="grid: 0..0.9 shrink toward the top")
    # printer
    ap.add_argument("--printer", choices=sorted(PRINTERS), default="generic",
                    help="a1mini = Bambu Lab A1 mini profile")
    ap.add_argument("--bed", type=float, nargs=2, metavar=("X", "Y"))
    ap.add_argument("--nozzle-temp", type=int)
    ap.add_argument("--bed-temp", type=int)
    ap.add_argument("--retract", type=float)
    ap.add_argument("--clearance", type=float, help="nozzle tip to heater block bottom (mm)")
    ap.add_argument("--hotend-radius", type=float)
    a = ap.parse_args(argv)

    s = Settings(printer=a.printer, **PRINTERS[a.printer])
    if a.level_h: s.level_h = a.level_h
    if a.bed: s.bed_x, s.bed_y = a.bed
    if a.nozzle_temp: s.nozzle_temp = a.nozzle_temp
    if a.bed_temp is not None: s.bed_temp = a.bed_temp
    if a.retract is not None: s.retract = a.retract
    if a.clearance: s.nozzle_clearance = a.clearance
    if a.hotend_radius: s.hotend_radius = a.hotend_radius

    if a.shape == "tower":
        shape = tower_shape(s, a.n, a.radius, a.bulge, a.twist, a.levels or 14)
    else:
        shape = grid_shape(s, a.cols, a.rows, a.spacing, a.taper, a.levels or 10)

    w = generate(shape, s)
    out = a.output or f"{a.shape}.gcode"
    header = [
        f"; wireprint.py  shape={a.shape}  levels={shape.levels}  level_h={s.level_h}",
        f"; height {w.top_z:.1f} mm, filament {w.e_total / 1000:.2f} m, est. time {w.time / 60:.0f} min",
    ]
    with open(out, "w") as f:
        f.write("\n".join(header + w.out) + "\n")
    print("\n".join(header))
    print(f"wrote {out}  ({len(w.out)} lines)")
    if a.preview:
        with open(a.preview, "w") as f:
            json.dump({"shape": a.shape, "bed": [s.bed_x, s.bed_y], "height": w.top_z,
                       "segments": w.segments}, f, separators=(",", ":"))
        print(f"wrote {a.preview}")
    if w.collisions:
        print(f"\nWARNING: {len(w.collisions)} possible hotend collisions, e.g.:", file=sys.stderr)
        for c in w.collisions[:5]:
            print("  " + c, file=sys.stderr)
        print("-> lower --level-h, or check --clearance / --hotend-radius for your printer", file=sys.stderr)
        return 2
    print("collision check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
