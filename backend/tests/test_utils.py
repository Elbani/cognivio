from app.utils import extract_wiki_links, normalize_tag, normalize_title


def test_extract_wiki_links_normalizes_and_deduplicates_titles() -> None:
    markdown = "Link [[ Project Plan ]] and [[project   plan]] plus [[Daily Note]]."

    assert extract_wiki_links(markdown) == ["Project Plan", "Daily Note"]


def test_normalizers_trim_case_and_spacing() -> None:
    assert normalize_title("  My   Linked   Note ") == "my linked note"
    assert normalize_tag("  Research ") == "research"
