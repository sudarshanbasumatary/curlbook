"""curlbook - a tiny HTML Postman-like app backed by a local JSON file."""
import os
import time
from urllib.parse import urlsplit, urlunsplit

import requests
import urllib3
from flask import Flask, jsonify, request, send_from_directory

import history
import store
import tags as tagmod
from curl_builder import build_curl
from curl_parser import CurlParseError, parse_curl
from variables import ExtractError, extract, resolve_request

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY_BYTES = int(os.environ.get("CURLBOOK_MAX_BODY_BYTES", 10 * 1024 * 1024))
# When running in Docker, 'localhost' is the container itself (where curlbook's own server
# listens). If set, loopback hosts in request URLs are redirected to this host instead,
# e.g. 'host.docker.internal', so requests behave like they do from your terminal.
LOCALHOST_ALIAS = os.environ.get("CURLBOOK_LOCALHOST_ALIAS", "").strip()
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def rewrite_loopback(url: str):
    """Return (url_to_connect, original_netloc) — original_netloc is None if not rewritten."""
    if not LOCALHOST_ALIAS:
        return url, None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS and not host.endswith(".localhost"):
        return url, None
    netloc = LOCALHOST_ALIAS
    if parts.port:
        netloc += f":{parts.port}"
    userinfo = parts.netloc.rpartition("@")[0]
    if userinfo:
        netloc = f"{userinfo}@{netloc}"
    return urlunsplit(parts._replace(netloc=netloc)), parts.netloc.rpartition("@")[2]

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")


def bad(msg, code=400):
    return jsonify({"error": msg}), code


@app.errorhandler(CurlParseError)
def _curl_err(e):
    return bad(str(e))


@app.errorhandler(store.StoreCorruptError)
def _store_err(e):
    return bad(str(e), 500)


@app.errorhandler(tagmod.TagError)
def _tag_err(e):
    return bad(str(e), 409 if "already used" in str(e) else 400)


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ---------------------------------------------------------------- store ----
@app.get("/api/store")
def get_store():
    return jsonify(store.load())


@app.post("/api/collections")
def create_collection():
    name = ((request.json or {}).get("name") or "").strip() or "New Collection"
    with store.Transaction() as data:
        col = {"id": store.new_id(), "name": name, "requests": []}
        data["collections"].append(col)
    return jsonify(col), 201


@app.put("/api/collections/<cid>")
def rename_collection(cid):
    name = ((request.json or {}).get("name") or "").strip()
    if not name:
        return bad("Name is required")
    tx = store.Transaction()
    with tx as data:
        col = store.find_collection(data, cid)
        if not col:
            return bad("Collection not found", 404)
        tx.message = f'Rename collection "{col["name"]}" → "{name}"'
        col["name"] = name
    return jsonify(col)


@app.delete("/api/collections/<cid>")
def delete_collection(cid):
    tx = store.Transaction()
    with tx as data:
        col = store.find_collection(data, cid)
        if not col:
            return bad("Collection not found", 404)
        n = len(col["requests"])
        tx.message = f'Delete collection "{col["name"]}" ({n} request{"s" if n != 1 else ""})'
        data["collections"] = [c for c in data["collections"] if c["id"] != cid]
        tagmod.sync_tags(data)
    return jsonify({"ok": True})


@app.post("/api/requests")
def create_request():
    payload = request.json or {}
    cid = payload.get("collectionId")
    req = store.normalize_request(payload.get("request") or {})
    req["id"] = store.new_id()
    with store.Transaction(f'Create "{req["name"]}"') as data:
        col = store.find_collection(data, cid)
        if not col:
            return bad("Collection not found", 404)
        col["requests"].append(req)
        tagmod.sync_tags(data)
        tag_colors = data["tags"]
    return jsonify({"request": req, "collectionId": cid, "tags": tag_colors}), 201


