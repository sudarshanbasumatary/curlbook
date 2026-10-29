"""Request tags: normalisation and a global tag -> colour registry with unique colours."""
import colorsys
import re

MAX_TAG_LEN = 32
MAX_TAGS_PER_REQUEST = 20

# Distinct hues that read well as text/tint on both light and dark backgrounds.
PALETTE = [
    "#e5484d",  # red
    "#0090ff",  # blue
    "#30a46c",  # green
    "#f76b15",  # orange
    "#8e4ec6",  # purple
    "#12a594",  # teal
    "#d6409f",  # pink
    "#ffb224",  # amber
    "#3e63dd",  # indigo
    "#a18072",  # brown
    "#00a2c7",  # cyan
    "#46a758",  # grass
    "#e54666",  # crimson
    "#6e56cf",  # violet
    "#978365",  # bronze
    "#ab4aba",  # plum
]

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
_INVALID_CHARS = re.compile(r"[^\w\-./:+]", re.UNICODE)


class TagError(ValueError):
    pass


def normalize_tag(raw) -> str:
    """'  Auth Flow ' -> 'auth-flow'. Returns '' for unusable input."""
    tag = str(raw or "").strip().lstrip("#").lower()
    tag = re.sub(r"\s+", "-", tag)
    tag = _INVALID_CHARS.sub("", tag).strip("-")
    return tag[:MAX_TAG_LEN]


def normalize_tags(raw_tags) -> list:
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")
    out, seen = [], set()
    for t in raw_tags or []:
        tag = normalize_tag(t)
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out[:MAX_TAGS_PER_REQUEST]


def normalize_color(color) -> str:
    c = str(color or "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", c):
        c = "#" + "".join(ch * 2 for ch in c[1:])
    if not _HEX_RE.match(c):
        raise TagError(f"Invalid colour {color!r}; use #rrggbb")
    return c


def _generated_colors():
    """Endless sequence of distinct colours once the palette is exhausted (golden-angle hues)."""
    i = 0
    while True:
        hue = (i * 0.618033988749895 + 0.11) % 1.0
        light = (0.48, 0.42, 0.55)[(i // 7) % 3]
        r, g, b = colorsys.hls_to_rgb(hue, light, 0.68)
        yield "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
        i += 1


def next_free_color(used) -> str:
    used = {c.lower() for c in used}
    for c in PALETTE:
        if c not in used:
            return c
    for c in _generated_colors():
        if c not in used:
            return c
    raise RuntimeError("unreachable")


def used_tags(data: dict) -> set:
    return {t for col in data["collections"] for r in col["requests"] for t in r.get("tags") or []}


def ensure_tag(data: dict, tag: str) -> str:
    """Give `tag` a colour if it has none. Returns its colour."""
    registry = data.setdefault("tags", {})
    if tag not in registry:
        registry[tag] = next_free_color(registry.values())
    return registry[tag]


def sync_tags(data: dict) -> None:
    """Ensure every tag in use has a unique colour; drop colours for tags no longer used."""
    registry = data.setdefault("tags", {})
    in_use = used_tags(data)
    for tag in list(registry):
        if tag not in in_use:
            del registry[tag]
    for tag in sorted(in_use):
        ensure_tag(data, tag)


def set_color(data: dict, tag: str, color: str) -> str:
    tag = normalize_tag(tag)
    if not tag:
        raise TagError("Invalid tag name")
    color = normalize_color(color)
    registry = data.setdefault("tags", {})
    owner = next((t for t, c in registry.items() if c.lower() == color and t != tag), None)
    if owner:
        raise TagError(f"Colour {color} is already used by tag '{owner}'")
    registry[tag] = color
    return color
