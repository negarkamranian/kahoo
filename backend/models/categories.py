"""Category trees, links, GS1 publications, and category generation contracts."""

from typing import Literal

from pydantic import BaseModel, Field

from backend.models.common import Count, NonEmptyText


class CategoryNode(BaseModel):
    code: str
    parent_code: str | None
    level: Literal[1, 2, 3, 4]
    label_fa: str
    label_en: str | None
    icon: str | None
    count: Count
    children: list["CategoryNode"]


class CategoryLink(BaseModel):
    code: str
    label: str
    confidence: float | None = None
    source: str | None = None
    source_url: str | None = None


class GpcNode(BaseModel):
    code: int = Field(validation_alias="Code")
    title: NonEmptyText = Field(validation_alias="Title")
    level: int = Field(ge=1, validation_alias="Level")
    active: bool = Field(validation_alias="Active")
    children: list["GpcNode"] = Field(default_factory=list, validation_alias="Childs")


class GpcPublication(BaseModel):
    nodes: list[GpcNode] = Field(validation_alias="Schema")


class CategoryPolicy(BaseModel):
    source: NonEmptyText
    source_publication_id: int
    persian_publication_id: int
    allowed_segments: list[str]
    excluded_terms: list[str]
    segment_labels_fa: dict[str, NonEmptyText]
    segment_excluded_terms: dict[str, list[str]]


class CategoryBuildResult(BaseModel):
    categories: Count
    excluded_branches: Count
    output: str
