import re
from urllib.parse import urlparse


CATEGORY_RULES = (
    ("10000000", "خوراک، لوازم و محصولات مراقبت حیوانات خانگی", ("حیوان خانگی", "سگ", "گربه", "پت شاپ", "pet shop", "petcare")),
    ("53161000", "لوازم آرایشی، مراقبت پوست و مو و محصولات زیبایی", ("آرایش", "میکاپ", "پوست", "مراقبت مو", "عطر", "ادکلن", "beauty", "cosmetic", "perfume")),
    ("66010100", "لوازم جانبی موبایل، قاب، کاور و اکسسوری دیجیتال", ("قاب", "کاور", "گلس", "case", "cover", "mobile accessory")),
    ("66010300", "موبایل، تبلت و محصولات دیجیتال", ("موبایل", "گوشی", "تبلت", "mobile", "phone")),
    ("63010300", "کفش، بوت، صندل و پاپوش", ("کفش", "بوت", "صندل", "shoe", "boot", "sneaker")),
    ("64010100", "طلا، جواهرات و زیورآلات", ("طلا", "جواهر", "زیور", "gold", "jewel")),
    ("60010200", "کتاب و محصولات فرهنگی", ("کتاب", "book")),
    ("62060100", "لوازم تحریر و نوشت‌افزار", ("تحریر", "نوشت افزار", "stationery")),
    ("86010400", "اسباب‌بازی، بازی فکری و محصولات کودک", ("اسباب بازی", "بازی فکری", "toy", "lego")),
    ("73040000", "لوازم خانه، آشپزخانه و دکوراسیون", ("خانه", "آشپزخانه", "دکور", "home", "kitchen")),
    ("50230100", "مواد غذایی، نوشیدنی و محصولات سوپرمارکتی", ("مواد غذایی", "سوپرمارکت", "خوراکی", "food", "market")),
    ("67010000", "پوشاک و اکسسوری مد", ("پوشاک", "لباس", "مانتو", "مزون", "شومیز", "fashion", "clothing", "wear", "label")),
)


def normalize_identifier(identifier):
    value = str(identifier or "").strip().lower()
    if "://" in value:
        parsed = urlparse(value)
        if parsed.netloc not in {"instagram.com", "www.instagram.com"}:
            raise ValueError("the URL must be an instagram.com profile URL")
        value = parsed.path.strip("/").split("/", 1)[0]
    value = value.lstrip("@").strip("/")
    if not re.fullmatch(r"[a-z0-9._]{1,30}", value):
        raise ValueError("use an Instagram username, @username, or profile URL")
    return f"@{value}"


def infer_category(profile):
    captions = " ".join(post.get("caption") or "" for post in profile.get("posts", []))
    text = " ".join(
        (profile.get("handle") or "", profile.get("name") or "",
         profile.get("biography") or "", captions)
    ).lower().replace("‌", " ")
    scored = []
    for order, (code, description, keywords) in enumerate(CATEGORY_RULES):
        score = sum(text.count(keyword) for keyword in keywords)
        if score:
            scored.append((score, -order, code, description))
    if not scored:
        return None, None
    _, _, code, description = max(scored)
    return code, description