@app.put("/api/requests/<rid>")
def update_request(rid):
    payload = request.json or {}
    tx = store.Transaction()
    with tx as data:
        col, idx, existing = store.find_request(data, rid)
        if not existing:
            return bad("Request not found", 404)
        req = store.normalize_request({**existing, **(payload.get("request") or {})})
        req["id"] = rid
        changes = history.changed_fields(existing, req)
        target_cid = payload.get("collectionId") or col["id"]
        if target_cid != col["id"]:
            target = store.find_collection(data, target_cid)
            if not target:
                return bad("Target collection not found", 404)
            col["requests"].pop(idx)
            target["requests"].append(req)
            changes.insert(0, f'moved to "{target["name"]}"')
        else:
            col["requests"][idx] = req
        tx.message = f'Update "{req["name"]}"' + (f": {', '.join(changes)}" if changes else "")
        tagmod.sync_tags(data)
        tag_colors = data["tags"]
    return jsonify({"request": req, "collectionId": target_cid, "tags": tag_colors})


@app.post("/api/requests/<rid>/duplicate")
def duplicate_request(rid):
    tx = store.Transaction()
    with tx as data:
        col, idx, existing = store.find_request(data, rid)
        if not existing:
            return bad("Request not found", 404)
        copy = store.normalize_request({**existing, "name": existing["name"] + " (copy)"})
        copy["id"] = store.new_id()
        col["requests"].insert(idx + 1, copy)
        tx.message = f'Duplicate "{existing["name"]}"'
    return jsonify({"request": copy, "collectionId": col["id"]}), 201


@app.delete("/api/requests/<rid>")
def delete_request(rid):
    tx = store.Transaction()
    with tx as data:
        col, idx, existing = store.find_request(data, rid)
        if not existing:
            return bad("Request not found", 404)
        tx.message = f'Delete "{existing["name"]}"'
        col["requests"].pop(idx)
        tagmod.sync_tags(data)
    return jsonify({"ok": True})


# ----------------------------------------------------------------- tags ----
@app.post("/api/tags")
def api_ensure_tag():
    """Reserve a unique colour for a tag (used when a tag is added in the editor before saving)."""
    tag = tagmod.normalize_tag((request.json or {}).get("name"))
    if not tag:
        return bad("Invalid tag name")
    with store.Transaction() as data:
        color = tagmod.ensure_tag(data, tag)
        tag_colors = data["tags"]
    return jsonify({"tag": tag, "color": color, "tags": tag_colors})


@app.put("/api/tags/<path:name>")
def api_set_tag_color(name):
    with store.Transaction() as data:
        tag = tagmod.normalize_tag(name)
        color = tagmod.set_color(data, tag, (request.json or {}).get("color"))
        tag_colors = data["tags"]
    return jsonify({"tag": tag, "color": color, "tags": tag_colors})


@app.put("/api/globals")
def put_globals():
    g = (request.json or {}).get("globals")
    if not isinstance(g, dict):
        return bad("globals must be an object")
    clean = {str(k).strip(): ("" if v is None else str(v)) for k, v in g.items() if str(k).strip()}
    with store.Transaction() as data:
        data["globals"] = clean
    return jsonify({"globals": clean})


@app.patch("/api/globals")
def patch_globals():
    g = (request.json or {}).get("globals")
    if not isinstance(g, dict):
        return bad("globals must be an object")
    with store.Transaction() as data:
        for k, v in g.items():
            if str(k).strip():
                data["globals"][str(k).strip()] = "" if v is None else str(v)
        result = data["globals"]
    return jsonify({"globals": result})


# ----------------------------------------------------------------- curl ----
@app.post("/api/parse-curl")
def api_parse_curl():
    req, warnings = parse_curl((request.json or {}).get("curl", ""))
    return jsonify({"request": req, "warnings": warnings})


@app.post("/api/build-curl")
def api_build_curl():
    payload = request.json or {}
    req = store.normalize_request(payload.get("request") or {})
    missing = []
    if payload.get("resolve"):
        req, missing = resolve_request(req, store.load()["globals"])
    return jsonify({"curl": build_curl(req), "missing": missing})


