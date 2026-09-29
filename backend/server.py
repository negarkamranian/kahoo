#!/usr/bin/env python3
import json
import mimetypes
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_ROOT = PROJECT_ROOT / "public"
DATA_ROOT = PROJECT_ROOT / "data"
DB_PATH = DATA_ROOT / "kahoo.db"

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
    ("ig_sabz","سارینالند","@sarinaland_com","گل و گیاه آپارتمانی، گلدان، خاک و لوازم نگهداری گیاه","93037400","تهران","س","#d9ead6","اطلاعات نمونه",1,"https://socialveins.com/influencer/instagram/sarinaland_com",["photo-1485955900006-10f4d324d411","photo-1416879595882-3373a0480b5b","photo-1501004318641-b39e6451bec6"])
]

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

def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

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

def instagram_profile(handle):
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

def cache_post_image(db, post_id, image_url, label):
    image_blob, mime_type = fetch_image(image_url, label)
    db.execute("UPDATE merchant_posts SET image_blob=?, mime_type=? WHERE id=?", (image_blob, mime_type, post_id))

def cache_merchant_avatar(db, merchant_id, initial, color, image_url=None, source_url=None):
    try:
        avatar_blob,mime_type=download_image(image_url) if image_url else fallback_avatar(initial,color)
    except Exception:
        avatar_blob,mime_type=fallback_avatar(initial,color);source_url=None
    db.execute("UPDATE merchants SET avatar_blob=?,avatar_mime_type=?,avatar_source_url=? WHERE id=?",(avatar_blob,mime_type,source_url,merchant_id))

def migrate_database(db):
    merchant_columns = {row[1] for row in db.execute("PRAGMA table_info(merchants)")}
    post_columns = {row[1] for row in db.execute("PRAGMA table_info(merchant_posts)")}
    if "verification_source" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN verification_source TEXT")
    if "verified_at" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN verified_at TEXT")
    if "description" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    if "avatar_blob" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN avatar_blob BLOB")
    if "avatar_mime_type" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN avatar_mime_type TEXT")
    if "avatar_source_url" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN avatar_source_url TEXT")
    if "biography" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN biography TEXT NOT NULL DEFAULT ''")
    if "biography_source" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN biography_source TEXT")
    if "biography_updated_at" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN biography_updated_at TEXT")
    if "followers_count" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN followers_count INTEGER")
    if "following_count" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN following_count INTEGER")
    if "media_count" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN media_count INTEGER")
    if "former_username_count" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN former_username_count INTEGER")
    if "account_created_at" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN account_created_at TEXT")
    if "metrics_source" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN metrics_source TEXT")
    if "metrics_updated_at" not in merchant_columns:
        db.execute("ALTER TABLE merchants ADD COLUMN metrics_updated_at TEXT")
    if "image_blob" not in post_columns:
        db.execute("ALTER TABLE merchant_posts ADD COLUMN image_blob BLOB")
    if "mime_type" not in post_columns:
        db.execute("ALTER TABLE merchant_posts ADD COLUMN mime_type TEXT")
    post_schema=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='merchant_posts'").fetchone()[0]
    if "BETWEEN 1 AND 3" in post_schema:
        db.executescript("""
        CREATE TABLE merchant_posts_v2 (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
          image_url TEXT NOT NULL,
          image_blob BLOB,
          mime_type TEXT,
          permalink TEXT NOT NULL,
          position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 9),
          UNIQUE(merchant_id, position)
        );
        INSERT INTO merchant_posts_v2(id,merchant_id,image_url,image_blob,mime_type,permalink,position)
          SELECT id,merchant_id,image_url,image_blob,mime_type,permalink,position FROM merchant_posts;
        DROP TABLE merchant_posts;
        ALTER TABLE merchant_posts_v2 RENAME TO merchant_posts;
        CREATE INDEX idx_posts_merchant ON merchant_posts(merchant_id);
        """)
    db.execute("UPDATE merchants SET biography='' WHERE biography_source IS NULL AND biography=description")

