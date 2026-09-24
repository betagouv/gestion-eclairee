from typing import Any, Optional

import sqlalchemy
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import JSONB

from gesec.data.pipeline.db import pydantic_model_to_dtype


class ModelWithAny(BaseModel):
    delivery: Optional[Any] = None
    note: str = ""


def test_pydantic_model_to_dtype_maps_optional_any_to_jsonb():
    dtype = pydantic_model_to_dtype(ModelWithAny)

    assert dtype["delivery"] is JSONB
    assert dtype["note"] is sqlalchemy.types.TEXT
