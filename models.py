from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional


class Competitor(BaseModel):
    reference: str
    competitor_retailer: str
    competitor_product_name: str
    competitor_url: Optional[str] = None
    competitor_price: Optional[float] = None

    @field_validator("competitor_url", mode="before")
    @classmethod
    def truncate_url(cls, v):
        if v and len(str(v)) > 2083:
            return None
        return v


class SourceMatch(BaseModel):
    source_reference: str
    competitors: list[Competitor]


Submission = list[SourceMatch]
