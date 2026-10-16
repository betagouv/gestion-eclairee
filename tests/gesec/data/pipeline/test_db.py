from typing import Any, Optional

import sqlalchemy
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import JSONB

from gesec.data.pipeline.db import pydantic_model_to_table, sqltype_for_annotation


class ModelWithAny(BaseModel):
    delivery: Optional[Any] = None
    note: str = ""


def test_pydantic_model_to_table_maps_optional_any_to_jsonb():
    table = pydantic_model_to_table(ModelWithAny, "t")

    assert isinstance(table.c.delivery.type, JSONB)
    assert isinstance(table.c.note.type, sqlalchemy.types.TEXT)


def test_sqltype_for_annotation_maps_scalars():
    assert isinstance(sqltype_for_annotation(str), sqlalchemy.types.TEXT)
    assert isinstance(sqltype_for_annotation(int), sqlalchemy.types.INTEGER)
    assert isinstance(sqltype_for_annotation(Optional[int]), sqlalchemy.types.INTEGER)
    assert isinstance(sqltype_for_annotation(dict), JSONB)
