from app.db.models import User


def test_get_user_profile_returns_new_shape_only(db_session, monkeypatch):
    from app.agent import memory, tools
    from app.agent.tools import get_user_profile

    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)

    db_session.add(User(
        id="local",
        interest_tags=["legacy"],
        taste_summary="legacy summary",
        about_me="I ride a bike",
        active_categories=["concerts", "party"],
        taste_facets={"concerts": {"artists": {"Nils Frahm": 1.0}}},
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    result = get_user_profile.invoke({})

    assert result == {
        "about_me": "I ride a bike",
        "active_categories": ["concerts", "party"],
        "taste_facets": {"concerts": {"artists": {"Nils Frahm": 1.0}}},
    }
    # Legacy fields are dropped from the tool response.
    assert "interest_tags" not in result
    assert "taste_summary" not in result
