from datetime import date

from app.schemas.common import ChatTokenUsage
from app.schemas.usage import UsageDay, UsageRollupResponse


def test_usage_day():
    d = UsageDay(date=date(2026, 6, 2), input_tokens=10, output_tokens=20, estimated_cost_usd=0.001)
    assert d.estimated_cost_usd == 0.001


def test_usage_rollup_response():
    r = UsageRollupResponse(
        today=ChatTokenUsage(input_tokens=10, output_tokens=20, estimated_cost_usd=0.001),
        last_7_days=[UsageDay(date=date(2026, 6, 2), input_tokens=10, output_tokens=20, estimated_cost_usd=0.001)],
    )
    dumped = r.model_dump(mode="json")
    assert dumped["last_7_days"][0]["date"] == "2026-06-02"
