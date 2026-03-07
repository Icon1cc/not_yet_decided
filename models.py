from pydantic import BaseModel, HttpUrl
from typing import Optional


class Competitor(BaseModel):
    reference: str
    competitor_retailer: str
    competitor_product_name: str
    competitor_url: Optional[HttpUrl] = None
    competitor_price: Optional[float] = None


class SourceMatch(BaseModel):
    source_reference: str
    competitors: list[Competitor]


Submission = list[SourceMatch]
