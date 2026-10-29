#!/usr/bin/env python3
"""Generate Curlbook SVG logos: 3D blocky pixel text with a PCB / hardware palette.

Outputs (into app/static/):
  logo.svg           full logo: gold blocks on a green circuit board with traces,
                     vias, mounting holes and an edge connector
  logo-wordmark.svg  blocks only, transparent background (used in the top bar)
  logo-icon.svg      IC-chip icon with a blocky "C" (used as favicon)

Run:  python3 tools/gen_logo.py
"""
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "static")

# 5x7 pixel font -------------------------------------------------------------
GLYPHS = {
    "C": [".####",
          "#....",
          "#....",
          "#....",
          "#....",
          "#....",
          ".####"],
    "U": ["#...#",
          "#...#",
          "#...#",
          "#...#",
          "#...#",
          "#...#",
          ".###."],
    "R": ["####.",
          "#...#",
          "#...#",
          "####.",
          "#.#..",
          "#..#.",
          "#...#"],
    "L": ["#....",
          "#....",
          "#....",
          "#....",
          "#....",
          "#....",
          "#####"],
    "B": ["####.",
          "#...#",
          "#...#",
          "####.",
          "#...#",
          "#...#",
          "####."],
    "O": [".###.",
          "#...#",
          "#...#",
          "#...#",
          "#...#",
          "#...#",
          ".###."],
    "K": ["#...#",
          "#..#.",
          "#.#..",
          "##...",
          "#.#..",
          "#..#.",
          "#...#"],
}
GW, GH, GAP = 5, 7, 1

# Hardware palette: gold-plated pads on green solder mask --------------------
GOLD_FRONT = [("0", "#fff1b0"), ("0.35", "#f6c955"), ("0.75", "#e0a234"), ("1", "#b77a1e")]
GOLD_TOP = "#ffe9a6"
GOLD_SIDE = [("0", "#a76a18"), ("1", "#6e430c")]
GOLD_EDGE = "#5a3507"
PCB_TOP, PCB_BOTTOM, PCB_EDGE = "#11804f", "#0a5134", "#063722"
TRACE = "#2cb46d"
SILK = "#e9f5ee"
HOLE = "#07140e"
CHIP_BODY, CHIP_EDGE = "#1c2024", "#000000"


def f(v):
    """Compact number formatting for SVG output."""
    v = round(v, 2)
    return str(int(v)) if v == int(v) else f"{v:g}"


def pts(*xy):
    return " ".join(f"{f(x)},{f(y)}" for x, y in xy)


def text_pixels(text):
    """Return set of (col, row) pixels and total width in cells."""
    pixels, col = set(), 0
    for i, ch in enumerate(text):
        rows = GLYPHS[ch]
        for r, line in enumerate(rows):
            for c, cell in enumerate(line):
                if cell == "#":
                    pixels.add((col + c, r))
        col += GW + (GAP if i < len(text) - 1 else 0)
    return pixels, col


def gradient(gid, stops, x1, y1, x2, y2):
    s = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
            f'x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}">{s}</linearGradient>')


def voxel_defs(prefix, oy, height, ox, width):
    return (gradient(f"{prefix}front", GOLD_FRONT, 0, oy, 0, oy + height)
            + gradient(f"{prefix}side", GOLD_SIDE, ox, 0, ox + width, 0))


