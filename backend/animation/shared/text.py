"""Comparing texts: whether two titles are about the same thing, and how much of a script's
wording another script already has.

Copied from the repository this engine was born in (the Shorts factory and the documentary
engine it shared code with), so that this project stands on its own.
"""
import re
import unicodedata

SHINGLE = 4
# Words too common in this kind of title to say that two questions are about the same thing.
_COMMON_WORDS = frozenset("para como quien cual cuando donde este esta esto estos estas pero porque sobre desde hasta entre "
                          "todo todos tiene tienen pasa pasaria seria fuera hubiera durante hace hacen puede pueden".split())


def words(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.findall(r"[0-9a-zñ]+", plain)

def shingles(text: str, n: int = SHINGLE) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}

def shared_wording(new: str, old: str) -> float:
    """Share of the new text's four-word sequences that the old one also has (0-1)."""
    mine = shingles(new)
    return round(len(mine & shingles(old)) / len(mine), 3) if mine else 0.0


def _keywords(title: str) -> set[str]:
    return {w for w in words(title) if len(w) >= 4 and w not in _COMMON_WORDS}


def similar_titles(title: str, previous: list[str]) -> list[str]:
    """Earlier titles that are about the same thing as this one: they share at least two
    significant words, and those are half or more of the shorter title."""
    mine = _keywords(title)
    out = []
    for other in previous:
        theirs = _keywords(other)
        shared = len(mine & theirs)
        if mine and theirs and shared >= 2 and shared / min(len(mine), len(theirs)) >= 0.5:
            out.append(other)
    return out
