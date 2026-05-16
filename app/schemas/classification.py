from pydantic import BaseModel
from typing import Literal


class ClassifyRequest(BaseModel):
    email_id: str
    # Optionally force a label (user override)
    override_label: Literal["important", "promotions", "spam", "social", "updates"] | None = None


class ClassifyResponse(BaseModel):
    email_id: str
    label: str
    confidence: float
    source: str
