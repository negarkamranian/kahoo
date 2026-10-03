#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import connect, run_migrations
from backend.search import embed_pending_documents, embedding_enabled, sync_search_documents


def main():
    parser = argparse.ArgumentParser(description="Refresh Kahoo search documents and embeddings")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--all", action="store_true", help="embed every pending or stale-model document"
    )
    args = parser.parse_args()
    run_migrations()
    with connect() as database:
        changed = sync_search_documents(database)
        embedded = 0
        while True:
            batch = embed_pending_documents(database, max(1, args.batch_size))
            embedded += batch
            if not args.all or batch < max(1, args.batch_size):
                break
            print(f"embedded so far: {embedded}", flush=True)
    print(f"documents needing embeddings: {changed}")
    print(f"documents embedded: {embedded}")
    if not embedding_enabled():
        print("embedding provider disabled; set EMBEDDING_API_URL to enable semantic search")


if __name__ == "__main__":
    main()
