from __future__ import annotations

import re


WIKI_LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_title(value: str) -> str:
    return " ".join(value.strip().lower().split())


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "untitled"


def normalize_tag(value: str) -> str:
    return value.strip().lower()


def extract_wiki_links(markdown: str) -> list[str]:
    seen: set[str] = set()
    links: list[str] = []

    for match in WIKI_LINK_RE.findall(markdown):
        title = " ".join(match.strip().split())
        normalized = normalize_title(title)
        if title and normalized not in seen:
            seen.add(normalized)
            links.append(title)

    return links
