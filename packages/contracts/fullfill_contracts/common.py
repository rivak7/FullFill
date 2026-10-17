"""Base rules shared by JSON contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1)]
Quantity = Annotated[int, Field(ge=0, strict=True)]
PositiveQuantity = Annotated[int, Field(gt=0, strict=True)]
Revision = Annotated[int, Field(ge=1, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
