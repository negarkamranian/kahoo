#!/usr/bin/env python3
import json
import mimetypes
import re
import os
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse

from backend.database import connect, run_category_seed, run_migrations
from backend.instagram import business_discovery_enabled, business_discovery_profile
from backend.search import lexical_merchant_scores, semantic_merchant_scores, sync_search_documents

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_ROOT = PROJECT_ROOT / "public"
DATA_ROOT = PROJECT_ROOT / "data"

MERCHANTS = [
    ("ig_nila","شیرینی بی‌بی","@bibi_confectionery","کیک تولد، شیرینی تر و خشک، شکلاتی، دسر و سفارش شیرینی","50182000","تهران","ب","#f2e2be","اطلاعات نمونه",1,"https://gzlocation.com/the-best-sweet-shop-in-tehran/",["photo-1578985545062-69928b1d9587","photo-1558961363-fa8fdf82db35","photo-1559620192-032c4bc4674e"]),
    ("ig_narin","پوشاک ایران","@iranclothings","تیشرت، پولوشرت، لباس کار، لباس فرم، پوشاک زنانه و مردانه، چاپ و گلدوزی","67010800","تهران","پ","#eee1d2","اطلاعات نمونه",1,"https://t.me/s/iranclothing",["photo-1551488831-00ddcb6c6bd3","photo-1529139574466-a303027c1d8b","photo-1483985988355-763728e1935b"]),
    ("ig_soft","ست‌سیتی","@set.city.store","لوازم آرایشی و بهداشتی، مراقبت پوست، رنگ مو، عطر و ادکلن","53131100","تهران","س","#f3dfe0","اطلاعات نمونه",1,"https://setcitystore.com/",["photo-1608248597279-f99d160bfcbc","photo-1598440947619-2c35fc9aa908","photo-1556229010-6c3f2c9ca5f8"]),
    ("ig_moss","دکوطرح","@decotarhco","طراحی داخلی، دکوراسیون منزل، بازسازی، کناف و چیدمان","75030100","تهران","د","#e2eadc","اطلاعات نمونه",1,"https://decotarhco.com/",["photo-1610701596007-11502861dcfa","photo-1618220179428-22790b461013","photo-1494438639946-1ebd1d20bf85"]),
    ("ig_sofal","فروغ هوم","@forough_homegallery","لوازم خانه و آشپزخانه، ظروف پذیرایی، لیوان، پارچ، بانکه و محصولات چوبی","73040400","گرگان","ف","#ead8ca","اطلاعات نمونه",1,"https://pelazaa.ir/business/forough-home/",["photo-1610701596007-11502861dcfa","photo-1578749556568-bc2c40e68b61","photo-1618220179428-22790b461013"]),
    ("ig_lune","صنایع دستی ایران‌زمین","@sanayedastiiranzamin","صنایع دستی ایرانی، آثار هنری، هدیه و محصولات دست‌ساز","70011400","ایران","ص","#f0ddd3","اطلاعات نمونه",1,"https://imginn.com/sanayedastiiranzamin/",["photo-1561214115-f2f134cc4912","photo-1578749556568-bc2c40e68b61","photo-1579783902614-a3fb3927b6a5"]),
    ("ig_bean","هایپرتوی","@hyper.toy","اسباب‌بازی، بازی فکری، پازل، لگو و عروسک","86010400","تهران","ه","#dbeaec","اطلاعات نمونه",1,"https://www.hypertoy.ir/contactus",["photo-1599443015574-be5fe8a05783","photo-1516627145497-ae6968895b74","photo-1560961911-ba7ef651a56c"]),
    ("ig_rose","نقره رُز","@noghre_rose","نقره، انگشتر، دستبند، گوشواره، گردنبند و زیورآلات","64010100","ایران","ن","#e5e5eb","تأیید کاربر",1,"https://www.instagram.com/noghre_rose/",["photo-1515562141207-7a88fb7ce338","photo-1617038260897-41a1f14a8ca0","photo-1535632066927-ab7c9ab60908"]),
    ("ig_hirad","پاندورا چالوس","@pandora_chalus","کفش اسپرت و چرمی، بوت، صندل، کیف، کمربند و کیف پول","63010300","چالوس","پ","#ead8c6","اطلاعات نمونه",1,"https://socialauditor.io/profile/pandora_chalus",["photo-1542291026-7eec264c27ff","photo-1549298916-b41d501d3772","photo-1608256246200-53e635b5b65f"]),
    ("ig_homino","ویداس","@vidasco.ir","لوازم خانگی، خردکن، ساندویچ‌ساز و لوازم برقی آشپزخانه","72020100","تهران","و","#dbe6e4","اطلاعات نمونه",1,"https://www.t.me/s/VIDASOFFICIAL",["photo-1585515320310-259814833e62","photo-1556911220-bff31c812dba","photo-1570222094114-d054a817e56b"]),
    ("ig_kaghaz","کوچه تحریر","@koocheh_tahrir","لوازم‌التحریر، نوشت‌افزار، دفتر، خودکار و وسایل طراحی","62060100","گرگان","ک","#f0dfbf","اطلاعات نمونه",1,"https://pelazaa.ir/business/koochehtahrir/",["photo-1455390582262-044cdead277a","photo-1517841905240-472988babdf9","photo-1531346878377-a5be20888e57"]),
    ("ig_sabz","سارینالند","@sarinaland_com","گل و گیاه آپارتمانی، گلدان، خاک و لوازم نگهداری گیاه","93037400","تهران","س","#d9ead6","اطلاعات نمونه",1,"https://socialveins.com/influencer/instagram/sarinaland_com",["photo-1485955900006-10f4d324d411","photo-1416879595882-3373a0480b5b","photo-1501004318641-b39e6451bec6"]),
    ("ig_digistyle","دیجی‌استایل","@digistylecom","پوشاک زنانه و مردانه، لباس راحتی و خواب، شلوار و جین، کیف، کفش و اکسسوری","67010000","تهران","د","#e5e0dc","منبع مستقل",1,"https://basaliro.com/shop/digistylecom",[]),
    ("ig_khanoumi","خانومی","@khanoumi_shop","لوازم آرایشی و بهداشتی، مراقبت پوست و مو، عطر، ضدآفتاب و لوازم برقی شخصی","53161000","تهران","خ","#f1dde4","منبع مستقل",1,"https://basaliro.com/shop/khanoumi_shop",[]),
    ("ig_roja","روژا","@rojashop","عطر و ادکلن، آرایش، مراقبت پوست و مو، شامپو، رنگ مو و محصولات بهداشتی","53161000","تهران","ر","#eadde5","منبع مستقل",1,"https://basaliro.com/shop/rojashop",[]),
    ("ig_mootanroo","مو تن رو","@mootanroo","محصولات آرایشی و بهداشتی، مراقبت پوست و مو، عطر و ابزار زیبایی","53161000","تهران","م","#eee1e2","منبع مستقل",1,"https://basaliro.com/shop/mootanroo",[]),
    ("ig_asenwear","آسن ویر","@asenwear","پوشاک زنانه روزمره، شومیز، تیشرت، تاپ، شلوار و ست‌های هماهنگ","67010000","اندیشه","آ","#e5e4df","منبع مستقل",1,"https://basaliro.com/shop/asenwear",[]),
    ("ig_ballentine","گالری بلنتین","@ballentine_gallery","پوشاک زنانه، مانتو، کت، شومیز، پیراهن، کفتان، شال و روسری","67010000","تهران","ب","#e7ded8","منبع مستقل",1,"https://basaliro.com/shop/ballentine_gallery",[]),
    ("ig_kifkafsh","کیف و کفش آنلاین","@kif_kafsh_onlinee","کیف و کفش زنانه، بوت، نیم‌بوت، صندل، کفش مجلسی و روزمره","63010300","ایران","ک","#e8dfd5","منبع مستقل",1,"https://basaliro.com/shop/kif_kafsh_onlinee",[]),
    ("ig_kajjshoe","کیف و کفش کاج","@kajjshoe","کفش، کیف و صندل زنانه برای استفاده روزمره و استایل مجلسی","63010300","بوشهر","ک","#e6ddd1","منبع مستقل",1,"https://basaliro.com/shop/kajjshoe",[]),
    ("ig_traffic","ترافیک","@kif.kafsh.traffic","کیف، کفش راحتی و رسمی، کوله‌پشتی مدرسه، سفر و دانشگاه","63010300","گنبدکاووس","ت","#deded8","منبع مستقل",1,"https://basaliro.com/shop/kif.kafsh.traffic",[]),
    ("ig_stiletto","تهران استیلتو","@tehran_stiletto","کفش زنانه، کفش مجلسی، پاشنه‌بلند و استیلتو","63010300","تهران","ت","#eadcd7","منبع مستقل",1,"https://basaliro.com/shop/tehran_stiletto",[]),
    ("ig_vartan","گالری ورتان","@vartan_gallery","زیورآلات دست‌ساز و هنری، قطعات تک‌نسخه با الهام از فرهنگ ایرانی","64010100","اصفهان","و","#e2e0dc","منبع مستقل",1,"https://basaliro.com/shop/vartan_gallery",[]),
    ("ig_nazmara","نظم آرا","@luxe_organizer","نظم‌دهنده، لوازم کاربردی خانه و آشپزخانه و محصولات سازمان‌دهی منزل","73040100","ایران","ن","#dfe7df","منبع مستقل",1,"https://basaliro.com/shop/luxe_organizer",[]),
    ("ig_khaneariaee","خانه آریایی","@khaneariaee","لوازم آشپزخانه، وسایل دکوری، گل مصنوعی، جهیزیه و محصولات خانه","75030100","ایران","خ","#e5e2d8","منبع مستقل",1,"https://basaliro.com/shop/khaneariaee",[]),
    ("ig_hihome","های هوم","@hihome_opal","لوازم خانه و آشپزخانه، محصولات لوکس، دکوراسیون و لوازم نظافت منزل","73040000","تهران","ه","#dfe5e1","منبع مستقل",1,"https://basaliro.com/shop/hihome_opal",[]),
    ("ig_niloofarabi","گالری نیلوفر آبی","@gallery.niloofarabi","لوازم آشپزخانه، وسایل دکوری، ظروف و هدایای خانه","75030100","امیرکلا","ن","#e0e6e5","منبع مستقل",1,"https://basaliro.com/shop/gallery.niloofarabi",[]),
    ("ig_haghgoo","گالری حق‌گو","@haghgoo_galleri","دکوریجات، ظروف چوبی، لوازم خانه و وسایل کاربردی آشپزخانه","73040400","مشهد","ح","#e7dfd3","منبع مستقل",1,"https://basaliro.com/shop/haghgoo_galleri",[]),
    ("ig_favstor","فیواستور","@favstor","لوازم تحریر فانتزی، خودکار، مداد، پاک‌کن، دفتر، کاغذ و ماژیک","62060100","ایران","ف","#e2e5eb","منبع مستقل",1,"https://basaliro.com/shop/favstor",[]),
    ("ig_tahrirshop","تحریر شاپ","@tahrir._shopp","لوازم تحریر فانتزی، پلنر، دفتر، روان‌نویس و ابزار برنامه‌ریزی","62060400","تهران","ت","#e8e1eb","منبع مستقل",1,"https://basaliro.com/shop/tahrir._shopp",[]),
    ("ig_fantasymarket","فانتزی مارکت","@fantasy_markett","لوازم تحریر رنگی و فانتزی، اکسسوری و محصولات خلاقانه کودک و بزرگسال","62060100","قزوین","ف","#ebe0e7","منبع مستقل",1,"https://basaliro.com/shop/fantasy_markett",[]),
    ("ig_homebazi","خانه بازی","@home.bazi","اسباب‌بازی چوبی، آشپزخانه کودک، پارکینگ طبقاتی و بازی‌های کودک","86010400","ایران","خ","#dfe8df","منبع مستقل",1,"https://basaliro.com/shop/home.bazi",[]),
    ("ig_kadopich","کادوپیچ","@kadopich.shops","ماگ، قمقمه، فلاسک، نوشیدنی‌افزار و لوازم کاربردی خانه و آشپزخانه","73050000","ایران","ک","#e4e0d8","منبع مستقل",1,"https://basaliro.com/shop/kadopich.shops",[]),
    ("ig_homekala","هوم‌کالا","@homekala_20","لوازم خانه و آشپزخانه، وسایل دکوراسیون و محصولات کاربردی منزل","73040000","ایران","ه","#e1e5de","منبع مستقل",1,"https://basaliro.com/shop/homekala_20",[])
]
MERCHANT_CATEGORY_SEED={
  "@iranclothings":("67010300",),
  "@set.city.store":("53131100","53141100","53161300"),
  "@forough_homegallery":("73040100","73050000","75030100"),
  "@hyper.toy":("86010100","86010200"),
  "@pandora_chalus":("64010200",),
  "@vidasco.ir":("72020200",),
  "@koocheh_tahrir":("62060400","62061100"),
  "@digistylecom":("67010200","67010300","67010800","67020100","67040100","63010300","64010200"),
  "@khanoumi_shop":("53131100","53141100","53161300","53181100"),
  "@rojashop":("53131100","53141100","53161300","53181100"),
  "@mootanroo":("53131100","53141100","53161300","53181100"),
  "@asenwear":("67010300","67010800"),
  "@ballentine_gallery":("67010200","67010800","64010100"),
  "@kif_kafsh_onlinee":("64010200",),
  "@kajjshoe":("64010200",),
  "@kif.kafsh.traffic":("64010200",),
  "@vartan_gallery":("70011400",),
  "@luxe_organizer":("75030100",),
  "@khaneariaee":("73040000",),
  "@hihome_opal":("72020400","75030100"),
  "@gallery.niloofarabi":("73040000","73050000"),
  "@haghgoo_galleri":("75030100",),
  "@favstor":("62060400","62061100"),
  "@tahrir._shopp":("62060100","62061100"),
  "@fantasy_markett":("62060400","62061100"),
  "@home.bazi":("86010700","86011100","86011200"),
  "@kadopich.shops":("73050300",),
  "@homekala_20":("75030100",),
}