@app.post("/api/import")
def api_import():
    payload = request.json or {}
    req, warnings = parse_curl(payload.get("curl", ""))
    name = (payload.get("name") or "").strip()
    if name:
        req["name"] = name
    req["tags"] = payload.get("tags") or []
    req = store.normalize_request(req)
    with store.Transaction(f'Import "{req["name"]}"') as data:
        col = store.find_collection(data, payload.get("collectionId"))
        if not col:
            if not data["collections"]:
                data["collections"].append({"id": store.new_id(), "name": "Default", "requests": []})
            col = data["collections"][0]
        col["requests"].append(req)
        tagmod.sync_tags(data)
    return jsonify({"request": req, "collectionId": col["id"], "warnings": warnings}), 201


# -------------------------------------------------------------- history ----
@app.errorhandler(history.HistoryError)
def _history_err(e):
    return bad(str(e), 404 if "not found" in str(e) else 400)


def _current_record(data, rid):
    col, _, req = store.find_request(data, rid)
    return {"collectionId": col["id"], "collectionName": col["name"], "request": req} if req else None


@app.get("/api/history")
def api_history_status():
    return jsonify({"enabled": history.ENABLED})


@app.get("/api/requests/<rid>/history")
def api_request_history(rid):
    return jsonify({"enabled": history.ENABLED, "versions": history.versions(rid)})


@app.get("/api/requests/<rid>/history/<sha>")
def api_request_version(rid, sha):
    """A version plus a diff: 'prev' = what that commit changed; 'current' = version -> current saved."""
    against = request.args.get("against", "prev")
    v = history.version(rid, sha)
    rec = v["record"]
    short = sha[:7]
    if against == "current":
        current = _current_record(store.load(), rid)
        diff = history.diff(rec, current, f"{short} (this version)", "current" if current else "current (deleted)")
    else:
        before = history.record_at(rid, f"{sha}^")
        after = None if v["deleted"] else rec
        diff = history.diff(before, after, f"{short}^ (before)" if before else "(new)",
                            f"{short} (after)" if after else "(deleted)")
    return jsonify({
        "sha": sha, "deleted": v["deleted"], "request": rec["request"],
        "collectionId": rec.get("collectionId"), "collectionName": rec.get("collectionName"),
        "curl": build_curl(rec["request"]), "diff": diff,
    })


@app.get("/api/history/deleted")
def api_deleted_requests():
    data = store.load()
    present = [r["id"] for c in data["collections"] for r in c["requests"]]
    return jsonify({"enabled": history.ENABLED, "items": history.deleted_requests(present)})


@app.post("/api/history/restore")
def api_restore_deleted():
    """Bring back a deleted request with its original id (so its history continues)."""
    p = request.json or {}
    rid, sha = str(p.get("id") or ""), str(p.get("sha") or "")
    v = history.version(rid, sha)
    rec = v["record"]
    req = store.normalize_request(rec["request"])
    req["id"] = rid
    tx = store.Transaction(f'Restore "{req["name"]}"')
    with tx as data:
        if store.find_request(data, rid)[2]:
            return bad("That request already exists", 409)
        col = (store.find_collection(data, rec.get("collectionId"))
               or next((c for c in data["collections"] if c["name"] == rec.get("collectionName")), None))
        if not col:
            if not data["collections"]:
                data["collections"].append({"id": store.new_id(), "name": "Default", "requests": []})
            col = data["collections"][0]
        col["requests"].append(req)
        tagmod.sync_tags(data)
        tag_colors = data["tags"]
    return jsonify({"request": req, "collectionId": col["id"], "tags": tag_colors}), 201


