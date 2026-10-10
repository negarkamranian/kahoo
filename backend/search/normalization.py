from functools import lru_cache
from unicodedata import decimal, normalize

from hazm import Normalizer, Stemmer

_NORMALIZER = Normalizer()
_STEMMER = Stemmer()
SEARCH_STOPWORDS = {
    "از",
    "به",
    "با",
    "در",
    "برای",
    "و",
    "یا",
    "یک",
    "های",
    "این",
    "آن",
    "رو",
    "را",
    "که",
    "می",
    "shop",
    "store",
}


def normalize_persian(value: str) -> str:
    return _NORMALIZER.normalize(value)


@lru_cache(maxsize=8192)
def normalize_search(value: str) -> str:
    """Hazm normalization plus search-specific case, digit and token separators."""
    text = normalize_persian(normalize("NFKC", value)).lower()
    characters = []
    for char in text:
        if char.isdecimal():
            characters.append(str(decimal(char)))
        elif char.isalnum() or char == "_":
            characters.append(char)
        else:
            characters.append(" ")
    text = "".join(characters)
    return " ".join(text.split())


def query_tokens(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            token
            for token in normalize_search(value).split()
            if len(token) > 1 and token not in SEARCH_STOPWORDS
        )
    )


@lru_cache(maxsize=8192)
def token_variants(token: str) -> frozenset[str]:
    stem = _STEMMER.stem(token)
    if len(stem) > 2:
        return frozenset((token, stem))
    return frozenset((token,))