# Public Instagram biography snapshots. The source URL for every value is kept
# alongside it so a product description is never presented as an Instagram bio.
PROFILE_BIO_SNAPSHOTS = {
    "@forough_homegallery": (
        "✨اگه کیفیت برات مهمه،با من همراه باش😊✨\nبا ضمانت سالم رسیدن کالا🛍️\nثبت سفارش: سایت\n۰۹۳۵۳۷۸۴۵۹۹📌\nبا اعتبار ترب پی قسطی خرید کن💸",
        "https://pelazaa.ir/business/forough-home/",
    ),
    "@sanayedastiiranzamin": (
        "محصولات دستساز و با کیفیت هنرمندان ایرانی❤️\nبیش از ۱۰ سال سابقه فروش\nفروش حضوری و آنلاین\nثبت سفارش واتساپ/دایرکت\n📞۰۲۱۸۸۳۷۲۶۱۴",
        "https://imginn.com/sanayedastiiranzamin/",
    ),
    "@sarinaland_com": (
        "ارسال گیاهان آپارتمانی ارزان از محلات به سراسر ایران 🪴 انتخاب از بین بیش از ۶۰ گیاه آپارتمانی مقاوم 📌 بسته‌بندی ویژه و تحویل درب منزل شما 📦🛒",
        "https://socialveins.com/influencer/instagram/sarinaland_com",
    ),
}