def initialize_database():
    with connect() as db:
        db.executescript((DATA_ROOT / "schema.sql").read_text())
        migrate_database(db)
        category_seed=DATA_ROOT / "categories.sql"
        if category_seed.exists():db.executescript(category_seed.read_text())
        for instagram_id,name,handle,description,category,city,initial,color,updated,verified,source,posts in MERCHANTS:
            url=f"https://www.instagram.com/{handle[1:]}/"
            existing=db.execute("SELECT id FROM merchants WHERE instagram_id=?",(instagram_id,)).fetchone()
            if existing:
                merchant_id=existing["id"]
                db.execute("UPDATE merchants SET name=?,handle=?,description=?,category_code=?,city=?,avatar_initial=?,avatar_color=?,instagram_url=?,updated_label=?,verified=?,verification_source=?,verified_at=date('now') WHERE id=?",(name,handle,description,category,city,initial,color,url,updated,verified,source,merchant_id))
            else:
                cursor=db.execute("INSERT INTO merchants(instagram_id,name,handle,description,category_code,city,avatar_initial,avatar_color,instagram_url,updated_label,verified,verification_source,verified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,date('now'))",(instagram_id,name,handle,description,category,city,initial,color,url,updated,verified,source))
                merchant_id=cursor.lastrowid
            biography_snapshot=PROFILE_BIO_SNAPSHOTS.get(handle)
            if biography_snapshot:
                db.execute("""UPDATE merchants SET biography=?,biography_source=?,biography_updated_at=datetime('now')
                  WHERE id=? AND biography_source IS NULL""",(biography_snapshot[0],biography_snapshot[1],merchant_id))
            avatar=db.execute("SELECT avatar_blob,avatar_source_url FROM merchants WHERE id=?",(merchant_id,)).fetchone()
            post_state=db.execute("SELECT COUNT(*) count,SUM(image_url LIKE '%cdninstagram.com%') instagram_count FROM merchant_posts WHERE merchant_id=?",(merchant_id,)).fetchone()
            needs_avatar=not avatar["avatar_blob"] or avatar["avatar_source_url"]!=url
            needs_posts=post_state["count"]<6 or (post_state["instagram_count"] or 0)<post_state["count"]
            profile=None
            if needs_avatar or needs_posts:
                try:profile=instagram_profile(handle)
                except Exception:profile=None
            if needs_avatar:
                cache_merchant_avatar(db,merchant_id,initial,color,profile["avatar_url"] if profile else None,url if profile else None)
            if needs_posts and profile and len(profile["posts"])>=4:
                downloaded=[]
                for post in profile["posts"][:9]:
                    try:image_blob,mime_type=download_image(post["image_url"])
                    except Exception:break
                    downloaded.append((post["image_url"],image_blob,mime_type,post["permalink"]))
                if len(downloaded)==len(profile["posts"][:9]):
                    db.execute("DELETE FROM merchant_posts WHERE merchant_id=?",(merchant_id,))
                    for position,(image_url,image_blob,mime_type,permalink) in enumerate(downloaded,1):
                        db.execute("INSERT INTO merchant_posts(merchant_id,image_url,image_blob,mime_type,permalink,position) VALUES(?,?,?,?,?,?)",(merchant_id,image_url,image_blob,mime_type,permalink,position))
            if db.execute("SELECT COUNT(*) FROM merchant_posts WHERE merchant_id=?",(merchant_id,)).fetchone()[0]==0:
                for position,photo in enumerate(posts,1):
                    image_url=f"https://images.unsplash.com/{photo}?auto=format&fit=crop&w=500&q=80"
                    db.execute("INSERT INTO merchant_posts(merchant_id,image_url,permalink,position) VALUES(?,?,?,?)",(merchant_id,image_url,url,position))
        uncached=list(db.execute("SELECT p.id,p.image_url,m.name FROM merchant_posts p JOIN merchants m ON m.id=p.merchant_id WHERE p.image_blob IS NULL OR p.mime_type IS NULL"))
        for post in uncached:
            cache_post_image(db,post["id"],post["image_url"],post["name"])

def refresh_instagram_profiles(handles=None):
    requested={handle if handle.startswith("@") else f"@{handle}" for handle in (handles or [])}
    results=[]
    with connect() as db:
        rows=list(db.execute("SELECT id,handle FROM merchants ORDER BY id"))
        for merchant in rows:
            if requested and merchant["handle"] not in requested:continue
            try:
                profile=instagram_profile(merchant["handle"])
                biography=(profile.get("biography") or "").strip()
                db.execute("""UPDATE merchants SET biography=?,biography_source='instagram_public_embed',
                  biography_updated_at=datetime('now'),followers_count=COALESCE(?,followers_count),
                  following_count=COALESCE(?,following_count),media_count=COALESCE(?,media_count),
                  metrics_source='instagram_public_embed',metrics_updated_at=datetime('now') WHERE id=?""",
                  (biography,profile.get("followers_count"),profile.get("following_count"),profile.get("media_count"),merchant["id"]))
                results.append({"handle":merchant["handle"],"updated":True,"has_biography":bool(biography)})
            except Exception as error:
                results.append({"handle":merchant["handle"],"updated":False,"error":str(error)})
    return results

def category_tree():
    with connect() as db:
        rows=[dict(row) for row in db.execute("SELECT code,parent_code,level,label_fa,label_en,icon FROM categories ORDER BY level,sort_order,label_fa")]
        counts={row["code"]:0 for row in rows}
        parents={row["code"]:row["parent_code"] for row in rows}
        for item in db.execute("SELECT category_code,COUNT(*) count FROM merchants GROUP BY category_code"):
            code=item["category_code"]
            while code:
                counts[code]=counts.get(code,0)+item["count"]
                code=parents.get(code)
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

