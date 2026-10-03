import os
from http.server import ThreadingHTTPServer

from backend.database import initialize_database
from backend.server.http import Handler


def serve(args):
    initialize_database()
    host = args.host or os.environ.get("KAHOO_HOST", "127.0.0.1")
    port = args.port if args.port is not None else int(os.environ.get("KAHOO_PORT", "4173"))
    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f"Kahoo running at http://{host}:{port}", flush=True)
        server.serve_forever()
