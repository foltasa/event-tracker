import pytest

from app.agent.memory_blob import EditError, apply_edit


def test_append_into_empty():
    new = apply_edit("", "", "User lives in Eimsbüttel", cap=200, label="facts_md")
    assert new == "User lives in Eimsbüttel"


def test_append_onto_existing_adds_single_newline():
    new = apply_edit("a", "", "b", cap=200, label="facts_md")
    assert new == "a\nb"


def test_append_onto_blob_ending_in_newline_no_double():
    new = apply_edit("a\n", "", "b", cap=200, label="facts_md")
    assert new == "a\nb"


def test_replace_unique():
    new = apply_edit("x\ny\nz", "y", "Y", cap=200, label="facts_md")
    assert new == "x\nY\nz"


def test_replace_ambiguous_raises():
    with pytest.raises(EditError, match="matches 2 locations"):
        apply_edit("a\na\nb", "a", "c", cap=200, label="facts_md")


def test_replace_not_found_raises():
    with pytest.raises(EditError, match="not found"):
        apply_edit("a", "xyz", "c", cap=200, label="facts_md")


def test_remove_full_line():
    new = apply_edit("a\nb\nc", "b\n", "", cap=200, label="facts_md")
    assert new == "a\nc"


def test_both_empty_raises():
    with pytest.raises(EditError, match="no-op"):
        apply_edit("anything", "", "", cap=200, label="facts_md")


def test_cap_overflow_on_append_raises():
    blob = "\n".join(str(i) for i in range(199))  # 199 lines
    with pytest.raises(EditError, match="would exceed cap"):
        apply_edit(blob, "", "x\ny", cap=200, label="facts_md")  # would be 201


def test_cap_edge_exactly_at_limit():
    blob = "\n".join(str(i) for i in range(199))  # 199 lines
    new = apply_edit(blob, "", "x", cap=200, label="facts_md")  # exactly 200
    assert len(new.splitlines()) == 200


def test_pre_existing_over_cap_blob_first_edit_raises():
    blob = "\n".join(str(i) for i in range(250))  # already over cap
    with pytest.raises(EditError, match="would exceed cap"):
        apply_edit(blob, "", "extra", cap=200, label="facts_md")


def test_label_appears_in_error_message():
    with pytest.raises(EditError, match="taste_summary"):
        apply_edit("foo", "", "", cap=20, label="taste_summary")
