#!/usr/bin/env python3
"""Build deterministic catalog shards from a public Basaliro JSON snapshot."""

import argparse
import json
import math
import re
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES = {
    "beauty": ("53161000", ("آرایش", "میکاپ", "پوست", "ادکلن", "عطر", "زیبایی", "بهداشتی", "ناخن", "cosmetic", "beauty", "haircare", "skincare")),
    "shoe_bag": ("63010300", ("کفش", "کیف", "صندل", "کتونی", "نیم بوت", "پاپوش", "shoe", "چرم")),
    "jewelry": ("64010100", ("طلا", "جواهر", "نقره", "بدلیجات", "زیور", "اکسسوری", "gold", "jewelry")),
    "mobile": ("66010300", ("موبایل", "گوشی", "قاب", "کاور", "گلس", "لپتاپ", "دیجیتال", "کامپیوتر", "هدفون")),
    "home": ("73040000", ("لوازم خانگی", "لوازم‌خانگی", "آشپزخانه", "دکور", "ظروف", "فرش", "مبلمان", "جهیزیه", "هوم", "لوستر")),
    "food": ("50230100", ("قهوه", "شکلات", "شیرینی", "کیک", "عسل", "خشکبار", "آجیل", "سوپرمارکت", "مواد غذایی", "زعفران")),
    "toy": ("86010400", ("اسباب بازی", "بازی فکری", "عروسک", "سیسمونی", "نوزاد")),
    "book": ("60010200", ("کتاب", "تحریر", "نوشت افزار", "دفتر")),
    "pet": ("10000000", ("پت شاپ", "حیوان خانگی", "غذای سگ", "غذای گربه")),
    "eyewear": ("51102100", ("عینک", "optic")),
    "fashion": ("67010000", ("مانتو", "شومیز", "لباس", "پوشاک", "مزون", "بوتیک", "استایل", "شلوار", "پیراهن", "دامن", "روسری", "شال", "پارچه", "فشن", "کراپ", "کت زنانه", "کت مردانه", "تیشرت", "fashion", "wear", "پالتو")),
}
DESCRIPTIONS = {
    "beauty": "محصولات آرایشی، مراقبت پوست و مو و زیبایی",
    "shoe_bag": "کیف، کفش و اکسسوری استایل",
    "jewelry": "طلا، جواهرات، نقره و زیورآلات",
    "mobile": "موبایل، کالای دیجیتال و لوازم جانبی",
    "home": "لوازم خانه، آشپزخانه و دکوراسیون",
    "food": "مواد غذایی، نوشیدنی و محصولات خوراکی",
    "toy": "اسباب‌بازی و محصولات کودک",
    "book": "کتاب، نوشت‌افزار و محصولات فرهنگی",
    "pet": "خوراک و لوازم حیوانات خانگی",
    "eyewear": "عینک، فریم و محصولات اپتیکی",
    "fashion": "پوشاک و اکسسوری مد",
}


def follower_count(value):
    value = str(value or "0").replace(",", "").strip().upper()
    multiplier = 1
    if value.endswith("M"):
        multiplier, value = 1_000_000, value[:-1]
    elif value.endswith("K"):
        multiplier, value = 1_000, value[:-1]
    try:
        return int(float(value) * multiplier)
    except ValueError:
        return 0


