from app.agent.facets import apply_facet_delta, initial_from_form


def test_apply_facet_delta_increments_and_clamps_at_one():
    facets = {"concerts": {"artists": {"Die Sterne": 0.8}}}
    apply_facet_delta(facets, "concerts", "artists", "Die Sterne", 0.5)
    assert facets["concerts"]["artists"]["Die Sterne"] == 1.0


def test_apply_facet_delta_creates_missing_structure():
    facets = {}
    apply_facet_delta(facets, "party", "genres", "techno", 0.4)
    assert facets["party"]["genres"]["techno"] == 0.4


def test_apply_facet_delta_prunes_when_reaches_zero_or_below():
    facets = {"concerts": {"disliked.genres": {"edm": 0.3}}}
    apply_facet_delta(facets, "concerts", "disliked.genres", "edm", -0.5)
    assert "edm" not in facets["concerts"]["disliked.genres"]


def test_apply_facet_delta_leaves_other_fields_untouched():
    facets = {"concerts": {"artists": {"A": 0.5}, "genres": {"punk": 0.7}}}
    apply_facet_delta(facets, "concerts", "artists", "B", 0.6)
    assert facets["concerts"]["genres"]["punk"] == 0.7


def test_initial_from_form_uses_default_weight():
    out = initial_from_form(["Die Sterne", "Tocotronic"], weight=0.8)
    assert out == {"Die Sterne": 0.8, "Tocotronic": 0.8}


def test_initial_from_form_strips_whitespace_and_drops_empties():
    out = initial_from_form([" Die Sterne ", "", "  ", "Interpol"], weight=0.8)
    assert out == {"Die Sterne": 0.8, "Interpol": 0.8}
