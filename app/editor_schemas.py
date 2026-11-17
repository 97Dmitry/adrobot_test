from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import PositiveID


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Annotated[int, Field(strict=True, ge=1)]


class AddOffer(Revision):
    offer_id: PositiveID


class EditOffer(Revision):
    action: Literal["remove", "restore", "pin", "unpin"]
    pin: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None
