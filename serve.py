"""Serve Design Graph, plus any Trae draft folders you mount.

The viewer stays at /. Every mounted folder is served under /draft/<id>/ so the
design file and the HTML pages sitting beside it keep their relative paths.

Mount a folder without restarting the server:

  * in the viewer — "＋ folder" in the toolbar, next to the project picker
  * over HTTP    — POST /api/mount  {"dir": "E:\\path\\to\\draft"}
                   (requires the X-DG-Mount: 1 header, loopback callers only)
  * at startup   — python serve.py --draft <path>   (repeatable)

A folder is mountable when it holds design-draft.design; the folder's own name
becomes the project id, so one folder is one project. Mounts are remembered in
.dg-mounts.json (gitignored) so they survive a restart. Unmount from the same
toolbar panel, or POST /api/unmount {"id": "..."}.
"""

import argparse
import json
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

GRAPH_ROOT = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(GRAPH_ROOT, "data", "manifest.json")
DESIGN_FILE = "design-draft.design"
MOUNT_HEADER = "X-DG-Mount"
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


class MountError(Exception):
    """A mount request that the user needs to fix (bad path, missing file)."""


def static_project_ids():
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return set()
    return {p.get("id") for p in (manifest.get("projects") or []) if p.get("id")}


def project_from_mount(entry):
    """The manifest entry the viewer boots from for a mounted draft."""
    return {
        "id": entry["id"],
        "name": entry["name"],
        "description": "Trae draft mounted from " + entry["dir"],
        "format": "trae",
        "design": "/draft/%s/%s" % (entry["id"], DESIGN_FILE),
    }


class Mounts:
    """The draft folders currently served under /draft/<id>/."""

    def __init__(self, path, static_ids=()):
        self.path = path
        self.static_ids = set(static_ids)
        self.items = []
        self._load()

    # ── persistence ────────────────────────────────────────────────
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                stored = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(stored, list):
            return
        seen = set()
        for item in stored:
            if not isinstance(item, dict):
                continue
            try:
                entry = self._describe(item.get("dir"), item.get("id"))
            except MountError as exc:
                print("note: dropping stored mount (%s)" % exc, file=sys.stderr)
                continue
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            self.items.append(entry)

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.items, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            print("warning: could not persist mounts: %s" % exc, file=sys.stderr)

    # ── lookup ─────────────────────────────────────────────────────
    def by_id(self, mount_id):
        for entry in self.items:
            if entry["id"] == mount_id:
                return entry
        return None

    def _unique_id(self, wanted):
        taken = {e["id"] for e in self.items} | self.static_ids
        if wanted not in taken:
            return wanted
        n = 2
        while "%s-%d" % (wanted, n) in taken:
            n += 1
        return "%s-%d" % (wanted, n)

    # ── mutation ───────────────────────────────────────────────────
    def _describe(self, raw_dir, wanted_id=None):
        """Validate a folder and return an entry without registering it."""
        if raw_dir is None or not str(raw_dir).strip():
            raise MountError("no folder given")
        folder = str(raw_dir).strip().strip('"').strip("'")
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            raise MountError("not a folder: " + folder)
        if not os.path.isfile(os.path.join(folder, DESIGN_FILE)):
            others = sorted(n for n in os.listdir(folder) if n.endswith(".design"))
            hint = " (found %s instead)" % ", ".join(others) if others else ""
            raise MountError("%s has no %s%s" % (folder, DESIGN_FILE, hint))
        name = os.path.basename(folder.rstrip("\\/")) or folder
        slug = re.sub(r"[^a-z0-9]+", "-", str(wanted_id or name).lower()).strip("-")
        return {
            "id": self._unique_id(slug or "draft"),
            "name": name,
            "dir": folder,
        }

    def add(self, raw_dir, wanted_id=None):
        entry = self._describe(raw_dir, wanted_id)
        existing = next((e for e in self.items if e["dir"] == entry["dir"]), None)
        if existing:
            raise MountError("already mounted as %s" % existing["id"])
        self.items.append(entry)
        self._save()
        return entry

    def remove(self, mount_id):
        before = len(self.items)
        self.items = [e for e in self.items if e["id"] != mount_id]
        if len(self.items) == before:
            return False
        self._save()
        return True


