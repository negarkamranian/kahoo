import os
from http.server import ThreadingHTTPServer

from backend.database import PROJECT_ROOT, run_category_seed, run_migrations
from backend.server.http import Handler


def serve(args):
    run_migrations()
    run_category_seed(PROJECT_ROOT / "data/categories.sql")
    host = args.host or os.environ.get("KAHOO_HOST", "127.0.0.1")
    port = args.port if args.port is not None else int(os.environ.get("KAHOO_PORT", "4173"))
    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f"Kahoo running at http://{host}:{port}", flush=True)
        server.serve_forever()
