"""GS1 publication and local category-policy contracts."""

from pydantic import BaseModel, Field

from backend.models import NonEmptyText


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
