"""Single-file JSON persistence with atomic writes."""
import json
import os
import tempfile
import threading
import uuid

DATA_DIR = os.environ.get("CURLBOOK_DATA_DIR", "/data")
STORE_PATH = os.path.join(DATA_DIR, "store.json")

_lock = threading.RLock()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _default_store() -> dict:
    return {
        "collections": [{"id": new_id(), "name": "Default", "requests": []}],
        "globals": {},
    }


def default_request(name: str = "New Request") -> dict:
    return {
        "id": new_id(),
        "name": name,
        "method": "GET",
        "url": "",
        "headers": [],
        "body": "",
        "options": {"insecure": False, "followRedirects": True, "timeout": 30},
        "extractions": [],
    }


def normalize_request(req: dict) -> dict:
    """Fill in missing fields so the frontend can rely on the shape."""
    base = default_request(req.get("name") or "New Request")
    out = {**base, **{k: v for k, v in req.items() if v is not None}}
    out["options"] = {**base["options"], **(req.get("options") or {})}
    out["headers"] = [
        {
            "key": str(h.get("key", "")),
            "value": str(h.get("value", "")),
            "enabled": bool(h.get("enabled", True)),
        }
        for h in (out.get("headers") or [])
    ]
    out["extractions"] = [
        {
            "var": str(e.get("var", "")),
            "source": e.get("source", "body") if e.get("source") in ("body", "header", "status") else "body",
            "path": str(e.get("path", "")),
        }
        for e in (out.get("extractions") or [])
    ]
    out["method"] = str(out.get("method") or "GET").upper()
    out.pop("rawCurl", None)
    return out


class StoreCorruptError(RuntimeError):
    pass


def load() -> dict:
    with _lock:
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            data = _default_store()
            save(data)
            return data
        if not raw.strip():
            data = _default_store()
            save(data)
            return data
        try:
            data = json.loads(raw)
        except ValueError as e:
            # Never overwrite a file the user may have hand-edited; surface the problem instead.
            raise StoreCorruptError(f"{STORE_PATH} is not valid JSON ({e}). Fix or remove the file.") from e
        data.setdefault("collections", [])
        data.setdefault("globals", {})
        return data


def save(data: dict) -> None:
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".store-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.chmod(tmp, 0o644)
            os.replace(tmp, STORE_PATH)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


class Transaction:
    """Context manager: load, mutate, save under a lock."""

    def __enter__(self):
        _lock.acquire()
        try:
            self.data = load()
        except Exception:
            _lock.release()
            raise
        return self.data

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                save(self.data)
        finally:
            _lock.release()
        return False


def find_collection(data: dict, cid: str):
    return next((c for c in data["collections"] if c["id"] == cid), None)


def find_request(data: dict, rid: str):
    for c in data["collections"]:
        for i, r in enumerate(c["requests"]):
            if r["id"] == rid:
                return c, i, r
    return None, None, None
