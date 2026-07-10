from app.db.models import User


def test_get_user_profile_returns_active_categories_and_facets(db_session, monkeypatch):
    from app.agent import memory, tools
    from app.agent.tools import get_user_profile

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    db_session.add(User(
        id="local",
        active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"Die Sterne": 0.8}}},
        interest_tags=["music"],
        taste_summary="likes indie",
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    result = get_user_profile.invoke({})
    assert result["active_categories"] == ["concerts"]
    assert result["taste_facets"]["concerts"]["artists"]["Die Sterne"] == 0.8
    assert result["interest_tags"] == ["music"]
