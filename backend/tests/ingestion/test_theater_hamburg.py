from pathlib import Path

import pytest

from app.ingestion.scrapers.theater_hamburg import _extract_jwt


_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


class TestExtractJwt:
    def test_extracts_from_real_widget_js_fixture(self):
        js = (_FIXTURE_DIR / "theater_hamburg_widget_sample.js").read_text(encoding="utf-8")
        token = _extract_jwt(js)
        assert token is not None
        assert token.startswith("ey")
        assert token.count(".") == 2

    def test_returns_none_when_no_graphql_bearer_token_present(self):
        assert _extract_jwt("var x = 1; footerLogo:'/x.svg', ") is None

    def test_ignores_other_jwts_and_picks_graphql_bearer_one(self):
        js = (
            'someOtherToken:"eyBADAAA.BBB.CCC", '
            'graphqlBearerToken:"eyRIGHT.MID.SIG", '
            'yetAnother:"eyOTHER.XX.YY"'
        )
        assert _extract_jwt(js) == "eyRIGHT.MID.SIG"

    def test_returns_none_when_graphql_bearer_token_key_present_but_value_not_jwt_shaped(self):
        assert _extract_jwt('graphqlBearerToken:"not-a-jwt"') is None
