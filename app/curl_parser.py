"""Parse a curl command line into curlbook's request model."""
import base64
from urllib.parse import quote, urlsplit, urlunsplit

from store import default_request

# Options that take a value (short and long forms)
VALUE_OPTS = {
    "-X": "method", "--request": "method",
    "-H": "header", "--header": "header",
    "-d": "data", "--data": "data", "--data-ascii": "data",
    "--data-raw": "data_raw", "--data-binary": "data_binary",
    "--data-urlencode": "data_urlencode",
    "--json": "json",
    "-u": "user", "--user": "user",
    "-b": "cookie", "--cookie": "cookie",
    "-A": "user_agent", "--user-agent": "user_agent",
    "-e": "referer", "--referer": "referer",
    "--url": "url",
    "-m": "max_time", "--max-time": "max_time",
    "-F": "form", "--form": "form", "--form-string": "form",
    # accepted but ignored (value consumed)
    "--connect-timeout": "ignore_val", "-o": "ignore_val", "--output": "ignore_val",
    "-w": "ignore_val", "--write-out": "ignore_val", "--retry": "ignore_val",
    "-x": "proxy", "--proxy": "proxy", "-c": "ignore_val", "--cookie-jar": "ignore_val",
    "--cacert": "ignore_val", "--cert": "ignore_val", "--key": "ignore_val",
    "-T": "unsupported_val", "--upload-file": "unsupported_val",
    "--limit-rate": "ignore_val", "--max-redirs": "ignore_val",
}

# Boolean flags
FLAG_OPTS = {
    "-k": "insecure", "--insecure": "insecure",
    "-L": "location", "--location": "location",
    "-G": "get", "--get": "get",
    "-I": "head", "--head": "head",
    "--compressed": "noop", "-s": "noop", "--silent": "noop", "-S": "noop",
    "--show-error": "noop", "-v": "noop", "--verbose": "noop", "-i": "noop",
    "--include": "noop", "-f": "noop", "--fail": "noop", "-N": "noop",
    "--no-buffer": "noop", "-g": "noop", "--globoff": "noop", "--http1.1": "noop",
    "--http2": "noop", "-#": "noop", "--progress-bar": "noop", "-n": "noop",
    "--netrc": "noop", "--location-trusted": "location", "--fail-with-body": "noop",
}


class CurlParseError(ValueError):
    pass


def tokenize(cmd: str) -> list:
    """Shell-like tokenizer supporting '..', "..", $'..', backslash escapes
    and line continuations (\\ + newline, also Windows ^ continuations)."""
    tokens, buf, i, n = [], [], 0, len(cmd)
    in_token = False

    def flush():
        nonlocal buf, in_token
        if in_token:
            tokens.append("".join(buf))
        buf, in_token = [], False

    while i < n:
        c = cmd[i]
        if c == "\\" and i + 1 < n and cmd[i + 1] in "\r\n":
            # line continuation
            i += 2
            if i < n and cmd[i - 1] == "\r" and cmd[i] == "\n":
                i += 1
            continue
        if c == "^" and i + 1 < n and cmd[i + 1] in "\r\n" and not in_token:
            i += 2
            continue
        if c in " \t\r\n":
            flush()
            i += 1
            continue
        if c == "'":
            in_token = True
            j = cmd.find("'", i + 1)
            if j == -1:
                raise CurlParseError("Unterminated single quote")
            buf.append(cmd[i + 1:j])
            i = j + 1
            continue
        if c == "$" and i + 1 < n and cmd[i + 1] == "'":
            in_token = True
            i += 2
            while i < n and cmd[i] != "'":
                if cmd[i] == "\\" and i + 1 < n:
                    e = cmd[i + 1]
                    mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "0": "\0"}
                    if e in mapping:
                        buf.append(mapping[e])
                        i += 2
                    elif e == "x" and i + 3 < n:
                        buf.append(chr(int(cmd[i + 2:i + 4], 16)))
                        i += 4
                    elif e == "u" and i + 5 < n:
                        buf.append(chr(int(cmd[i + 2:i + 6], 16)))
                        i += 6
                    else:
                        buf.append(e)
                        i += 2
                else:
                    buf.append(cmd[i])
                    i += 1
            if i >= n:
                raise CurlParseError("Unterminated $'...' quote")
            i += 1
            continue
        if c == '"':
            in_token = True
            i += 1
            while i < n and cmd[i] != '"':
                if cmd[i] == "\\" and i + 1 < n and cmd[i + 1] in '"\\$`\n':
                    if cmd[i + 1] != "\n":
                        buf.append(cmd[i + 1])
                    i += 2
                else:
                    buf.append(cmd[i])
                    i += 1
            if i >= n:
                raise CurlParseError("Unterminated double quote")
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            in_token = True
            buf.append(cmd[i + 1])
            i += 2
            continue
        in_token = True
        buf.append(c)
        i += 1
    flush()
    return tokens


def _urlencode_data(value: str) -> str:
    """Emulate curl --data-urlencode semantics."""
    if value.startswith("="):
        return quote(value[1:], safe="")
    if "=" in value:
        name, content = value.split("=", 1)
        return f"{name}={quote(content, safe='')}"
    return quote(value, safe="")


def _has_header(headers, name):
    return any(h["key"].lower() == name.lower() for h in headers)


