"""Serialize models only at the HTTP/CLI output boundary."""

from datetime import date, datetime
from decimal import Decimal
from functools import singledispatch

from pydantic import BaseModel


@singledispatch
def json_default(value):
    raise TypeError(f"Cannot serialize {type(value).__name__}")


@json_default.register(date)
@json_default.register(datetime)
def date_json(value):
    return value.isoformat()


@json_default.register(Decimal)
def decimal_json(value):
    return float(value)


@json_default.register(BaseModel)
def model_json(value):
    return value.model_dump(exclude_unset=True)
