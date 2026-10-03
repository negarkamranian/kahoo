from http.server import ThreadingHTTPServer

from backend.database import initialize_database
from backend.server.http import Handler


def serve(args):
    initialize_database()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        print(f"Kahoo running at http://{args.host}:{args.port}", flush=True)
        server.serve_forever()
