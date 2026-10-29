#!/usr/bin/env python3
"""Generate Curlbook SVG logos: cursive "CurlBook" written in blue ballpoint ink with a
red offset shadow line, sitting on two light ruled lines (baseline and x-height) so
capitals and ascenders overshoot the top line, like handwriting on a ruled page.

Text is shaped with HarfBuzz and converted to plain SVG paths, so the output SVGs
need no fonts at runtime.

Outputs (into app/static/):
  logo.svg / logo-dark.svg                     large logo (welcome screen, README)
  logo-wordmark.svg / logo-wordmark-dark.svg   compact logo (top bar)
  logo-icon.svg                                favicon: cursive "C" on a ruled paper square

Requires: pip install -r tools/requirements.txt
Run:      python3 tools/gen_logo.py
"""
import os

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "app", "static")
FONT_PATH = os.path.join(HERE, "fonts", "Sacramento-Regular.ttf")  # SIL OFL 1.1, see fonts/OFL.txt
TEXT = "CurlBook"

# Palettes ------------------------------------------------------------------
THEMES = {
    # classic blue ballpoint on paper, red pen shadow, pale-blue ruled lines
    "light": {"ink": "#1c3aa0", "shadow": "#d9363e", "rule": "#8fb0de", "rule_opacity": 0.85},
    # brighter "gel pen" inks so the logo stays legible on dark backgrounds
    "dark": {"ink": "#8aa9ff", "shadow": "#ff5c62", "rule": "#c9d6ff", "rule_opacity": 0.28},
}
PAPER, PAPER_EDGE = "#fffdf6", "#e6e0cf"


def f(v):
    v = round(v, 2)
    return str(int(v)) if v == int(v) else f"{v:g}"


# Text -> path ---------------------------------------------------------------
_tt = TTFont(FONT_PATH)
_glyphs = _tt.getGlyphSet()
_order = _tt.getGlyphOrder()
_upem = _tt["head"].unitsPerEm
_hb_font = hb.Font(hb.Face(hb.Blob.from_file_path(FONT_PATH)))


def x_height_units():
    xh = getattr(_tt["OS/2"], "sxHeight", 0)
    if not xh:
        bp = BoundsPen(_glyphs)
        _glyphs[_tt.getBestCmap()[ord("x")]].draw(bp)
        xh = bp.bounds[3]
    return xh


def shape(text, size):
    """Return (svg path d, (xmin, ymin, xmax, ymax), x_height) in SVG units, baseline at y=0."""
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(_hb_font, buf, {"kern": True, "liga": True, "calt": True})
    s = size / _upem
    pen, bounds = SVGPathPen(_glyphs), BoundsPen(_glyphs)
    x = 0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        glyph = _glyphs[_order[info.codepoint]]
        m = (s, 0, 0, -s, (x + pos.x_offset) * s, -pos.y_offset * s)
        glyph.draw(TransformPen(pen, m))
        glyph.draw(TransformPen(bounds, m))
        x += pos.x_advance
    return pen.getCommands(), bounds.bounds, x_height_units() * s


# SVG building blocks --------------------------------------------------------
def ink_filter(fid, grain_freq):
    """Subtle ballpoint texture: the ink density varies slightly along the strokes."""
    return (f'<filter id="{fid}" x="-5%" y="-20%" width="110%" height="140%">'
            f'<feTurbulence type="fractalNoise" baseFrequency="{grain_freq}" numOctaves="2" seed="11" result="n"/>'
            '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -0.75 1.3" result="a"/>'
            '<feComposite in="SourceGraphic" in2="a" operator="in"/>'
            '</filter>')


def rule_gradient(gid, x0, x1, color, opacity):
    """Ruled line that fades out at both ends."""
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{f(x0)}" y1="0" x2="{f(x1)}" y2="0">'
            f'<stop offset="0" stop-color="{color}" stop-opacity="0"/>'
            f'<stop offset="0.07" stop-color="{color}" stop-opacity="{opacity}"/>'
            f'<stop offset="0.93" stop-color="{color}" stop-opacity="{opacity}"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient>')


def svg_doc(x, y, w, h, body, out_w=None, label="Curlbook"):
    out_w = out_w or w
    out_h = out_w * h / w
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="{f(x)} {f(y)} {f(w)} {f(h)}" width="{f(out_w)}" height="{f(out_h)}" '
            f'role="img" aria-label="{label}"><title>{label}</title>{body}</svg>\n')