# ----------------------------------------------------------------- send ----
@app.post("/api/send")
def api_send():
    payload = request.json or {}
    req = store.normalize_request(payload.get("request") or {})
    globals_ = store.load()["globals"]
    resolved, missing = resolve_request(req, globals_)

    url = resolved["url"].strip()
    if not url:
        return bad("URL is required")
    if "://" not in url:
        url = "http://" + url
        resolved["url"] = url

    headers = {}
    for h in resolved["headers"]:
        if h["enabled"] and h["key"].strip():
            headers[h["key"].strip()] = h["value"]

    opts = resolved["options"]
    try:
        timeout = float(opts.get("timeout") or 30)
    except (TypeError, ValueError):
        timeout = 30.0

    sent_curl = build_curl(resolved)
    result = {"missing": missing, "sentCurl": sent_curl, "resolvedUrl": url}

    connect_url, original_host = rewrite_loopback(url)
    if original_host is not None:
        # keep the Host header the target would see from a terminal curl
        if not any(k.lower() == "host" for k in headers):
            headers["Host"] = original_host
        result["rewrittenUrl"] = connect_url

    started = time.perf_counter()
    try:
        resp = requests.request(
            resolved["method"],
            connect_url,
            headers=headers,
            data=resolved["body"].encode("utf-8") if resolved["body"] else None,
            verify=not opts.get("insecure"),
            allow_redirects=bool(opts.get("followRedirects")),
            timeout=timeout,
            stream=True,
        )
        raw = b""
        truncated = False
        for chunk in resp.iter_content(64 * 1024):
            raw += chunk
            if len(raw) > MAX_BODY_BYTES:
                raw = raw[:MAX_BODY_BYTES]
                truncated = True
                break
        resp.close()
    except requests.exceptions.SSLError as e:
        result["error"] = f"SSL error: {e}. Enable 'Insecure (-k)' to skip certificate verification."
        return jsonify(result)
    except requests.exceptions.RequestException as e:
        result["error"] = f"{type(e).__name__}: {e}"
        host = (urlsplit(url).hostname or "").lower()
        if isinstance(e, requests.exceptions.ConnectionError) and original_host is not None:
            result["error"] += (
                f" — Hint: '{original_host}' was sent to your machine via {LOCALHOST_ALIAS}. "
                "Check the service is running there (on Linux it must listen on 0.0.0.0, not 127.0.0.1)."
            )
        elif isinstance(e, requests.exceptions.ConnectionError) and host in LOOPBACK_HOSTS:
            result["error"] += (
                " — Hint: inside Docker, 'localhost' is the container itself. "
                "Use http://host.docker.internal:<port> to reach services on your machine."
            )
        return jsonify(result)
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    encoding = resp.encoding or resp.apparent_encoding or "utf-8"
    try:
        body_text = raw.decode(encoding, errors="replace")
    except LookupError:
        body_text = raw.decode("utf-8", errors="replace")

    resp_headers = dict(resp.headers)

    # run extraction rules and persist resulting globals
    extractions = []
    updates = {}
    for rule in req["extractions"]:
        var = rule["var"].strip()
        if not var:
            continue
        try:
            value = extract(rule["source"], rule["path"], resp.status_code, resp_headers, body_text)
            updates[var] = value
            extractions.append({"var": var, "value": value, "ok": True})
        except ExtractError as e:
            extractions.append({"var": var, "error": str(e), "ok": False})
    if updates:
        with store.Transaction() as data:
            data["globals"].update(updates)
            globals_ = data["globals"]

    result.update({
        "status": resp.status_code,
        "reason": resp.reason,
        "timeMs": elapsed_ms,
        "size": len(raw),
        "truncated": truncated,
        "headers": resp_headers,
        "body": body_text,
        "contentType": resp.headers.get("Content-Type", ""),
        "finalUrl": url if resp.url == connect_url else resp.url,
        "extractions": extractions,
        "globals": globals_,
    })
    return jsonify(result)


@app.post("/api/extract")
def api_extract():
    """Preview an extraction against a response the client already has."""
    p = request.json or {}
    try:
        value = extract(p.get("source", "body"), p.get("path", ""), p.get("status", 0),
                        p.get("headers") or {}, p.get("body", ""))
        return jsonify({"ok": True, "value": value})
    except ExtractError as e:
        return jsonify({"ok": False, "error": str(e)})


def _init_history():
    """Create the history repo (snapshotting existing requests) and record any hand-edits."""
    try:
        with store._lock:
            history.startup(store.load())
    except Exception as e:  # noqa: BLE001 - history must never stop the app from starting
        app.logger.warning("request history unavailable: %s", e)


_init_history()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