class GraphHandler(SimpleHTTPRequestHandler):
    mounts = Mounts(os.path.join(GRAPH_ROOT, ".dg-mounts.json"))
    extensions_map = {
        **getattr(SimpleHTTPRequestHandler, "extensions_map", {}),
        ".design": "application/json",
    }

    def log_message(self, fmt, *args):
        if "/api/" in (self.requestline or ""):
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        path = urlparse(self.path).path.lower()
        if path.endswith((".design", ".html", ".css", ".js")) or path in ("", "/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ── routing ────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/mounts":
            return self._send_json({"mounts": self.mounts.items})
        if path in ("/api/projects", "/data/manifest.json"):
            return self._send_json(self.manifest())
        return super().do_GET()

    def do_POST(self):
        path = (urlparse(self.path).path.rstrip("/") or "/")
        if path not in ("/api/mount", "/api/unmount"):
            return self._send_json({"error": "no such endpoint: " + path}, 404)
        if not self._local_mount_request():
            return self._send_json(
                {"error": "refused: mount requests must come from this machine's browser"}, 403)
        try:
            payload = self._read_json()
            if path == "/api/mount":
                entry = self.mounts.add(payload.get("dir"), payload.get("id"))
                print("mounted: %s -> /draft/%s/" % (entry["dir"], entry["id"]))
                return self._send_json({
                    "ok": True,
                    "mount": entry,
                    "project": project_from_mount(entry),
                    "message": "mounted %s at /draft/%s/" % (entry["dir"], entry["id"]),
                })
            if not self.mounts.remove(payload.get("id")):
                return self._send_json({"error": "no such mount: %s" % payload.get("id")}, 404)
            print("unmounted: %s" % payload.get("id"))
            return self._send_json({"ok": True, "message": "unmounted %s" % payload.get("id")})
        except MountError as exc:
            return self._send_json({"error": str(exc)}, 400)

    def _local_mount_request(self):
        # Mounting reads a filesystem path off this machine, so keep it to
        # loopback callers. The custom header makes browsers preflight the
        # request, which stops a stray web page from mounting a directory here.
        if self.client_address[0] not in LOOPBACK:
            return False
        if self.headers.get(MOUNT_HEADER) != "1":
            return False
        origin, host = self.headers.get("Origin"), self.headers.get("Host")
        if origin and host and urlparse(origin).netloc != host:
            return False
        return True

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= 64 * 1024:
            raise MountError("missing or oversized request body")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise MountError("request body is not valid JSON")
        if not isinstance(payload, dict):
            raise MountError("request body must be a JSON object")
        return payload

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def manifest(self):
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError) as exc:
            print("warning: cannot read %s: %s" % (MANIFEST_PATH, exc), file=sys.stderr)
            manifest = {}
        projects = list(manifest.get("projects") or [])
        present = {p.get("id") for p in projects}
        for entry in self.mounts.items:
            if entry["id"] not in present:
                projects.append(project_from_mount(entry))
                present.add(entry["id"])
        manifest["projects"] = projects
        return manifest

    # ── file resolution ────────────────────────────────────────────
    def translate_path(self, path):
        raw = unquote(urlparse(path).path)
        if raw == "/draft" or raw.startswith("/draft/"):
            rest = raw[len("/draft"):].lstrip("/")
            mount_id, _, relative = rest.partition("/")
            entry = self.mounts.by_id(mount_id)
            if entry is None:
                return os.path.join(GRAPH_ROOT, "__no_such_mount__")
            return self._safe_join(entry["dir"], relative)
        return self._safe_join(GRAPH_ROOT, raw.lstrip("/"))

    def _safe_join(self, root, relative):
        root = os.path.realpath(root)
        full = os.path.realpath(os.path.join(root, *relative.split("/")))
        try:
            inside = os.path.commonpath([root, full]) == root
        except ValueError:
            inside = False
        return full if inside else os.path.join(GRAPH_ROOT, "__forbidden__")


def main():
    parser = argparse.ArgumentParser(
        description="Serve Design Graph, plus any Trae draft folders you mount.")
    parser.add_argument("--draft", action="append", default=[], metavar="PATH",
                        help="mount this Trae draft folder at startup (repeatable)")
    parser.add_argument("--mounts-file", default=os.path.join(GRAPH_ROOT, ".dg-mounts.json"),
                        help="where to remember mounts between runs")
    parser.add_argument("--port", type=int, default=3333)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    seeds = list(args.draft)
    env_draft = os.environ.get("DESIGN_DRAFT_ROOT")
    if env_draft and not seeds:
        seeds.append(env_draft)

    mounts = Mounts(args.mounts_file, static_ids=static_project_ids())
    for seed in seeds:
        try:
            entry = mounts.add(seed)
            print("mounted: %s -> /draft/%s/" % (entry["dir"], entry["id"]))
        except MountError as exc:
            print("warning: --draft %s: %s" % (seed, exc), file=sys.stderr)

    GraphHandler.mounts = mounts
    server = ThreadingHTTPServer((args.host, args.port), GraphHandler)
    print("Design Graph:   http://%s:%s/" % (args.host, args.port))
    for entry in mounts.items:
        print("Mounted draft:  /draft/%s/  ->  %s" % (entry["id"], entry["dir"]))
    if not mounts.items:
        print("No drafts mounted yet — use “＋ folder” in the toolbar to point at one,")
        print("or restart with --draft <path>.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.server_close()


if __name__ == "__main__":
    main()