def build_logo(theme, size=120, pad_x=None, pad_y=None, rule_w=None, ink_w=None, out_w=None,
               rule_ext=None, grain=True):
    """Cursive word on two ruled lines with a red shadow offset to the lower right."""
    pal = THEMES[theme]
    d, (bx0, by0, bx1, by1), xh = shape(TEXT, size)
    ink_w = ink_w if ink_w is not None else size * 0.005         # extra ballpoint weight
    sh_dx, sh_dy = size * 0.021, size * 0.018                     # red shadow offset
    pad_x = pad_x if pad_x is not None else size * 0.12
    pad_y = pad_y if pad_y is not None else size * 0.06
    rule_w = rule_w if rule_w is not None else max(0.8, size * 0.011)
    rule_ext = rule_ext if rule_ext is not None else size * 0.35  # how far rules run past the text

    x0 = bx0 - rule_ext - pad_x
    x1 = bx1 + sh_dx + rule_ext + pad_x
    y0 = by0 - ink_w - pad_y
    y1 = max(by1, 0) + sh_dy + ink_w + pad_y
    rx0, rx1 = x0 + pad_x * 0.5, x1 - pad_x * 0.5

    defs = [f'<path id="word" d="{d}"/>',
            rule_gradient("rule", rx0, rx1, pal["rule"], pal["rule_opacity"])]
    if grain:
        defs.append(ink_filter("ink", f(1.6 / (size / 120))))
    body = ["<defs>", *defs, "</defs>",
            # ruled lines: x-height (top) and baseline (bottom)
            f'<g stroke="url(#rule)" stroke-width="{f(rule_w)}" stroke-linecap="round">'
            f'<line x1="{f(rx0)}" y1="{f(-xh)}" x2="{f(rx1)}" y2="{f(-xh)}"/>'
            f'<line x1="{f(rx0)}" y1="0" x2="{f(rx1)}" y2="0"/></g>',
            # red shadow line, offset to one side
            f'<use xlink:href="#word" href="#word" transform="translate({f(sh_dx)},{f(sh_dy)})" '
            f'fill="{pal["shadow"]}" stroke="{pal["shadow"]}" stroke-width="{f(ink_w * 0.55)}" stroke-linejoin="round"/>',
            # blue ballpoint ink
            f'<use xlink:href="#word" href="#word" fill="{pal["ink"]}" stroke="{pal["ink"]}" '
            f'stroke-width="{f(ink_w)}" stroke-linejoin="round" stroke-linecap="round"'
            + (' filter="url(#ink)"' if grain else "") + "/>"]
    return svg_doc(x0, y0, x1 - x0, y1 - y0, "".join(body), out_w=out_w)


def build_icon():
    """Favicon: a ruled paper square with a cursive capital C overshooting the top line."""
    pal = THEMES["light"]
    size = 64
    glyph_size = 56
    d, (bx0, by0, bx1, by1), xh = shape("C", glyph_size)
    gw, gh = bx1 - bx0, by1 - by0
    # place the C so it is centred; the baseline lands where the glyph bottom sits
    tx = (size - gw) / 2 - bx0 - 1
    ty = (size - gh) / 2 - by0 + 1
    base, top = ty, ty - xh
    ink_w = 1.8
    body = ("<defs>"
            f'<path id="c" d="{d}"/>'
            "</defs>"
            f'<rect x="1" y="1" width="62" height="62" rx="12" fill="{PAPER}" stroke="{PAPER_EDGE}" stroke-width="2"/>'
            f'<g stroke="{pal["rule"]}" stroke-width="2" stroke-linecap="round">'
            f'<line x1="7" y1="{f(top)}" x2="57" y2="{f(top)}"/>'
            f'<line x1="7" y1="{f(base)}" x2="57" y2="{f(base)}"/></g>'
            f'<g transform="translate({f(tx)},{f(ty)})">'
            f'<use xlink:href="#c" href="#c" transform="translate(1.6,1.4)" fill="{pal["shadow"]}" '
            f'stroke="{pal["shadow"]}" stroke-width="{f(ink_w * 0.7)}" stroke-linejoin="round"/>'
            f'<use xlink:href="#c" href="#c" fill="{pal["ink"]}" stroke="{pal["ink"]}" '
            f'stroke-width="{f(ink_w)}" stroke-linejoin="round" stroke-linecap="round"/></g>')
    return svg_doc(0, 0, size, size, body)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    outputs = {
        "logo.svg": build_logo("light", out_w=560),
        # ink grain reads as fuzz on dark backgrounds, so the dark variant uses clean ink
        "logo-dark.svg": build_logo("dark", out_w=560, grain=False),
        # compact: tighter padding, shorter rules, heavier ink so it survives small sizes
        "logo-wordmark.svg": build_logo("light", size=120, pad_x=4, pad_y=4, rule_ext=14,
                                        ink_w=2, rule_w=3, grain=False),
        "logo-wordmark-dark.svg": build_logo("dark", size=120, pad_x=4, pad_y=4, rule_ext=14,
                                             ink_w=2, rule_w=3, grain=False),
        "logo-icon.svg": build_icon(),
    }
    for name, content in outputs.items():
        path = os.path.join(OUT_DIR, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"wrote {os.path.relpath(path)} ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
