import re
import unicodedata

PERSIAN_TRANSLATION = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "ٱ": "ا",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)


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


PERSIAN_SUFFIXES = ("ترین", "تر", "هایی", "های", "ها")


DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")


def normalize_search(value):
    """Canonical form shared by indexing, retrieval, metadata, and analytics."""
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = DIACRITICS.sub("", value).translate(PERSIAN_TRANSLATION)
    value = value.replace("\u200c", " ").replace("ـ", " ")
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def query_tokens(value):
    return [
        token
        for token in normalize_search(value).split()
        if len(token) > 1 and token not in SEARCH_STOPWORDS
    ]


def token_variants(token):
    variants = {token}
    for suffix in PERSIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            variants.add(token[: -len(suffix)])
    return variants
