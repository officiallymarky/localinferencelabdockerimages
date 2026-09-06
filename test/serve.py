#!/usr/bin/env python3
"""Tiny test-only HTTP server: serves fixtures/tags.json for ANY path/query.

The watchdog appends '&page=N' to its API base URL, so a plain static file
server 404s. This responds the same JSON regardless of what came in.
Run: python3 serve.py [port]   (default 8001)
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "tags.json")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8001

with open(FIXTURE) as f:
    BODY = f.read().encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("fixture server on :{}  (serving tags.json for any path)".format(PORT))
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
