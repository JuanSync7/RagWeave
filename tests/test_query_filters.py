from query import parse_filters


def test_parse_filters_supports_quoted_values():
    clean, filters = parse_filters(
        'source:"spec docs/design note.md" section:"Clock Domain Crossing" explain timing'
    )
    assert clean == "explain timing"
    assert filters["source_filter"] == "spec docs/design note.md"
    assert filters["heading_filter"] == "Clock Domain Crossing"


def test_parse_filters_supports_unquoted_values():
    clean, filters = parse_filters("source:doc.txt section:Intro what is this")
    assert clean == "what is this"
    assert filters["source_filter"] == "doc.txt"
    assert filters["heading_filter"] == "Intro"
