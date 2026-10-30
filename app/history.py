"""Git-backed version history of saved requests.

The history lives in its own git repository (``$CURLBOOK_DATA_DIR/history``) with one file per
request: ``requests/<id>.json``. ``store.json`` stays the source of truth; this module mirrors the
requests into the repo and commits after each user-visible change. Globals are deliberately *not*
tracked: they hold tokens and change on every send that runs an extraction rule.

History is best-effort: if git fails, saving still succeeds and the error is only logged.
"""
import difflib
import json
import logging
import os
import re
import shutil
import subprocess

from curl_builder import build_curl

log = logging.getLogger("curlbook.history")

DATA_DIR = os.environ.get("CURLBOOK_DATA_DIR", "/data")
REPO_DIR = os.environ.get("CURLBOOK_HISTORY_DIR") or os.path.join(DATA_DIR, "history")
REQ_DIR = "requests"
ENABLED = (
    os.environ.get("CURLBOOK_HISTORY", "1").strip().lower() not in ("0", "false", "no", "off")
    and shutil.which("git") is not None
)
LOG_LIMIT = 300
DELETED_LIMIT = 100

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_RID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Curlbook", "GIT_AUTHOR_EMAIL": "curlbook@localhost",
    "GIT_COMMITTER_NAME": "Curlbook", "GIT_COMMITTER_EMAIL": "curlbook@localhost",
    "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
}
# Keep the user's global git config (signing, hooks, pagers…) from interfering.
_GIT_OPTS = [
    "-c", "safe.directory=*", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
    "-c", "core.quotepath=false", "-c", "core.autocrlf=false", "-c", "log.showSignature=false",
]

_initialised = False


class HistoryError(RuntimeError):
    pass


