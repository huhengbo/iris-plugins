from iris_plugin_metatube.similarity import levenshtein, title_similarity
from iris_plugin_metatube.substitution import SubstitutionTable


def test_parse_ignores_blank_keys_and_later_lines_win_case_insensitively() -> None:
    table = SubstitutionTable.parse("a=1\n\n =x\nA=2\nbare\n b = c d ")

    assert table.substitute_text("aAb") == "2Ac d"
    assert table.substitute_items(["A", "bare", "B", "other"]) == ["2", "c d", "other"]


def test_substitute_text_is_case_sensitive_and_ordered() -> None:
    table = SubstitutionTable.parse("ab=X\nX=Y")

    assert table.substitute_text("abAB") == "YAB"


def test_substitute_items_deletes_blank_targets() -> None:
    table = SubstitutionTable.parse("x=\ny=  \nz=w")

    assert table.substitute_items(["x", "y", "z", "k"]) == ["w", "k"]


def test_levenshtein_and_similarity() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert title_similarity(("SSIS-001", "Title A"), ("ssis-001", "title a")) == 1.0
    assert title_similarity(("A", "B"), ("", "")) == 0.0
    assert title_similarity(("SSIS-001", "Title"), ("XXX-999", "Other")) < 0.8
