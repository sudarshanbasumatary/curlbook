"""{{variable}} substitution and response value extraction."""
import json
import random
import re
import time
import uuid

VAR_RE = re.compile(r"\{\{\s*([$A-Za-z0-9_.\-]+)\s*\}\}")
PATH_TOKEN_RE = re.compile(r"""\[\s*(-?\d+)\s*\]|\[\s*["']([^"']*)["']\s*\]|\.?([^.\[\]]+)""")

DYNAMIC = {
    "$timestamp": lambda: str(int(time.time())),
    "$timestampMs": lambda: str(int(time.time() * 1000)),
    "$uuid": lambda: str(uuid.uuid4()),
    "$randomInt": lambda: str(random.randint(0, 1000)),
}


def substitute(text: str, variables: dict, missing: set) -> str:
    if not text:
        return text

    def repl(m):
        name = m.group(1)
        if name in variables:
            v = variables[name]
            return v if isinstance(v, str) else json.dumps(v)
        if name in DYNAMIC:
            return DYNAMIC[name]()
        missing.add(name)
        return m.group(0)

    return VAR_RE.sub(repl, str(text))


def resolve_request(req: dict, variables: dict) -> tuple:
    """Return (resolved_request, sorted list of missing variable names)."""
    missing = set()
    out = dict(req)
    out["url"] = substitute(req.get("url", ""), variables, missing)
    out["body"] = substitute(req.get("body", ""), variables, missing)
    out["headers"] = [
        {**h, "key": substitute(h.get("key", ""), variables, missing),
         "value": substitute(h.get("value", ""), variables, missing)}
        for h in req.get("headers") or []
    ]
    return out, sorted(missing)


class ExtractError(Exception):
    pass


def parse_path(path: str) -> list:
    path = (path or "").strip()
    if path.startswith("$"):
        path = path[1:]
    tokens, pos = [], 0
    while pos < len(path):
        m = PATH_TOKEN_RE.match(path, pos)
        if not m or m.end() == pos:
            raise ExtractError(f"Invalid path near {path[pos:]!r}")
        if m.group(1) is not None:
            tokens.append(int(m.group(1)))
        elif m.group(2) is not None:
            tokens.append(m.group(2))
        else:
            key = m.group(3)
            tokens.append(int(key) if key.lstrip("-").isdigit() else key)
        pos = m.end()
    return tokens


def get_path(data, path: str):
    cur = data
    walked = "$"
    for tok in parse_path(path):
        if isinstance(tok, int) and isinstance(cur, list):
            if -len(cur) <= tok < len(cur):
                cur = cur[tok]
            else:
                raise ExtractError(f"Index {tok} out of range at {walked} (length {len(cur)})")
            walked += f"[{tok}]"
        elif isinstance(cur, dict):
            key = str(tok)
            if key in cur:
                cur = cur[key]
            elif key == "length":
                cur = len(cur)
            else:
                raise ExtractError(f"Key {key!r} not found at {walked}")
            walked += f".{key}"
        elif isinstance(cur, list) and tok == "length":
            cur = len(cur)
        else:
            raise ExtractError(f"Cannot access {tok!r} on {type(cur).__name__} at {walked}")
    return cur


def to_var_string(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def extract(source: str, path: str, status: int, headers: dict, body_text: str) -> str:
    if source == "status":
        return str(status)
    if source == "header":
        name = (path or "").strip().lower()
        for k, v in (headers or {}).items():
            if k.lower() == name:
                return v
        raise ExtractError(f"Header {path!r} not found")
    # body
    try:
        data = json.loads(body_text)
    except (ValueError, TypeError):
        if not (path or "").strip():
            return body_text or ""
        raise ExtractError("Response body is not valid JSON")
    return to_var_string(get_path(data, path))