def render_voxels(pixels, ox, oy, s, d, prefix, edge_w=None, bevel=True):
    """Render pixels as extruded cubes (oblique projection, depth goes up-right).

    Only exposed side faces are drawn; all side faces are painted before the
    front faces so fronts (nearest plane) always win.
    """
    edge_w = edge_w if edge_w is not None else max(0.6, s * 0.065)
    sides, fronts = [], []
    hl = max(0.8, s * 0.09)       # bevel highlight width
    inset = hl * 1.1
    for (c, r) in sorted(pixels, key=lambda p: (-p[1], p[0])):
        x, y = ox + c * s, oy + r * s
        if (c, r - 1) not in pixels:  # top face
            sides.append(f'<polygon points="{pts((x, y), (x + s, y), (x + s + d, y - d), (x + d, y - d))}" '
                         f'fill="{GOLD_TOP}"/>')
        if (c + 1, r) not in pixels:  # right face
            sides.append(f'<polygon points="{pts((x + s, y), (x + s + d, y - d), (x + s + d, y + s - d), (x + s, y + s))}" '
                         f'fill="url(#{prefix}side)"/>')
    for (c, r) in sorted(pixels, key=lambda p: (p[1], p[0])):
        x, y = ox + c * s, oy + r * s
        fronts.append(f'<rect x="{f(x)}" y="{f(y)}" width="{f(s)}" height="{f(s)}" fill="url(#{prefix}front)"/>')
        if not bevel:
            continue
        # bevel: light top-left inner edge, dark bottom-right inner edge
        fronts.append(f'<polyline points="{pts((x + inset, y + s - inset), (x + inset, y + inset), (x + s - inset, y + inset))}" '
                      f'fill="none" stroke="#fff8dc" stroke-opacity="0.75" stroke-width="{f(hl)}" stroke-linecap="square"/>')
        fronts.append(f'<polyline points="{pts((x + s - inset, y + inset), (x + s - inset, y + s - inset), (x + inset, y + s - inset))}" '
                      f'fill="none" stroke="#7a4b0e" stroke-opacity="0.45" stroke-width="{f(hl)}" stroke-linecap="square"/>')
    return (f'<g stroke="{GOLD_EDGE}" stroke-width="{f(edge_w)}" stroke-linejoin="round">{"".join(sides)}</g>'
            f'<g stroke="{GOLD_EDGE}" stroke-width="{f(edge_w)}" stroke-linejoin="round">{"".join(fronts)}</g>')


def shadow_filter(fid, dx, dy, blur, opacity, color="#02160d"):
    return (f'<filter id="{fid}" x="-10%" y="-20%" width="120%" height="150%">'
            f'<feDropShadow dx="{f(dx)}" dy="{f(dy)}" stdDeviation="{f(blur)}" '
            f'flood-color="{color}" flood-opacity="{opacity}"/></filter>')


def svg_doc(w, h, body, label="Curlbook"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {f(w)} {f(h)}" '
            f'width="{f(w)}" height="{f(h)}" role="img" aria-label="{label}">'
            f'<title>{label}</title>{body}</svg>\n')


