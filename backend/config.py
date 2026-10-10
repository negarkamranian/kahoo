"""Read environment configuration once at startup."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment():
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / ".env.example", override=False)


class Settings(BaseModel):
    database_url: str = Field(repr=False)
    host: str
    port: int
    admin_token: str = Field(repr=False)
    meta_graph_version: str
    meta_ig_user_id: str
    meta_access_token: str = Field(repr=False)
    embedding_api_url: str
    embedding_api_key: str = Field(repr=False)
    embedding_model: str
    rerank_api_url: str
    rerank_min_score: float = Field(ge=0, le=1)
    product_vision_api_url: str
    product_vision_api_key: str = Field(repr=False)
    product_vision_model: str
    product_vision_timeout: int = Field(ge=1, le=120)
    product_vision_max_images: int = Field(ge=1, le=20)

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
            rerank_api_url=os.environ["RERANK_API_URL"],
            rerank_min_score=float(os.environ["RERANK_MIN_SCORE"]),
            product_vision_api_url=os.environ["PRODUCT_VISION_API_URL"],
            product_vision_api_key=os.environ["PRODUCT_VISION_API_KEY"],
            product_vision_model=os.environ["PRODUCT_VISION_MODEL"],
            product_vision_timeout=int(os.environ["PRODUCT_VISION_TIMEOUT"]),
            product_vision_max_images=int(os.environ["PRODUCT_VISION_MAX_IMAGES"]),
        )


load_environment()
settings = Settings.from_environment()
