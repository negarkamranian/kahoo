"""Read environment configuration once at startup."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment():
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / ".env.example", override=False)


@dataclass
class Settings:
    database_url: str = field(repr=False)
    host: str
    port: int
    admin_token: str = field(repr=False)
    meta_graph_version: str
    meta_ig_user_id: str
    meta_access_token: str = field(repr=False)
    embedding_api_url: str
    embedding_api_key: str = field(repr=False)
    embedding_model: str

    @classmethod
    def from_environment(cls):
        return cls(
            database_url=os.environ["DATABASE_URL"],
            host=os.environ["KAHOO_HOST"],
            port=int(os.environ["KAHOO_PORT"]),
            admin_token=os.environ["KAHOO_ADMIN_TOKEN"],
            meta_graph_version=os.environ["META_GRAPH_VERSION"],
            meta_ig_user_id=os.environ["META_IG_USER_ID"],
            meta_access_token=os.environ["META_ACCESS_TOKEN"],
            embedding_api_url=os.environ["EMBEDDING_API_URL"],
            embedding_api_key=os.environ["EMBEDDING_API_KEY"],
            embedding_model=os.environ["EMBEDDING_MODEL"],
        )


load_environment()
settings = Settings.from_environment()