def fallback_image(label, color="#e8eee4"):
    safe_label = escape(label)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
<rect width="640" height="480" fill="{color}"/><path d="M0 355L195 210l90 70 92-105 263 180v125H0z" fill="#fff" opacity=".55"/>
<circle cx="505" cy="105" r="48" fill="#fff" opacity=".65"/><text x="320" y="430" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#435044">{safe_label}</text>
</svg>'''
    return svg.encode("utf-8"), "image/svg+xml"

def fallback_avatar(initial, color):
    safe_initial = escape(initial)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<rect width="256" height="256" rx="128" fill="{color}"/><circle cx="128" cy="128" r="104" fill="#fff" opacity=".28"/>
<path d="M75 184c12-35 32-53 53-53s41 18 53 53" fill="#fff" opacity=".48"/><circle cx="128" cy="91" r="35" fill="#fff" opacity=".48"/>
<text x="128" y="151" text-anchor="middle" font-family="Tahoma,sans-serif" font-size="72" font-weight="700" fill="#7f2e38">{safe_initial}</text>
</svg>'''
    return svg.encode("utf-8"), "image/svg+xml"

def download_image(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; KahooPrototype/1.0)"})
    with urlopen(request, timeout=20) as response:
        mime = response.headers.get_content_type()
        data = response.read(3_000_001)
        if not mime.startswith("image/") or not data or len(data) > 3_000_000:
            raise ValueError("invalid image response")
        return data, mime

def fetch_image(url, label):
    try:return download_image(url)
    except Exception:return fallback_image(label)

def public_embed_profile(handle):
    username=handle.lstrip("@").lower()
    request=Request(f"https://www.instagram.com/{username}/embed/",headers={"User-Agent":"Mozilla/5.0"})
    with urlopen(request,timeout=20) as response:
        payload=response.read(2_000_000).decode("utf-8","ignore")
    def decode_value(encoded):
        decoded=encoded
        for _ in range(2):
            try:decoded=json.loads('"'+decoded+'"')
            except (json.JSONDecodeError,TypeError):break
        return decoded
    def value(key):
        match=re.search(r'\\"'+re.escape(key)+r'\\":\\"(.*?)\\"',payload)
        return decode_value(match.group(1)) if match else None
    found=value("username");image_url=value("profile_pic_url")
    if found!=username or not image_url:raise ValueError(f"Instagram profile not found: {handle}")
    def count(key):
        match=re.search(r'\\"'+re.escape(key)+r'\\":\{\\"count\\":(\d+)',payload)
        return int(match.group(1)) if match else None
    verified_match=re.search(r'\\"is_verified\\":(true|false)',payload)
    posts=[];seen=set()
    pattern=re.compile(r'\\"shortcode\\":\\"(.*?)\\".*?\\"display_url\\":\\"(.*?)\\"',re.DOTALL)
    for shortcode_value,image_value in pattern.findall(payload):
        shortcode=decode_value(shortcode_value);post_image=decode_value(image_value)
        if shortcode in seen:continue
        seen.add(shortcode);posts.append({"image_url":post_image,"permalink":f"https://www.instagram.com/p/{shortcode}/"})
        if len(posts)==9:break
    return {"avatar_url":image_url,"posts":posts,"biography":value("biography"),
      "followers_count":count("edge_followed_by"),"following_count":count("edge_follow"),
      "media_count":count("edge_owner_to_timeline_media"),
      "instagram_verified":verified_match and verified_match.group(1)=="true"}

