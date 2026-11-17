from typing import Annotated

import pycountry
from pydantic import BaseModel, Field, field_validator

PREFIX = "test_tsibizov_"
PositiveID = Annotated[int, Field(strict=True, gt=0)]


class CreateCampaign(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    countries: list[str] = Field(min_length=1, max_length=249)
    offer_id: PositiveID
    domain_id: PositiveID
    group_id: PositiveID
    traffic_source_id: PositiveID

    @field_validator("name")
    @classmethod
    def campaign_name(cls, value):
        value = value.strip()
        if not value.startswith(PREFIX):
            value = PREFIX + value
        if not value.removeprefix(PREFIX).strip():
            raise ValueError("Укажите название после test_tsibizov_.")
        return value

    @field_validator("countries")
    @classmethod
    def country_codes(cls, values):
        result = []
        for value in values:
            code = value.strip().upper()
            if len(code) != 2 or pycountry.countries.get(alpha_2=code) is None:
                raise ValueError(f"Неизвестный ISO-код страны: {code}.")
            if code not in result:
                result.append(code)
        return result
