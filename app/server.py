"""curlbook - a tiny HTML Postman-like app backed by a local JSON file."""
import os
import time
from urllib.parse import urlsplit

import requests
import urllib3
from flask import Flask, jsonify, request, send_from_directory

import store
from curl_builder import build_curl
from curl_parser import CurlParseError, parse_curl
from variables import ExtractError, extract, resolve_request

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY_BYTES = int(os.environ.get("CURLBOOK_MAX_BODY_BYTES", 10 * 1024 * 1024))

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")


def bad(msg, code=400):
    return jsonify({"error": msg}), code


@app.errorhandler(CurlParseError)
def _curl_err(e):
    return bad(str(e))


@app.errorhandler(store.StoreCorruptError)
def _store_err(e):
    return bad(str(e), 500)


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
    with store.Transaction() as data:
        col = store.find_collection(data, cid)
        if not col:
            return bad("Collection not found", 404)
        col["name"] = name
    return jsonify(col)


@app.delete("/api/collections/<cid>")
def delete_collection(cid):
    with store.Transaction() as data:
        before = len(data["collections"])
        data["collections"] = [c for c in data["collections"] if c["id"] != cid]
        if len(data["collections"]) == before:
            return bad("Collection not found", 404)
    return jsonify({"ok": True})


@app.post("/api/requests")
def create_request():
    payload = request.json or {}
    cid = payload.get("collectionId")
    req = store.normalize_request(payload.get("request") or {})
    req["id"] = store.new_id()
    with store.Transaction() as data:
        col = store.find_collection(data, cid)
        if not col:
            return bad("Collection not found", 404)
        col["requests"].append(req)
    return jsonify({"request": req, "collectionId": cid}), 201


@app.put("/api/requests/<rid>")
def update_request(rid):
    payload = request.json or {}
    with store.Transaction() as data:
        col, idx, existing = store.find_request(data, rid)
        if not existing:
            return bad("Request not found", 404)
        req = store.normalize_request({**existing, **(payload.get("request") or {})})
        req["id"] = rid
        target_cid = payload.get("collectionId") or col["id"]
        if target_cid != col["id"]:
            target = store.find_collection(data, target_cid)
            if not target:
                return bad("Target collection not found", 404)
            col["requests"].pop(idx)
            target["requests"].append(req)
        else:
            col["requests"][idx] = req
    return jsonify({"request": req, "collectionId": target_cid})


@app.post("/api/requests/<rid>/duplicate")
def duplicate_request(rid):
    with store.Transaction() as data:
        col, idx, existing = store.find_request(data, rid)
        if not existing:
            return bad("Request not found", 404)
        copy = store.normalize_request({**existing, "name": existing["name"] + " (copy)"})
        copy["id"] = store.new_id()
        col["requests"].insert(idx + 1, copy)
    return jsonify({"request": copy, "collectionId": col["id"]}), 201


@app.delete("/api/requests/<rid>")
def delete_request(rid):
    with store.Transaction() as data:
        col, idx, existing = store.find_request(data, rid)
        if not existing:
            return bad("Request not found", 404)
        col["requests"].pop(idx)
    return jsonify({"ok": True})


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
    req = store.normalize_request(req)
    with store.Transaction() as data:
        col = store.find_collection(data, payload.get("collectionId"))
        if not col:
            if not data["collections"]:
                data["collections"].append({"id": store.new_id(), "name": "Default", "requests": []})
            col = data["collections"][0]
        col["requests"].append(req)
    return jsonify({"request": req, "collectionId": col["id"], "warnings": warnings}), 201


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

    started = time.perf_counter()
    try:
        resp = requests.request(
            resolved["method"],
            url,
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
        if isinstance(e, requests.exceptions.ConnectionError) and host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
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
        "finalUrl": resp.url,
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
