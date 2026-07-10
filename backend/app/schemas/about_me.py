"""API contracts for the About Me page."""
from pydantic import Field, field_validator

from app.agent.categories import USER_SELECTABLE_CATEGORIES
from app.schemas.common import _JsonBase


class AboutMeResponse(_JsonBase):
    active_categories: list[str] | None = None
    taste_facets: dict = Field(default_factory=dict)
    taste_summary: str | None = None


class AboutMeUpdate(_JsonBase):
    active_categories: list[str] | None = None
    taste_facets: dict | None = None
    taste_summary: str | None = None

    @field_validator("active_categories")
    @classmethod
    def _check_categories(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        unknown = [c for c in v if c not in USER_SELECTABLE_CATEGORIES]
        if unknown:
            raise ValueError(f"unknown categories: {unknown}")
        return v
