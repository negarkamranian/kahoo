#!/usr/bin/env python3
import os
from http.server import ThreadingHTTPServer

from backend.server import Handler, initialize_database


if __name__ == "__main__":
    host = os.environ.get("KAHOO_HOST", "127.0.0.1")
    port = int(os.environ.get("KAHOO_PORT", "4173"))
    initialize_database()
    print(f"Kahoo running at http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
