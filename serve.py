"""Serve Design Graph and a Trae design-draft directory on one origin.

The viewer stays at /. The draft is mounted at /draft so page HTML and its
sibling CSS keep their relative paths.
"""

import argparse
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

GRAPH_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DRAFT = r"D:\novelwrite\ai-stage\design-draft"


class DualRootHandler(SimpleHTTPRequestHandler):
    draft_root = DEFAULT_DRAFT
    extensions_map = {
        **getattr(SimpleHTTPRequestHandler, "extensions_map", {}),
        ".design": "application/json",
    }

    def end_headers(self):
        path = urlparse(self.path).path.lower()
        if path.endswith((".design", ".html", ".css", ".js")) or path in ("", "/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path):
        raw = unquote(urlparse(path).path)
        if raw == "/draft" or raw.startswith("/draft/"):
            root = os.path.normpath(self.draft_root)
            relative = raw[len("/draft"):].lstrip("/")
        else:
            root = os.path.normpath(GRAPH_ROOT)
            relative = raw.lstrip("/")
        full = os.path.normpath(os.path.join(root, *relative.split("/")))
        try:
            inside = os.path.commonpath([root, full]) == root
        except ValueError:
            inside = False
        if not inside:
            return os.path.join(root, "__forbidden__")
        return full


def main():
    parser = argparse.ArgumentParser(description="Serve Design Graph plus a Trae design draft.")
    parser.add_argument("--draft", default=os.environ.get("DESIGN_DRAFT_ROOT", DEFAULT_DRAFT))
    parser.add_argument("--port", type=int, default=3333)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    draft = os.path.normpath(args.draft)
    design_file = os.path.join(draft, "design-draft.design")
    if not os.path.isfile(design_file):
        raise SystemExit("design file not found: " + design_file)
    DualRootHandler.draft_root = draft
    server = ThreadingHTTPServer((args.host, args.port), DualRootHandler)
    print("Design Graph: http://%s:%s/?project=ai-stage" % (args.host, args.port))
    print("Draft:        " + draft)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