def parse_curl(cmd: str) -> tuple:
    """Return (request_dict, warnings)."""
    cmd = (cmd or "").strip()
    if not cmd:
        raise CurlParseError("Empty curl command")
    tokens = tokenize(cmd)
    if not tokens:
        raise CurlParseError("Empty curl command")
    if tokens[0].lower() in ("curl", "curl.exe"):
        tokens = tokens[1:]

    req = default_request("Imported Request")
    # curl does not follow redirects unless -L is given
    req["options"]["followRedirects"] = False
    warnings = []
    headers = []
    data_parts = []
    data_kind = None  # "form" (-d style) or "json"
    method = None
    url = None
    get_mode = False
    head_mode = False

    def apply(kind, val):
        nonlocal method, url, get_mode, head_mode, data_kind
        if kind == "method":
            method = val.upper()
        elif kind == "header":
            if ":" in val:
                k, v = val.split(":", 1)
                headers.append({"key": k.strip(), "value": v.strip(), "enabled": True})
            elif val.endswith(";"):
                headers.append({"key": val[:-1].strip(), "value": "", "enabled": True})
            else:
                warnings.append(f"Ignored malformed header: {val!r}")
        elif kind in ("data", "data_raw", "data_binary"):
            if kind != "data_raw" and val.startswith("@"):
                warnings.append(f"File data ({val}) is not supported; stored literally")
            if kind == "data":
                val = val.replace("\r", "").replace("\n", "")
            data_parts.append(val)
            data_kind = data_kind or "form"
        elif kind == "data_urlencode":
            data_parts.append(_urlencode_data(val))
            data_kind = data_kind or "form"
        elif kind == "json":
            data_parts.append(val)
            data_kind = "json"
        elif kind == "user":
            token = base64.b64encode(val.encode()).decode()
            headers.append({"key": "Authorization", "value": f"Basic {token}", "enabled": True})
        elif kind == "cookie":
            if "=" in val:
                headers.append({"key": "Cookie", "value": val, "enabled": True})
            else:
                warnings.append(f"Cookie file ({val}) is not supported; ignored")
        elif kind == "user_agent":
            headers.append({"key": "User-Agent", "value": val, "enabled": True})
        elif kind == "referer":
            headers.append({"key": "Referer", "value": val, "enabled": True})
        elif kind == "url":
            url = val
        elif kind == "max_time":
            try:
                req["options"]["timeout"] = float(val) if "." in val else int(val)
            except ValueError:
                warnings.append(f"Invalid --max-time value: {val!r}")
        elif kind == "form":
            warnings.append(f"Multipart form field (-F {val}) is not supported; ignored")
        elif kind == "proxy":
            warnings.append(f"Proxy option ({val}) is not supported; ignored")
        elif kind == "unsupported_val":
            warnings.append(f"Upload file ({val}) is not supported; ignored")
        elif kind == "insecure":
            req["options"]["insecure"] = True
        elif kind == "location":
            req["options"]["followRedirects"] = True
        elif kind == "get":
            get_mode = True
        elif kind == "head":
            head_mode = True

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if tok.startswith("--"):
            name, eq, inline = tok.partition("=")
            if name in VALUE_OPTS:
                if eq:
                    val = inline
                else:
                    if i >= len(tokens):
                        raise CurlParseError(f"Option {name} requires a value")
                    val = tokens[i]
                    i += 1
                apply(VALUE_OPTS[name], val)
            elif tok in FLAG_OPTS:
                apply(FLAG_OPTS[tok], None)
            elif tok == "--":
                continue
            else:
                warnings.append(f"Unknown option ignored: {tok}")
        elif tok.startswith("-") and len(tok) > 1:
            # short options, possibly combined (-sSLk) or with attached value (-XPOST)
            j = 1
            while j < len(tok):
                opt = "-" + tok[j]
                if opt in VALUE_OPTS:
                    rest = tok[j + 1:]
                    if rest:
                        val = rest
                    else:
                        if i >= len(tokens):
                            raise CurlParseError(f"Option {opt} requires a value")
                        val = tokens[i]
                        i += 1
                    apply(VALUE_OPTS[opt], val)
                    break
                elif opt in FLAG_OPTS:
                    apply(FLAG_OPTS[opt], None)
                    j += 1
                else:
                    warnings.append(f"Unknown option ignored: {opt}")
                    j += 1
        else:
            if url is None:
                url = tok
            else:
                warnings.append(f"Extra argument ignored: {tok}")

    if not url:
        raise CurlParseError("No URL found in curl command")

    body = "&".join(data_parts) if data_kind == "form" else "".join(data_parts)

    if data_kind == "json":
        if not _has_header(headers, "Content-Type"):
            headers.append({"key": "Content-Type", "value": "application/json", "enabled": True})
        if not _has_header(headers, "Accept"):
            headers.append({"key": "Accept", "value": "application/json", "enabled": True})
    elif data_kind == "form" and not get_mode and not _has_header(headers, "Content-Type"):
        headers.append({"key": "Content-Type", "value": "application/x-www-form-urlencoded", "enabled": True})

    if get_mode and data_parts:
        parts = urlsplit(url)
        q = parts.query + ("&" if parts.query else "") + body
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))
        body = ""

    if method is None:
        if head_mode:
            method = "HEAD"
        elif get_mode:
            method = "GET"
        elif data_parts:
            method = "POST"
        else:
            method = "GET"

    req["method"] = method
    req["url"] = url
    req["headers"] = headers
    req["body"] = body
    return req, warnings