def merchants(category=None, query=""):
    params=[]
    where=[]
    if category:
        where.append("m.category_code IN (WITH RECURSIVE branch(code) AS (SELECT ? UNION ALL SELECT c.code FROM categories c JOIN branch b ON c.parent_code=b.code) SELECT code FROM branch)")
        params.append(category)
    sql="SELECT m.* FROM merchants m"+(" WHERE "+" AND ".join(where) if where else "")+" ORDER BY m.id DESC"
    with connect() as db:
        category_rows={row["code"]:dict(row) for row in db.execute("SELECT code,parent_code,label_fa,label_en FROM categories")}
        result=[]
        for row in db.execute(sql,params):
            merchant=dict(row)
            score=0
            if query:
                tokens=[token for token in normalize_search(query).split() if len(token)>1 and token not in SEARCH_STOPWORDS]
                category_labels=[];code=row["category_code"]
                while code and code in category_rows:
                    category_labels.extend((category_rows[code]["label_fa"],category_rows[code]["label_en"]));code=category_rows[code]["parent_code"]
                identity=normalize_search(f'{row["name"]} {row["handle"]} {row["city"]}')
                description=normalize_search(row["description"])
                category_text=normalize_search(" ".join(category_labels))
                phrase=normalize_search(query)
                score=(12 if phrase and phrase in description else 0)+sum((5 if token in identity else 0)+(3 if token in description else 0)+(2 if token in category_text else 0) for token in tokens)
                if not tokens or score==0:continue
            merchant.pop("avatar_blob",None);merchant.pop("avatar_mime_type",None);merchant["avatar_url"]=f"/api/avatars/{row['id']}"
            merchant["posts"]=[{"media_url":f"/api/media/{post['id']}","permalink":post["permalink"],"position":post["position"]} for post in db.execute("SELECT id,permalink,position FROM merchant_posts WHERE merchant_id=? AND image_blob IS NOT NULL ORDER BY position",(row["id"],))]
            merchant["search_score"]=score
            result.append(merchant)
        return sorted(result,key=lambda merchant:(merchant["search_score"],merchant["id"]),reverse=True)

def merchant_detail(merchant_id):
    with connect() as db:
        row=db.execute("SELECT m.*,c.label_fa category_label FROM merchants m JOIN categories c ON c.code=m.category_code WHERE m.id=?",(merchant_id,)).fetchone()
        if not row:return None
        merchant=dict(row);merchant.pop("avatar_blob",None);merchant.pop("avatar_mime_type",None)
        merchant["avatar_url"]=f"/api/avatars/{merchant_id}"
        merchant["posts"]=[{"media_url":f"/api/media/{post['id']}","permalink":post["permalink"],"position":post["position"]} for post in db.execute("SELECT id,permalink,position FROM merchant_posts WHERE merchant_id=? AND image_blob IS NOT NULL ORDER BY position",(merchant_id,))]
        category_rows={item["code"]:dict(item) for item in db.execute("SELECT code,parent_code,label_fa FROM categories")}
        breadcrumb=[];code=row["category_code"]
        while code and code in category_rows:
            breadcrumb.insert(0,{"code":code,"label":category_rows[code]["label_fa"]});code=category_rows[code]["parent_code"]
        merchant["category_path"]=breadcrumb
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
          SELECT substr(created_at,1,10) day,
            SUM(event_type='search') searches,
            SUM(event_type='merchant_click') clicks,
            COUNT(DISTINCT session_id) visitors,
            SUM(event_type='search' AND result_count=0) zero_results
          FROM analytics_events WHERE created_at>=? GROUP BY day ORDER BY day
        """,(since,))}
        daily=[{"date":day,"searches":0,"clicks":0,"visitors":0,"zero_results":0}|daily_rows.get(day,{}) for day in date_keys]
        top_queries=[dict(row) for row in db.execute("""
          SELECT query,COUNT(*) searches,ROUND(AVG(result_count),1) avg_results,
            SUM(result_count=0) zero_results
          FROM analytics_events WHERE created_at>=? AND event_type='search' AND query IS NOT NULL
          GROUP BY query ORDER BY searches DESC,id DESC LIMIT 10
        """,(since,))]
        missed_queries=[dict(row) for row in db.execute("""
          SELECT query,COUNT(*) searches FROM analytics_events
          WHERE created_at>=? AND event_type='search' AND result_count=0 AND query IS NOT NULL
          GROUP BY query ORDER BY searches DESC,id DESC LIMIT 8
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
        body=json.dumps(payload,ensure_ascii=False).encode();self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
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
