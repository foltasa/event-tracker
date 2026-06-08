from datetime import date as date_cls

from pydantic import Field

from app.schemas.common import ChatTokenUsage, _JsonBase


class UsageDay(_JsonBase):
    date: date_cls
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class UsageRollupResponse(_JsonBase):
    today: ChatTokenUsage
    last_7_days: list[UsageDay] = Field(default_factory=list)
