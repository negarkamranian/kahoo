"""Shared validation types and the base input contract."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Count = Annotated[int, Field(strict=True, ge=0)]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TrimmedText = Annotated[str, StringConstraints(strip_whitespace=True)]
InstagramHandle = Annotated[str, StringConstraints(pattern=r"^@[a-z0-9._]{1,30}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(strict=True)
