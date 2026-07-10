import pytest
from pydantic import ValidationError


def test_about_me_response_shape():
    from app.schemas.about_me import AboutMeResponse
    resp = AboutMeResponse(
        active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"Die Sterne": 0.8}}},
        taste_summary="likes indie rock",
    )
    assert resp.model_dump()["active_categories"] == ["concerts"]


def test_about_me_update_rejects_unknown_category():
    from app.schemas.about_me import AboutMeUpdate
    with pytest.raises(ValidationError):
        AboutMeUpdate(active_categories=["nonsense"])


def test_about_me_update_partial_is_allowed():
    from app.schemas.about_me import AboutMeUpdate
    u = AboutMeUpdate(taste_summary="new")
    assert u.active_categories is None
    assert u.taste_facets is None
    assert u.taste_summary == "new"