# ---------------------------------------------------------------- logos ----
def build_board_logo(text="CURLBOOK"):
    s, d = 14, 9
    pixels, cols = text_pixels(text)
    tw, th = cols * s, GH * s
    pad_l = pad_r = 50
    pad_t, pad_b = 46, 62
    w = pad_l + tw + d + pad_r
    h = pad_t + th + pad_b
    ox, oy = pad_l, pad_t

    # board outline with a card-edge connector tab (and key notch) at the bottom
    r, tab_h = 12, 18
    tx1, tx2 = round(w * 0.22), round(w * 0.78)
    nx1 = tx1 + round((tx2 - tx1) * 0.36)
    nx2 = nx1 + 9
    board = (f"M{r},0 H{w - r} Q{w},0 {w},{r} V{h - r} Q{w},{h} {w - r},{h} "
             f"H{tx2} V{h + tab_h - 3} Q{tx2},{h + tab_h} {tx2 - 3},{h + tab_h} "
             f"H{nx2} V{h + tab_h - 11} H{nx1} V{h + tab_h} "
             f"H{tx1 + 3} Q{tx1},{h + tab_h} {tx1},{h + tab_h - 3} V{h} "
             f"H{r} Q0,{h} 0,{h - r} V{r} Q0,0 {r},0 Z")

    out = ["<defs>",
           gradient("pcb", [("0", PCB_TOP), ("1", PCB_BOTTOM)], 0, 0, 0, h + tab_h),
           gradient("finger", [("0", "#ffe9a6"), ("0.5", "#e8b14a"), ("1", "#b07418")], 0, h, 0, h + tab_h),
           voxel_defs("g", oy, th, ox, tw + d),
           shadow_filter("sh", -3, 5, 2.6, 0.65),
           shadow_filter("bsh", 0, 6, 6, 0.45, "#000"),
           # faint solder-mask texture
           '<pattern id="dots" width="8" height="8" patternUnits="userSpaceOnUse">'
           '<circle cx="1" cy="1" r="0.7" fill="#ffffff" fill-opacity="0.05"/></pattern>',
           "</defs>"]

    out.append(f'<path d="{board}" fill="url(#pcb)" stroke="{PCB_EDGE}" stroke-width="2" filter="url(#bsh)"/>')
    out.append(f'<path d="{board}" fill="url(#dots)"/>')
    # inner board outline (silkscreen keep-out line)
    out.append(f'<rect x="8" y="8" width="{w - 16}" height="{h - 16}" rx="8" fill="none" '
               f'stroke="{SILK}" stroke-opacity="0.18" stroke-width="1" stroke-dasharray="4 4"/>')

    traces, vias = [], []

    def via(x, y, rr=3.6):
        vias.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(rr)}" fill="url(#finger)" stroke="#8a5a14" stroke-width="0.8"/>'
                    f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(rr * 0.42)}" fill="{HOLE}"/>')

    def trace(dpath, width=2.6):
        traces.append(f'<path d="{dpath}" fill="none" stroke="{TRACE}" stroke-opacity="0.75" '
                      f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')

    # top band traces (y between board edge and block tops)
    ty = oy - d - 14
    trace(f"M34,{ty - 10} H{w * 0.18} L{w * 0.18 + 10},{ty} H{w * 0.36}")
    via(w * 0.36, ty)
    trace(f"M{w * 0.42},{ty - 10} H{w * 0.55}")
    via(w * 0.42, ty - 10)
    via(w * 0.55, ty - 10)
    trace(f"M{w - 34},{ty - 10} H{w * 0.82} L{w * 0.82 - 10},{ty} H{w * 0.64}")
    via(w * 0.64, ty)

    # left / right band traces
    mx = pad_l / 2
    trace(f"M{mx - 6},34 V{oy + th * 0.35} L{mx + 6},{oy + th * 0.35 + 12} V{oy + th * 0.8}")
    via(mx + 6, oy + th * 0.8)
    trace(f"M{w - mx + 6},34 V{oy + th * 0.3} L{w - mx - 6},{oy + th * 0.3 + 12} V{oy + th * 0.75}")
    via(w - mx - 6, oy + th * 0.75)

    # edge connector fingers with traces running up from every other finger
    fingers = []
    fw, fg = 7, 4.5
    x = tx1 + 7
    i = 0
    while x + fw <= tx2 - 7:
        if not (x + fw > nx1 - 2 and x < nx2 + 2):
            fingers.append(f'<rect x="{f(x)}" y="{h + 2}" width="{fw}" height="{tab_h - 5}" rx="1.2" '
                           f'fill="url(#finger)" stroke="#8a5a14" stroke-width="0.6"/>')
            if i % 2 == 0:
                cx = x + fw / 2
                top = h - 26 - (i % 4) * 4
                jog = -8 if cx < w / 2 else 8  # fan out away from the centre
                trace(f"M{f(cx)},{h + 3} V{h - 10} L{f(cx + jog)},{h - 18} V{top}", 2)
                via(cx + jog, top, 3)
            i += 1
        x += fw + fg

    # corner mounting holes
    holes = []
    for hx, hy in ((18, 18), (w - 18, 18), (18, h - 18), (w - 18, h - 18)):
        holes.append(f'<circle cx="{hx}" cy="{hy}" r="8.5" fill="url(#finger)" stroke="#8a5a14" stroke-width="1"/>'
                     f'<circle cx="{hx}" cy="{hy}" r="4.6" fill="{HOLE}"/>')

    # silkscreen labels
    silk = (f'<g font-family="ui-monospace, Menlo, Consolas, monospace" font-size="10" font-weight="700" '
            f'fill="{SILK}" fill-opacity="0.85" letter-spacing="1">'
            f'<text x="36" y="{h - 14}">CB-01 REV A</text>'
            f'<text x="{w - 36}" y="{h - 14}" text-anchor="end">HTTP/1.1  5V  GND</text>'
            f'<text x="{ox - 2}" y="{oy - d - 3}" font-size="8" fill-opacity="0.7">U1</text>'
            f'</g>')

    out += traces + vias + fingers + holes + [silk]
    out.append(f'<g filter="url(#sh)">{render_voxels(pixels, ox, oy, s, d, "g")}</g>')
    return svg_doc(w, h + tab_h + 4, "".join(out))


def build_wordmark(text="CURLBOOK"):
    s, d = 10, 6
    pixels, cols = text_pixels(text)
    tw, th = cols * s, GH * s
    pad = 4
    ox, oy = pad + 3, pad + d
    w, h = ox + tw + d + pad, oy + th + pad + 4
    body = ("<defs>" + voxel_defs("w", oy, th, ox, tw + d)
            + shadow_filter("wsh", -2, 3, 1.6, 0.6, "#000") + "</defs>"
            + f'<g filter="url(#wsh)">{render_voxels(pixels, ox, oy, s, d, "w", 0.7, bevel=False)}</g>')
    return svg_doc(w, h, body)


def build_icon():
    size = 64
    s, d = 5.4, 3
    pixels, cols = text_pixels("C")
    tw, th = cols * s, GH * s
    bx, by, bw, bh = 13, 7, 38, 50
    ox = bx + (bw - (tw + d)) / 2
    oy = by + (bh - (th - d)) / 2 + 1
    pins = []
    for k in range(4):
        py = by + 7 + k * 11
        pins.append(f'<rect x="4" y="{py}" width="{bx - 2}" height="5" rx="1" fill="url(#ipin)" stroke="#8a5a14" stroke-width="0.6"/>')
        pins.append(f'<rect x="{bx + bw - 2}" y="{py}" width="{size - 4 - (bx + bw - 2)}" height="5" rx="1" '
                    f'fill="url(#ipin)" stroke="#8a5a14" stroke-width="0.6"/>')
    body = ("<defs>" + voxel_defs("i", oy, th, ox, tw + d)
            + gradient("ipin", [("0", "#ffe9a6"), ("0.5", "#e8b14a"), ("1", "#b07418")], 0, 0, 0, 6)
            + gradient("ibody", [("0", "#2a3036"), ("1", CHIP_BODY)], 0, by, 0, by + bh)
            + shadow_filter("ish", -1.2, 1.8, 0.9, 0.7, "#000") + "</defs>"
            + "".join(pins)
            + f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="4" fill="url(#ibody)" stroke="{CHIP_EDGE}" stroke-width="1.2"/>'
            + f'<path d="M{bx + bw / 2 - 4},{by} a4,4 0 0 0 8,0" fill="#0b0d0f"/>'
            + f'<circle cx="{bx + 6}" cy="{by + bh - 6}" r="1.8" fill="#4a535c"/>'
            + f'<g filter="url(#ish)">{render_voxels(pixels, ox, oy, s, d, "i", 0.5)}</g>')
    return svg_doc(size, size, body)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, content in (("logo.svg", build_board_logo()),
                          ("logo-wordmark.svg", build_wordmark()),
                          ("logo-icon.svg", build_icon())):
        path = os.path.join(OUT_DIR, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"wrote {os.path.relpath(path)} ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