def build_records(source):
    base = json.loads((PROJECT_ROOT / "data/merchant_catalog.json").read_text(encoding="utf-8"))["merchants"]
    server_text = (PROJECT_ROOT / "backend/server.py").read_text(encoding="utf-8")
    existing = {item["handle"][1:] for item in base}
    existing.update(handle.lower() for handle in re.findall(r'"@([a-zA-Z0-9._]+)"', server_text))
    primary_codes = {name: value[0] for name, value in RULES.items()}
    priority = {"fashion": 3, "beauty": 3, "shoe_bag": 2, "jewelry": 2}
    eligible = []
    for shop in source:
        handle = shop["shopId"].strip().lower()
        followers = follower_count(shop.get("followers"))
        quality = float((shop.get("aiEvaluation") or {}).get("score") or 0)
        reviews, average = int(shop.get("commentsCount") or 0), float(shop.get("avgScore") or 0)
        if (handle in existing or followers < 100_000 or int(shop.get("posts") or 0) < 50
                or quality < 4.1 or (reviews >= 2 and average < 2.5)
                or str(shop.get("bio") or "") in {"style", "custom"}):
            continue
        text = " ".join((shop.get("title") or "", shop.get("bio") or "", " ".join(shop.get("hashtags") or []))).lower().replace("_", " ")
        scores = {name: sum(text.count(keyword) for keyword in keywords) for name, (_, keywords) in RULES.items()}
        scores = {name: score for name, score in scores.items() if score}
        if not scores:
            continue
        category = max(scores, key=lambda name: (scores[name], priority.get(name, 1)))
        women = any(word in text for word in ("زنانه", "بانوان", "مانتو", "شومیز", "دامن", "روسری", "مزون"))
        preference = 3 if category == "beauty" else 2.5 if category == "fashion" and women else 2 if category == "fashion" else 1
        rank = quality * 10 + math.log1p(followers) + preference
        eligible.append((shop, category, scores, followers, quality, rank, women))
    preferred = sorted((item for item in eligible if item[1] in {"beauty", "fashion"}), key=lambda item: (item[5], item[3]), reverse=True)
    others = sorted((item for item in eligible if item[1] not in {"beauty", "fashion"}), key=lambda item: (item[5], item[3]), reverse=True)
    selected = (preferred + others)[:300]
    if len(selected) < 300:
        raise ValueError(f"only {len(selected)} eligible shops")
    records = []
    for shop, category, scores, followers, quality, _, women in selected:
        handle = shop["shopId"].strip().lower()
        tags = []
        for tag in shop.get("hashtags") or []:
            cleaned = " ".join(str(tag).replace("_", " ").split())
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
            if len(tags) == 6:
                break
        extra = []
        if category == "fashion" and women:
            extra.extend(("67010200", "67010800"))
        joined = " ".join(tags)
        if category == "beauty" and any(value in joined for value in ("پوست", "اسکین", "skincare")):
            extra.append("53131100")
        if category == "beauty" and any(value in joined for value in ("مو", "hair")):
            extra.append("53141100")
        if category == "shoe_bag":
            extra.append("64010200")
        if category == "mobile":
            extra.append("66010100")
        for other, score in sorted(scores.items(), key=lambda pair: pair[1], reverse=True):
            code = primary_codes[other]
            if other != category and score >= 2 and code not in extra:
                extra.append(code)
        source_url = f"https://basaliro.com/shop/{quote(handle)}/{quote(str(shop.get('title') or handle))}"
        records.append({
            "handle": f"@{handle}", "is_new": True, "name": str(shop.get("title") or handle),
            "description": DESCRIPTIONS[category] + (f"؛ {', '.join(tags)}" if tags else ""),
            "description_source": "curated_public_directory", "category_code": primary_codes[category],
            "category_codes": extra, "city": str(shop.get("city") or "ایران"),
            "followers_count": followers, "media_count": int(shop.get("posts") or 0),
            "source_url": source_url, "metrics_source": "basaliro_public_directory",
            "metrics_source_url": source_url, "quality_score": quality,
            "review_count": int(shop.get("commentsCount") or 0), "quality_source": "basaliro_ai_trust",
            "quality_source_url": source_url,
        })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--shard", type=int, choices=range(6), required=True)
    args = parser.parse_args()
    records = build_records(json.loads(args.source.read_text(encoding="utf-8")))
    start = args.shard * 50
    payload = {
        "version": 1, "snapshot_at": "2026-10-02T12:00:00+03:30",
        "notes": "High-audience active public-directory shops: >=100K followers, >=50 posts, automated trust score >=4.1/5, without materially low multi-review scores. Women clothing and beauty are prioritized. This is discovery evidence, not Kahoo verification.",
        "merchants": records[start:start + 50],
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
