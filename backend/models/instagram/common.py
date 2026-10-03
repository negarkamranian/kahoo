"""Shared containers and fields in Instagram source payloads."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Edge(BaseModel, Generic[T]):
    node: T


class Connection(BaseModel, Generic[T]):
    edges: list[Edge[T]]


class DataList(BaseModel, Generic[T]):
    data: list[T]


class Caption(BaseModel):
    text: str


class SourceProfile(BaseModel):
    biography: str = ""


class CountConnection(BaseModel):
    count: int