def instagram_profile(handle):
    if business_discovery_enabled():
        return business_discovery_profile(handle)
    profile=public_embed_profile(handle)
    profile["source"]="instagram_public_embed"
    return profile

def cache_post_image(db, post_id, image_url, label):
    image_blob, mime_type = fetch_image(image_url, label)
    db.execute("UPDATE merchant_posts SET image_blob=?, mime_type=? WHERE id=?", (image_blob, mime_type, post_id))

def cache_merchant_avatar(db, merchant_id, initial, color, image_url=None, source_url=None):
    try:
        avatar_blob,mime_type=download_image(image_url) if image_url else fallback_avatar(initial,color)
    except Exception:
        avatar_blob,mime_type=fallback_avatar(initial,color);source_url=None
    db.execute("UPDATE merchants SET avatar_blob=?,avatar_mime_type=?,avatar_source_url=? WHERE id=?",(avatar_blob,mime_type,source_url,merchant_id))

def replace_profile_posts(db,merchant_id,label,profile):
    downloaded=[]
    flat_position=0
    for post_position,post in enumerate(profile.get("posts",[])[:9],1):
        media_items=post.get("media") or [{"image_url":post.get("image_url"),"media_position":1}]
        collection_key=post.get("collection_key") or post.get("instagram_media_id") or instagram_shortcode(post.get("permalink")) or f"{merchant_id}-{post_position}"
        for media in media_items:
            image_url=media.get("image_url")
            if not image_url:continue
            image_blob,mime_type=download_image(image_url)
            flat_position+=1
            downloaded.append((post.get("instagram_media_id"),post.get("caption",''),image_url,image_blob,mime_type,post.get("permalink"),flat_position,collection_key,media.get("media_position",1),post.get("published_at")))
    if not downloaded:return False
    db.execute("DELETE FROM merchant_posts WHERE merchant_id=?",(merchant_id,))
    for row in downloaded:
        db.execute("""INSERT INTO merchant_posts(merchant_id,instagram_media_id,caption,image_url,image_blob,mime_type,permalink,position,collection_key,media_position,published_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(merchant_id,*row))
    return True

def migrate_database(db):
    return None

def initialize_database():
    run_migrations()
    run_category_seed(DATA_ROOT / "categories.sql")
    if os.environ.get("KAHOO_SEED_DEMO","1").lower() not in {"1","true","yes"}:
        return
    with connect() as db:
        for instagram_id,name,handle,description,category,city,initial,color,updated,verified,source,posts in MERCHANTS:
            url=f"https://www.instagram.com/{handle[1:]}/"
            existing=db.execute("SELECT id FROM merchants WHERE instagram_id=?",(instagram_id,)).fetchone()
            if existing:
                merchant_id=existing["id"]
                db.execute("UPDATE merchants SET name=?,handle=?,description=CASE WHEN description_source='llm' THEN description ELSE ? END,category_code=?,city=?,avatar_initial=?,avatar_color=?,instagram_url=?,updated_label=?,verified=?,verification_source=?,verified_at=date('now') WHERE id=?",(name,handle,description,category,city,initial,color,url,updated,verified,source,merchant_id))
            else:
                cursor=db.execute("INSERT INTO merchants(instagram_id,name,handle,description,category_code,city,avatar_initial,avatar_color,instagram_url,updated_label,verified,verification_source,verified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,date('now')) RETURNING id",(instagram_id,name,handle,description,category,city,initial,color,url,updated,verified,source))
                merchant_id=cursor.fetchone()["id"]
            db.execute("""UPDATE merchants SET source_url=?,description_source=COALESCE(description_source,'curated_seed'),
              description_source_url=COALESCE(description_source_url,?),description_updated_at=COALESCE(description_updated_at,datetime('now'))
              WHERE id=?""",(source,source,merchant_id))
            biography_snapshot=PROFILE_BIO_SNAPSHOTS.get(handle)
            if biography_snapshot:
                db.execute("""UPDATE merchants SET biography=?,biography_source=?,biography_updated_at=datetime('now')
                  WHERE id=? AND biography_source IS NULL""",(biography_snapshot[0],biography_snapshot[1],merchant_id))
            avatar=db.execute("SELECT avatar_blob,avatar_source_url FROM merchants WHERE id=?",(merchant_id,)).fetchone()
            post_state=db.execute("SELECT COUNT(*) count,COUNT(*) FILTER (WHERE image_url LIKE '%cdninstagram.com%') instagram_count FROM merchant_posts WHERE merchant_id=?",(merchant_id,)).fetchone()
            needs_avatar=not avatar["avatar_blob"] or avatar["avatar_source_url"]!=url
            needs_posts=post_state["count"]<6 or (post_state["instagram_count"] or 0)<post_state["count"]
            profile=None
            if os.environ.get("KAHOO_SYNC_ON_START","0").lower() in {"1","true","yes"} and (needs_avatar or needs_posts):
                try:profile=instagram_profile(handle)
                except Exception:profile=None
            if needs_avatar:
                cache_merchant_avatar(db,merchant_id,initial,color,profile["avatar_url"] if profile else None,url if profile else None)
            if needs_posts and profile and len(profile["posts"])>=4:
                try:replace_profile_posts(db,merchant_id,name,profile)
                except Exception:pass
            if db.execute("SELECT COUNT(*) FROM merchant_posts WHERE merchant_id=?",(merchant_id,)).fetchone()[0]==0:
                for position,photo in enumerate(posts,1):
                    image_url=f"https://images.unsplash.com/{photo}?auto=format&fit=crop&w=500&q=80"
                    db.execute("INSERT INTO merchant_posts(merchant_id,image_url,permalink,position) VALUES(?,?,?,?)",(merchant_id,image_url,url,position))
        seed_search_metadata(db)
        sync_search_documents(db)
        uncached=list(db.execute("SELECT p.id,p.image_url,m.name FROM merchant_posts p JOIN merchants m ON m.id=p.merchant_id WHERE p.image_blob IS NULL OR p.mime_type IS NULL"))
        for post in uncached:
            cache_post_image(db,post["id"],post["image_url"],post["name"])

def refresh_instagram_profiles(handles=None):
    requested={handle if handle.startswith("@") else f"@{handle}" for handle in (handles or [])}
    results=[]
    with connect() as db:
        rows=list(db.execute("SELECT id,handle,name,avatar_initial,avatar_color FROM merchants ORDER BY id"))
        for merchant in rows:
            if requested and merchant["handle"] not in requested:continue
            try:
                profile=instagram_profile(merchant["handle"])
                biography=(profile.get("biography") or "").strip()
                source=profile.get("source","instagram_public_embed")
                db.execute("""UPDATE merchants SET biography=?,biography_source=?,
                  biography_updated_at=datetime('now'),followers_count=COALESCE(?,followers_count),
                  following_count=COALESCE(?,following_count),media_count=COALESCE(?,media_count),
                  metrics_source=?,metrics_updated_at=datetime('now') WHERE id=?""",
                  (biography,source,profile.get("followers_count"),profile.get("following_count"),profile.get("media_count"),source,merchant["id"]))
                if profile.get("avatar_url"):
                    cache_merchant_avatar(db,merchant["id"],merchant["avatar_initial"],merchant["avatar_color"],profile["avatar_url"],source)
                if profile.get("posts"):
                    replace_profile_posts(db,merchant["id"],merchant["name"],profile)
                results.append({"handle":merchant["handle"],"updated":True,"has_biography":bool(biography)})
            except Exception as error:
                results.append({"handle":merchant["handle"],"updated":False,"error":str(error)})
        seed_search_metadata(db)
        sync_search_documents(db)
    return results

def category_tree():
    with connect() as db:
        rows=[dict(row) for row in db.execute("SELECT code,parent_code,level,label_fa,label_en,icon FROM categories ORDER BY level,sort_order,label_fa")]
        counts={row["code"]:0 for row in rows}
        parents={row["code"]:row["parent_code"] for row in rows}
        assignments={}
        for item in db.execute("SELECT merchant_id,category_code FROM merchant_categories"):
            assignments.setdefault(item["merchant_id"],[]).append(item["category_code"])
        for category_codes in assignments.values():
            visible=set()
            for category_code in category_codes:
                code=category_code
                while code:
                    visible.add(code);code=parents.get(code)
            for code in visible:
                counts[code]=counts.get(code,0)+1
        nodes={row["code"]:{**row,"count":counts[row["code"]],"children":[]} for row in rows}
        roots=[]
        for row in rows:
            node=nodes[row["code"]]
            (nodes[row["parent_code"]]["children"] if row["parent_code"] else roots).append(node)
        return roots

PERSIAN_TRANSLATION=str.maketrans({"ي":"ی","ى":"ی","ك":"ک","ة":"ه","ۀ":"ه","ؤ":"و","إ":"ا","أ":"ا"})
SEARCH_STOPWORDS={"از","به","با","در","برای","و","یا","یک","های","این","آن"}

def normalize_search(value):
    value=(value or "").lower().translate(PERSIAN_TRANSLATION).replace("\u200c"," ")
    return " ".join(re.sub(r"[^\w@.]+"," ",value).split())

SEARCH_ALIAS_SEED=(
  ("شلوار","لباس",0.55,"curated_taxonomy"),
  ("شلوار","پوشاک",0.55,"curated_taxonomy"),
  ("شلوار","پایین تنه",0.9,"curated_taxonomy"),
  ("جین","شلوار",0.9,"curated_taxonomy"),
  ("لگ","شلوار",0.8,"curated_taxonomy"),
  ("شلوارک","شلوار",0.85,"curated_taxonomy"),
  ("تی شرت","تیشرت",0.95,"curated_taxonomy"),
  ("تیشرت","لباس",0.6,"curated_taxonomy"),
)

def searchable_tokens(text):
    return {token for token in normalize_search(text).split() if len(token)>1 and token not in SEARCH_STOPWORDS}

def seed_search_metadata(db):
    for alias,term,weight,source in SEARCH_ALIAS_SEED:
        db.execute(
          """INSERT INTO search_aliases(alias,normalized_alias,term,normalized_term,weight,source)
            VALUES(?,?,?,?,?,?) ON CONFLICT(normalized_alias,normalized_term)
            DO UPDATE SET alias=excluded.alias,term=excluded.term,weight=excluded.weight,source=excluded.source""",
          (alias,normalize_search(alias),term,normalize_search(term),weight,source))
    for merchant in db.execute("SELECT id,handle,category_code,description,description_source_url,biography,biography_source,instagram_url FROM merchants"):
        db.execute(
          """INSERT INTO merchant_categories(merchant_id,category_code,confidence,source,source_url)
            VALUES(?,?,1,'merchant_primary',?) ON CONFLICT(merchant_id,category_code)
            DO UPDATE SET confidence=1,source='merchant_primary',source_url=excluded.source_url""",
          (merchant["id"],merchant["category_code"],merchant["description_source_url"]))
        db.execute("DELETE FROM merchant_categories WHERE merchant_id=? AND source='curated_catalog'",(merchant["id"],))
        for category_code in MERCHANT_CATEGORY_SEED.get(merchant["handle"],()):
            db.execute(
              """INSERT INTO merchant_categories(merchant_id,category_code,confidence,source,source_url)
                VALUES(?,?,0.9,'curated_catalog',?) ON CONFLICT(merchant_id,category_code)
                DO UPDATE SET confidence=excluded.confidence,source=excluded.source,source_url=excluded.source_url""",
              (merchant["id"],category_code,merchant["description_source_url"]))
        db.execute("DELETE FROM merchant_search_terms WHERE merchant_id=? AND source IN ('description','biography')",(merchant["id"],))
        sources=(("description",merchant["description"],1.0,merchant["description_source_url"]),("biography",merchant["biography"],0.8,merchant["instagram_url"]))
        for source,text,weight,source_url in sources:
            for term in searchable_tokens(text):
                db.execute(
                  """INSERT INTO merchant_search_terms(merchant_id,term,normalized_term,weight,source,source_url,confidence)
                    VALUES(?,?,?,?,?,?,1) ON CONFLICT(merchant_id,normalized_term,source)
                    DO UPDATE SET term=excluded.term,weight=excluded.weight,source_url=excluded.source_url,updated_at=CURRENT_TIMESTAMP""",
                  (merchant["id"],term,term,weight,source,source_url))

def save_llm_enrichment(merchant_id,description,terms,model,source_url,confidence=0.75):
    if not model or not source_url:
        raise ValueError("LLM enrichment requires both model and source_url provenance")
    normalized_terms={normalize_search(term):term.strip() for term in terms if normalize_search(term)}
    with connect() as db:
        db.execute("""UPDATE merchants SET description=?,description_source='llm',description_source_url=?,
          description_generated_by=?,description_updated_at=datetime('now') WHERE id=?""",
          (description.strip(),source_url,model,merchant_id))
        db.execute("DELETE FROM merchant_search_terms WHERE merchant_id=? AND source='llm'",(merchant_id,))
        for normalized,term in normalized_terms.items():
            db.execute("""INSERT INTO merchant_search_terms
              (merchant_id,term,normalized_term,weight,source,source_url,generated_by,confidence)
              VALUES(?,?,?,1,'llm',?,?,?)""",
              (merchant_id,term,normalized,source_url,model,max(0,min(1,confidence))))
        seed_search_metadata(db)
        sync_search_documents(db)
def instagram_shortcode(permalink):
    match=re.search(r"/(?:p|reel)/([^/?#]+)",permalink or "")
    return match.group(1) if match else ""

def shared_prefix(left,right):
    length=0
    for left_char,right_char in zip(left,right):
        if left_char!=right_char:break
        length+=1
    return left[:length]

def merchant_posts(db,merchant_id):
    rows=list(db.execute(
      "SELECT id,image_url,permalink,position,collection_key,media_position FROM merchant_posts "
      "WHERE merchant_id=? AND image_blob IS NOT NULL ORDER BY position,media_position",(merchant_id,)))
    posts=[];index=0
    while index<len(rows):
        first=rows[index];end=index+1;collection_key=first["collection_key"]
        if collection_key:
            while end<len(rows) and rows[end]["collection_key"]==collection_key:end+=1
        elif end<len(rows) and first["image_url"]==rows[end]["image_url"]:
            prefix=shared_prefix(instagram_shortcode(first["permalink"]),instagram_shortcode(rows[end]["permalink"]))
            if len(prefix)>=3:
                end+=1
                while end<len(rows) and instagram_shortcode(rows[end]["permalink"]).startswith(prefix):end+=1
        collection=[];seen_images=set()
        for media in rows[index:end]:
            if media["image_url"] in seen_images:continue
            seen_images.add(media["image_url"]);collection.append({"media_url":f"/api/media/{media['id']}","position":len(collection)+1})
        shortcode=instagram_shortcode(first["permalink"])
        posts.append({"key":collection_key or shortcode or f"{merchant_id}-{first['position']}","permalink":first["permalink"],"position":len(posts)+1,"media_url":collection[0]["media_url"],"media":collection,"image_count":len(collection)})
        index=end
    return posts
def merchants(category=None, query=""):
    params=[]
    where=[]
    if category:
        where.append("""EXISTS (SELECT 1 FROM merchant_categories mc WHERE mc.merchant_id=m.id
          AND mc.category_code IN (WITH RECURSIVE branch(code) AS (SELECT ? UNION ALL
          SELECT c.code FROM categories c JOIN branch b ON c.parent_code=b.code) SELECT code FROM branch))""")
        params.append(category)
    sql="SELECT m.* FROM merchants m"+(" WHERE "+" AND ".join(where) if where else "")+" ORDER BY m.id DESC"
    with connect() as db:
        category_rows={row["code"]:dict(row) for row in db.execute("SELECT code,parent_code,label_fa,label_en FROM categories")}
        categories_by_merchant={}
        for item in db.execute("SELECT merchant_id,category_code FROM merchant_categories"):
            categories_by_merchant.setdefault(item["merchant_id"],[]).append(item["category_code"])
        terms_by_merchant={}
        for item in db.execute("SELECT merchant_id,normalized_term,weight,confidence FROM merchant_search_terms"):
            terms_by_merchant.setdefault(item["merchant_id"],[]).append((item["normalized_term"],item["weight"]*item["confidence"]))
        phrase=normalize_search(query)
        tokens=[token for token in phrase.split() if len(token)>1 and token not in SEARCH_STOPWORDS]
        expanded={token:1.0 for token in tokens}
        alias_keys=set(tokens)
        if phrase:alias_keys.add(phrase)
        if alias_keys:
            placeholders=",".join("?" for _ in alias_keys)
            for item in db.execute(f"SELECT normalized_term,weight FROM search_aliases WHERE normalized_alias IN ({placeholders})",tuple(alias_keys)):
                expanded[item["normalized_term"]]=max(expanded.get(item["normalized_term"],0),item["weight"])
        lexical_document_scores=lexical_merchant_scores(db,phrase) if phrase else {}
        try:semantic_scores=semantic_merchant_scores(db,phrase) if phrase else {}
        except Exception:semantic_scores={}
        result=[]
        for row in db.execute(sql,params):
            merchant=dict(row);score=0;exact_score=0
            if query:
                category_labels=[]
                for category_code in categories_by_merchant.get(row["id"],[row["category_code"]]):
                    code=category_code
                    while code and code in category_rows:
                        category_labels.extend((category_rows[code]["label_fa"],category_rows[code]["label_en"]));code=category_rows[code]["parent_code"]
                identity=normalize_search(f'{row["name"]} {row["handle"]} {row["city"]}')
                description=normalize_search(row["description"])
                biography=normalize_search(row["biography"])
                category_text=normalize_search(" ".join(category_labels))
                stored_terms=terms_by_merchant.get(row["id"],[])
                def term_score(term):
                    metadata=max((weight*5 for stored,weight in stored_terms if term in stored or stored in term),default=0)
                    return (7 if term in identity else 0)+(5 if term in description else 0)+(4 if term in biography else 0)+(3 if term in category_text else 0)+metadata
                token_scores=[term_score(token) for token in tokens]
                exact_score=sum(token_scores)
                related_score=sum(term_score(term)*weight for term,weight in expanded.items() if term not in tokens)
                semantic_score=semantic_scores.get(row["id"],0)
                document_score=lexical_document_scores.get(row["id"],0)
                score=exact_score+related_score+(14 if phrase and phrase in identity else 0)+(12 if phrase and phrase in description else 0)+(9 if phrase and phrase in biography else 0)+(semantic_score*12)+(document_score*10)
                required_matches=max(2,(len(tokens)+1)//2)
                weak_lexical=len(tokens)>1 and sum(value>0 for value in token_scores)<required_matches
                if not tokens or score==0 or (weak_lexical and semantic_score<0.55 and document_score<0.2):continue
                merchant["match_quality"]="exact" if exact_score else ("semantic" if semantic_score>=0.55 else ("document" if document_score>=0.2 else "related"))
            merchant.pop("avatar_blob",None);merchant.pop("avatar_mime_type",None);merchant["avatar_url"]=f"/api/avatars/{row['id']}"
            merchant["posts"]=merchant_posts(db,row["id"])
            merchant["search_score"]=round(score,2)
            result.append(merchant)
        return sorted(result,key=lambda merchant:(merchant["search_score"],merchant["id"]),reverse=True)

def merchant_detail(merchant_id):
    with connect() as db:
        row=db.execute("SELECT m.*,c.label_fa category_label FROM merchants m JOIN categories c ON c.code=m.category_code WHERE m.id=?",(merchant_id,)).fetchone()
        if not row:return None
        merchant=dict(row);merchant.pop("avatar_blob",None);merchant.pop("avatar_mime_type",None)
        merchant["avatar_url"]=f"/api/avatars/{merchant_id}"
        merchant["posts"]=merchant_posts(db,merchant_id)
        category_rows={item["code"]:dict(item) for item in db.execute("SELECT code,parent_code,label_fa FROM categories")}
        breadcrumb=[];code=row["category_code"]
        while code and code in category_rows:
            breadcrumb.insert(0,{"code":code,"label":category_rows[code]["label_fa"]});code=category_rows[code]["parent_code"]
        merchant["category_path"]=breadcrumb
        merchant["categories"]=[dict(item) for item in db.execute(
          """SELECT c.code,c.label_fa label,mc.confidence,mc.source,mc.source_url
            FROM merchant_categories mc JOIN categories c ON c.code=mc.category_code
            WHERE mc.merchant_id=? ORDER BY mc.confidence DESC,c.level,c.sort_order""",(merchant_id,))]
        return merchant

def import_demo_merchant():
    # A real OAuth callback would upsert the authenticated account. The demo must
    # never create a made-up public identity in the directory.
    return {"created":False,"mode":"oauth_demo"}

ANALYTICS_EVENTS={"search","category_view","merchant_click","login_started","login_completed","oauth_started","oauth_completed"}

def record_event(event_type,session_id,query=None,category_code=None,merchant_id=None,result_count=None):
    if event_type not in ANALYTICS_EVENTS:return False
    session_id=re.sub(r"[^a-zA-Z0-9_-]","",str(session_id or ""))[:80]
    if len(session_id)<8:return False
    query=(query or "").strip()[:160] or None
    try:
        merchant_id=int(merchant_id) if merchant_id is not None else None
        result_count=int(result_count) if result_count is not None else None
    except (TypeError,ValueError):return False
    with connect() as db:
        db.execute("INSERT INTO analytics_events(event_type,session_id,query,category_code,merchant_id,result_count) VALUES(?,?,?,?,?,?)",(event_type,session_id,query,category_code or None,merchant_id,result_count))
    return True

def admin_metrics(days=30):
    days=days if days in (7,30,90) else 30
    since=(datetime.now()-timedelta(days=days-1)).strftime("%Y-%m-%d 00:00:00")
    date_keys=[(datetime.now()-timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days-1,-1,-1)]
    with connect() as db:
        count=lambda condition:db.execute(f"SELECT COUNT(*) FROM analytics_events WHERE created_at>=? AND {condition}",(since,)).fetchone()[0]
        searches=count("event_type='search'")
        clicks=count("event_type='merchant_click'")
        zero_searches=count("event_type='search' AND result_count=0")
        visitors=db.execute("SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=?",(since,)).fetchone()[0]
        searched_sessions=db.execute("SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=? AND event_type='search'",(since,)).fetchone()[0]
        clicked_sessions=db.execute("SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=? AND event_type='merchant_click'",(since,)).fetchone()[0]
        daily_rows={row["day"]:dict(row) for row in db.execute("""
          SELECT to_char(created_at,'YYYY-MM-DD') day,
            COUNT(*) FILTER (WHERE event_type='search') searches,
            COUNT(*) FILTER (WHERE event_type='merchant_click') clicks,
            COUNT(DISTINCT session_id) visitors,
            COUNT(*) FILTER (WHERE event_type='search' AND result_count=0) zero_results
          FROM analytics_events WHERE created_at>=? GROUP BY day ORDER BY day
        """,(since,))}
        daily=[{"date":day,"searches":0,"clicks":0,"visitors":0,"zero_results":0}|daily_rows.get(day,{}) for day in date_keys]
        top_queries=[dict(row) for row in db.execute("""
          SELECT query,COUNT(*) searches,ROUND(AVG(result_count),1)::double precision avg_results,
            COUNT(*) FILTER (WHERE result_count=0) zero_results
          FROM analytics_events WHERE created_at>=? AND event_type='search' AND query IS NOT NULL
          GROUP BY query ORDER BY searches DESC LIMIT 10
        """,(since,))]
        missed_queries=[dict(row) for row in db.execute("""
          SELECT query,COUNT(*) searches FROM analytics_events
          WHERE created_at>=? AND event_type='search' AND result_count=0 AND query IS NOT NULL
          GROUP BY query ORDER BY searches DESC LIMIT 8
        """,(since,))]
        top_merchants=[dict(row) for row in db.execute("""
          SELECT m.id,m.name,m.handle,COUNT(e.id) clicks FROM analytics_events e
          JOIN merchants m ON m.id=e.merchant_id
          WHERE e.created_at>=? AND e.event_type='merchant_click'
          GROUP BY m.id ORDER BY clicks DESC,m.id DESC LIMIT 8
        """,(since,))]
        top_categories=[dict(row) for row in db.execute("""
          SELECT c.label_fa label,COUNT(e.id) views FROM analytics_events e
          JOIN categories c ON c.code=e.category_code
          WHERE e.created_at>=? AND e.event_type='category_view'
          GROUP BY c.code ORDER BY views DESC LIMIT 8
        """,(since,))]
        catalog=dict(db.execute("""
          SELECT (SELECT COUNT(*) FROM merchants) merchants,
            (SELECT COUNT(DISTINCT category_code) FROM merchants) used_categories,
            (SELECT COUNT(*) FROM merchant_posts) posts,
            (SELECT COUNT(*) FROM merchants WHERE avatar_blob IS NOT NULL) avatars,
            (SELECT COUNT(*) FROM merchants WHERE description!='') descriptions
        """).fetchone())
        oauth_started=count("event_type='oauth_started'")
        oauth_completed=count("event_type='oauth_completed'")
    return {
      "period_days":days,"generated_at":datetime.now().isoformat(timespec="seconds"),
      "kpis":{"searches":searches,"visitors":visitors,"clicks":clicks,
        "zero_rate":round(zero_searches/searches*100,1) if searches else 0,
        "search_to_click":round(clicked_sessions/searched_sessions*100,1) if searched_sessions else 0},
      "catalog":catalog,"daily":daily,"top_queries":top_queries,"missed_queries":missed_queries,
      "top_merchants":top_merchants,"top_categories":top_categories,
      "funnel":{"visitors":visitors,"searched":searched_sessions,"clicked":clicked_sessions,
        "oauth_started":oauth_started,"oauth_completed":oauth_completed}
    }

class Handler(BaseHTTPRequestHandler):
    def send_json(self,payload,status=200):
        body=json.dumps(payload,ensure_ascii=False,default=lambda value:value.isoformat() if isinstance(value,(date,datetime)) else float(value) if isinstance(value,Decimal) else str(value)).encode();self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=="/api/categories": return self.send_json(category_tree())
        if parsed.path=="/api/merchants":
            args=parse_qs(parsed.query);category=args.get("category",[None])[0];query=args.get("q",[""])[0];result=merchants(category,query)
            session_id=self.headers.get("X-Kahoo-Session")
            if query:record_event("search",session_id,query=query,category_code=category,result_count=len(result))
            elif category:record_event("category_view",session_id,category_code=category,result_count=len(result))
            return self.send_json(result)
        if parsed.path.startswith("/api/merchants/"):
            try:merchant_id=int(parsed.path.rsplit("/",1)[1])
            except ValueError:return self.send_error(404)
            result=merchant_detail(merchant_id)
            return self.send_json(result) if result else self.send_error(404)
        if parsed.path=="/api/admin/metrics":
            args=parse_qs(parsed.query)
            try:days=int(args.get("days",[30])[0])
            except ValueError:days=30
            return self.send_json(admin_metrics(days))
        if parsed.path.startswith("/api/media/"):
            try: post_id=int(parsed.path.rsplit("/",1)[1])
            except ValueError: return self.send_error(404)
            with connect() as db:
                media=db.execute("SELECT image_blob,mime_type FROM merchant_posts WHERE id=?",(post_id,)).fetchone()
            if not media or media["image_blob"] is None:return self.send_error(404)
            data=media["image_blob"];self.send_response(200);self.send_header("Content-Type",media["mime_type"] or "application/octet-stream");self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","public, max-age=86400");self.end_headers();self.wfile.write(data);return
        if parsed.path.startswith("/api/avatars/"):
            try: merchant_id=int(parsed.path.rsplit("/",1)[1])
            except ValueError: return self.send_error(404)
            with connect() as db:
                avatar=db.execute("SELECT avatar_blob,avatar_mime_type FROM merchants WHERE id=?",(merchant_id,)).fetchone()
            if not avatar or avatar["avatar_blob"] is None:return self.send_error(404)
            data=avatar["avatar_blob"];self.send_response(200);self.send_header("Content-Type",avatar["avatar_mime_type"] or "application/octet-stream");self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","public, max-age=86400");self.end_headers();self.wfile.write(data);return
        path=PUBLIC_ROOT/("index.html" if parsed.path=="/" else parsed.path.lstrip("/"))
        if not path.is_file() or PUBLIC_ROOT not in path.resolve().parents: return self.send_error(404)
        data=path.read_bytes();self.send_response(200);self.send_header("Content-Type",mimetypes.guess_type(path)[0] or "application/octet-stream");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        length=int(self.headers.get("Content-Length","0"))
        try:payload=json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:return self.send_json({"error":"invalid_json"},400)
        if self.path=="/api/analytics/event":
            session_id=self.headers.get("X-Kahoo-Session") or payload.get("session_id")
            saved=record_event(payload.get("event_type"),session_id,payload.get("query"),payload.get("category_code"),payload.get("merchant_id"),payload.get("result_count"))
            return self.send_json({"saved":saved},201 if saved else 400)
        if self.path=="/api/login/request": return self.send_json({"challenge_id":str(uuid.uuid4()),"phone":payload.get("phone")})
        if self.path=="/api/login/verify":
            if len(str(payload.get("code","")))!=5:return self.send_json({"error":"invalid_code"},400)
            return self.send_json({"user":{"phone":payload.get("phone"),"display_name":"حساب من"}})
        if self.path=="/api/merchants/import-demo": return self.send_json(import_demo_merchant(),201)
        return self.send_error(404)

if __name__=="__main__":
    initialize_database();print("Kahoo running at http://127.0.0.1:4173");ThreadingHTTPServer(("127.0.0.1",4173),Handler).serve_forever()
