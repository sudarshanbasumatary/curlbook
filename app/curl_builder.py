"""Build a curl command string from curlbook's request model."""

_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./:=@%+,")


def shell_quote(s: str) -> str:
    s = "" if s is None else str(s)
    if s and all(c in _SAFE for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def build_curl(req: dict, multiline: bool = True) -> str:
    method = (req.get("method") or "GET").upper()
    body = req.get("body") or ""
    opts = req.get("options") or {}

    first = ["curl"]
    # Always state the method explicitly, except for a plain body-less GET
    # (curl's default). A GET *with* a body still needs -X GET, since curl
    # would otherwise switch to POST when it sees --data-raw.
    if method == "HEAD" and not body:
        first.append("-I")
    elif method != "GET" or body:
        first.append(f"-X {method}")
    first.append(shell_quote(req.get("url") or ""))

    rest = []
    for h in req.get("headers") or []:
        if not h.get("enabled", True) or not h.get("key"):
            continue
        rest.append(f"-H {shell_quote(h['key'] + ': ' + (h.get('value') or ''))}")
    if body:
        rest.append(f"--data-raw {shell_quote(body)}")
    if opts.get("insecure"):
        rest.append("-k")
    if opts.get("followRedirects"):
        rest.append("-L")
    timeout = opts.get("timeout")
    if timeout not in (None, "", 30, "30"):
        rest.append(f"-m {timeout}")

    sep = " \\\n  " if multiline else " "
    return sep.join([" ".join(first)] + rest)
