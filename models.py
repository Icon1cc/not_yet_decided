from pydantic import BaseModel, HttpUrl


class Competitor(BaseModel):
    reference: str
    competitor_retailer: str
    competitor_product_name: str
    competitor_url: HttpUrl
    competitor_price: float


class SourceMatch(BaseModel):
    source_reference: str
    competitors: list[Competitor]


Submission = list[SourceMatch]