# --------------------------------------------------------------------- git ----
def _run(*args, check=True):
    try:
        p = subprocess.run(
            ["git", *_GIT_OPTS, *args], cwd=REPO_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, env={**os.environ, **_GIT_ENV},
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise HistoryError(f"git {args[0]} failed: {e}") from e
    if check and p.returncode != 0:
        raise HistoryError(f"git {args[0]} failed: {(p.stderr or p.stdout).strip()}")
    return p


def _git(*args) -> str:
    return _run(*args).stdout


def _has_commits() -> bool:
    return _run("rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


def _ensure_repo() -> None:
    global _initialised
    if _initialised:
        return
    os.makedirs(os.path.join(REPO_DIR, REQ_DIR), exist_ok=True)
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        _git("init", "-q")
        _git("symbolic-ref", "HEAD", "refs/heads/main")
        log.info("initialised request history repo at %s", REPO_DIR)
    _initialised = True


# ---------------------------------------------------------------- records ----
def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _record(req: dict, col: dict) -> dict:
    return {"collectionId": col["id"], "collectionName": col["name"], "request": req}


def _path(rid: str) -> str:
    return f"{REQ_DIR}/{rid}.json"


def _check_rid(rid: str) -> str:
    if not _RID_RE.match(rid or ""):
        raise HistoryError("Invalid request id")
    return rid


def _check_sha(sha: str) -> str:
    if not _SHA_RE.match(sha or ""):
        raise HistoryError("Invalid version id")
    return sha


def record_at(rid: str, rev: str):
    """The stored record ({collectionId, collectionName, request}) at a revision, or None."""
    p = _run("show", f"{rev}:{_path(_check_rid(rid))}", check=False)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


# ------------------------------------------------------------------ write ----
def sync(data: dict, message: str):
    """Mirror all requests into the repo and commit if anything changed. Returns the new sha or None.

    Never raises: history problems must not break saving.
    """
    if not ENABLED:
        return None
    try:
        _ensure_repo()
        req_dir = os.path.join(REPO_DIR, REQ_DIR)
        wanted = {}
        for col in data.get("collections", []):
            for r in col.get("requests", []):
                if _RID_RE.match(str(r.get("id", ""))):
                    wanted[f"{r['id']}.json"] = _dump(_record(r, col))
        for name in os.listdir(req_dir):
            if name.endswith(".json") and name not in wanted:
                os.unlink(os.path.join(req_dir, name))
        for name, content in wanted.items():
            path = os.path.join(req_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    if f.read() == content:
                        continue
            except FileNotFoundError:
                pass
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        _git("add", "-A", "--", REQ_DIR)
        if _run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return None  # nothing changed (e.g. saving without edits)
        _git("commit", "-q", "--no-verify", "-m", message)
        return _git("rev-parse", "HEAD").strip()
    except Exception as e:  # noqa: BLE001 - best effort by design
        log.warning("history commit failed (%s): %s", message, e)
        return None


def startup(data: dict) -> None:
    """Create the repo on first run (snapshotting existing requests) and pick up hand-edits."""
    if not ENABLED:
        log.info("request history disabled (%s)", "git not found" if not shutil.which("git") else "CURLBOOK_HISTORY=0")
        return
    try:
        _ensure_repo()
        first = not _has_commits()
    except Exception as e:  # noqa: BLE001
        log.warning("history unavailable: %s", e)
        return
    n = sum(len(c.get("requests", [])) for c in data.get("collections", []))
    sync(data, f"Initial snapshot ({n} request{'s' if n != 1 else ''})" if first else "Sync external changes")


# ------------------------------------------------------------------- read ----
def versions(rid: str) -> list:
    """Commits touching a request, newest first: [{sha, date, message, kind}] (kind: add/modify/delete)."""
    _check_rid(rid)
    if not ENABLED or not os.path.isdir(os.path.join(REPO_DIR, ".git")) or not _has_commits():
        return []
    out = _git("log", f"-n{LOG_LIMIT}", "--no-renames", "--format=%x1e%H%x1f%aI%x1f%s", "--name-status",
               "--", _path(rid))
    entries = []
    for block in out.split("\x1e"):
        if not block.strip():
            continue
        head, _, rest = block.partition("\n")
        sha, date, subject = (head.split("\x1f") + ["", "", ""])[:3]
        status = rest.strip()[:1]
        entries.append({"sha": sha, "date": date, "message": subject,
                        "kind": {"A": "add", "D": "delete"}.get(status, "modify")})
    return entries


def version(rid: str, sha: str) -> dict:
    """The request as of a commit. For a deletion commit, the content just before it was deleted."""
    _check_rid(rid)
    _check_sha(sha)
    rec = record_at(rid, sha)
    deleted = rec is None
    if deleted:
        rec = record_at(rid, f"{sha}^")
    if rec is None:
        raise HistoryError("Version not found")
    return {"record": rec, "deleted": deleted}


def deleted_requests(present_ids) -> list:
    """Most recent deletion of each request that is not currently in the store."""
    if not ENABLED or not os.path.isdir(os.path.join(REPO_DIR, ".git")) or not _has_commits():
        return []
    present = set(present_ids)
    out = _git("log", "--no-renames", "--diff-filter=D", "--format=%x1e%H%x1f%aI%x1f%s", "--name-only",
               "--", REQ_DIR)
    seen, items = set(), []
    for block in out.split("\x1e"):
        if not block.strip():
            continue
        head, _, rest = block.partition("\n")
        sha, date, subject = (head.split("\x1f") + ["", "", ""])[:3]
        for line in rest.split("\n"):
            line = line.strip()
            if not (line.startswith(REQ_DIR + "/") and line.endswith(".json")):
                continue
            rid = line[len(REQ_DIR) + 1:-5]
            if rid in seen or rid in present or not _RID_RE.match(rid):
                continue
            seen.add(rid)
            rec = record_at(rid, f"{sha}^")
            if not rec:
                continue
            req = rec.get("request") or {}
            items.append({
                "id": rid, "sha": sha, "date": date, "message": subject,
                "name": req.get("name", ""), "method": req.get("method", "GET"), "url": req.get("url", ""),
                "collectionId": rec.get("collectionId"), "collectionName": rec.get("collectionName", ""),
            })
            if len(items) >= DELETED_LIMIT:
                return items
    return items


# ------------------------------------------------------------ rendering ----
def render(rec) -> str:
    """Readable text form used for diffs: metadata comments + the curl command."""
    if not rec:
        return ""
    req = rec.get("request") or {}
    lines = [f"# name: {req.get('name', '')}", f"# collection: {rec.get('collectionName', '')}"]
    if req.get("tags"):
        lines.append(f"# tags: {', '.join(req['tags'])}")
    for x in req.get("extractions") or []:
        src = x.get("source", "body")
        lines.append(f"# extract: {{{{{x.get('var', '')}}}}} <- {src}" + (f": {x.get('path', '')}" if src != "status" else ""))
    for h in req.get("headers") or []:
        if not h.get("enabled", True) and h.get("key"):
            lines.append(f"# disabled header: {h['key']}: {h.get('value', '')}")
    return "\n".join(lines) + "\n" + build_curl(req) + "\n"


def diff(old_rec, new_rec, old_label: str, new_label: str) -> str:
    a, b = render(old_rec).splitlines(), render(new_rec).splitlines()
    return "\n".join(difflib.unified_diff(a, b, old_label, new_label, lineterm="", n=3))


# Fields compared to build a readable "Update" commit message.
_FIELDS = [("name", "name"), ("method", "method"), ("url", "url"), ("headers", "headers"), ("body", "body"),
           ("options", "options"), ("extractions", "extract rules"), ("tags", "tags")]


def changed_fields(old: dict, new: dict) -> list:
    return [label for key, label in _FIELDS if old.get(key) != new.get(key)]
