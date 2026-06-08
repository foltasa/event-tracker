from app.schemas.common import UserSettings
from app.schemas.profile import OnboardingRequest, SettingsUpdate, UserProfileResponse, UserProfileUpdate


def test_user_profile_response():
    r = UserProfileResponse(
        city="Hamburg", interest_tags=["music"], about_me=None, taste_summary=None,
        settings=UserSettings(tool_toggles={}, llm_provider="openai", llm_model=None),
    )
    assert r.city == "Hamburg"


def test_user_profile_update_partial():
    u = UserProfileUpdate(interest_tags=["music"])
    assert u.about_me is None  # not set, defaults to None
    dumped = u.model_dump(exclude_unset=True)
    assert dumped == {"interest_tags": ["music"]}


def test_onboarding_request():
    o = OnboardingRequest(interest_tags=["music", "tech"], about_me="hi")
    assert o.interest_tags == ["music", "tech"]


def test_settings_update_partial():
    s = SettingsUpdate(llm_provider="anthropic")
    dumped = s.model_dump(exclude_unset=True)
    assert dumped == {"llm_provider": "anthropic"}
