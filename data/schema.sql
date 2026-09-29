PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
  code TEXT PRIMARY KEY,
  parent_code TEXT REFERENCES categories(code),
  level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 4),
  label_fa TEXT NOT NULL,
  label_en TEXT NOT NULL,
  icon TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS category_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  instagram_id TEXT UNIQUE,
  name TEXT NOT NULL,
  handle TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  biography TEXT NOT NULL DEFAULT '',
  biography_source TEXT,
  biography_updated_at TEXT,
  category_code TEXT NOT NULL REFERENCES categories(code),
  city TEXT NOT NULL,
  avatar_initial TEXT NOT NULL,
  avatar_color TEXT NOT NULL,
  avatar_blob BLOB,
  avatar_mime_type TEXT,
  avatar_source_url TEXT,
  instagram_url TEXT NOT NULL,
  updated_label TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0,
  verification_source TEXT,
  verified_at TEXT,
  followers_count INTEGER,
  following_count INTEGER,
  media_count INTEGER,
  former_username_count INTEGER,
  account_created_at TEXT,
  metrics_source TEXT,
  metrics_updated_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS merchant_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  image_blob BLOB,
  mime_type TEXT,
  permalink TEXT NOT NULL,
  position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 9),
  UNIQUE(merchant_id, position)
);

CREATE TABLE IF NOT EXISTS analytics_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL CHECK(event_type IN (
    'search', 'category_view', 'merchant_click',
    'login_started', 'login_completed',
    'oauth_started', 'oauth_completed'
  )),
  session_id TEXT NOT NULL,
  query TEXT,
  category_code TEXT REFERENCES categories(code),
  merchant_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
  result_count INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_code);
CREATE INDEX IF NOT EXISTS idx_merchants_category ON merchants(category_code);
CREATE INDEX IF NOT EXISTS idx_posts_merchant ON merchant_posts(merchant_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON analytics_events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_type_created ON analytics_events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_events_query ON analytics_events(query);

/* Legacy bootstrap retained for existing merchant foreign keys. The generated
   data/categories.sql seed expands and updates this after schema creation. */
INSERT OR IGNORE INTO categories(code,parent_code,level,label_fa,label_en,icon,sort_order) VALUES
('50000000',NULL,'1','خوراکی و نوشیدنی','Food/Beverage','◉','10'),
('67000000',NULL,'1','پوشاک','Clothing','♢','20'),
('53000000',NULL,'1','زیبایی و بهداشت','Beauty/Personal Care/Hygiene','✿','30'),
('75000000',NULL,'1','خانه و دکور','Furniture/Furnishings','⌂','40'),
('73000000',NULL,'1','آشپزخانه','Kitchenware and Tableware','▣','50'),
('70000000',NULL,'1','هنر و دست‌ساز','Arts/Crafts/Needlework','✎','60'),
('86000000',NULL,'1','اسباب‌بازی','Toys/Games','☻','70'),
('64000000',NULL,'1','اکسسوری','Personal Accessories','◇','80'),
('63000000',NULL,'1','کفش','Footwear','⌁','90'),
('72000000',NULL,'1','لوازم خانگی','Home Appliances','▤','100'),
('62000000',NULL,'1','لوازم‌التحریر','Stationery/Office','▧','110'),
('93000000',NULL,'1','گل و گیاه','Horticulture Plants','♧','120'),
('50180000','50000000','2','نان و شیرینی','Bread/Bakery Products',NULL,'10'),
('53130000','53000000','2','مراقبت پوست','Skin Products',NULL,'10'),
('62060000','62000000','2','لوازم‌التحریر و اداری','Stationery/Office Machinery',NULL,'10'),
('63010000','63000000','2','کفش و پاپوش','Footwear',NULL,'10'),
('64010000','64000000','2','اکسسوری شخصی','Personal Accessories',NULL,'10'),
('67010000','67000000','2','لباس','Clothing',NULL,'10'),
('70010000','70000000','2','هنر، صنایع دستی و خیاطی','Arts/Crafts Supplies',NULL,'10'),
('72020000','72000000','2','لوازم خانگی کوچک','Small Domestic Appliances',NULL,'10'),
('73040000','73000000','2','لوازم آشپزی','Kitchenware',NULL,'10'),
('75030000','75000000','2','دکور و تزئینات','Ornamental Furnishings',NULL,'10'),
('86010000','86000000','2','اسباب‌بازی و بازی','Toys/Games',NULL,'10'),
('93030000','93000000','2','گیاه آپارتمانی','Live Plants',NULL,'10'),
('50160000','50000000','2','شکلات و تنقلات','Confectionery',NULL,'20'),
('53160000','53000000','2','آرایشی و عطر','Cosmetics/Fragrances',NULL,'20'),
('62050000','62000000','2','کارت، کادو و مناسبت','Greeting Cards/Gift Wrap',NULL,'20'),
('67030000','67000000','2','لباس ورزشی','Activewear',NULL,'20'),
('72010000','72000000','2','لوازم خانگی بزرگ','Major Domestic Appliances',NULL,'20'),
('73050000','73000000','2','ظروف پذیرایی','Tableware',NULL,'20'),
('75010000','75000000','2','مبلمان','Furniture',NULL,'20'),
('93010000','93000000','2','گل شاخه‌بریده','Cut Flowers',NULL,'20'),
('50130000','50000000','2','لبنیات و تخم‌مرغ','Dairy/Eggs',NULL,'30'),
('50132100','50130000','3','ماست','Yogurt',NULL,'10'),
('50161800','50160000','3','محصولات قندی و شکلاتی','Confectionery Products',NULL,'10'),
('50182000','50180000','3','شیرینی و کیک','Sweet Bakery Products',NULL,'10'),
('53131100','53130000','3','محصولات پوستی','Skin Care',NULL,'10'),
('53161000','53160000','3','لوازم آرایش','Cosmetic/MakeUp Products',NULL,'10'),
('62060100','62060000','3','نوشت‌افزار و طراحی','Writing/Design Implements',NULL,'10'),
('63010300','63010000','3','کفش روزمره','General Purpose Footwear',NULL,'10'),
('64010100','64010000','3','زیورآلات','Jewellery',NULL,'10'),
('67010800','67010000','3','بالاتنه','Upper Body Wear/Tops',NULL,'10'),
('70011400','70010000','3','مواد اولیه هنری','Arts/Crafts Supplies',NULL,'10'),
('72020100','72020000','3','پخت‌وپز و گرمایش','Small Cooking Appliances',NULL,'10'),
('73040400','73040000','3','ظروف پخت‌وپز','Cookware/Bakeware',NULL,'10'),
('75030100','75030000','3','اشیای تزئینی','Ornaments',NULL,'10'),
('86010400','86010000','3','اسباب‌بازی آموزشی','Educational Toys',NULL,'10'),
('93037400','93030000','3','فیکوس','Ficus - Live Plants',NULL,'10'),
('50181900','50180000','3','نان','Bread',NULL,'20'),
('53161300','53160000','3','عطر','Fragrances',NULL,'20'),
('62061100','62060000','3','کاغذ و مقوا','Stationery Paper/Card',NULL,'20'),
('63010100','63010000','3','کفش ورزشی','Athletic Footwear',NULL,'20'),
('64010300','64010000','3','ساعت','Watches',NULL,'20'),
('67010300','67010000','3','شلوار و دامن','Lower Body Wear/Bottoms',NULL,'20'),
('70010100','70010000','3','نقاشی و طراحی','Painting/Drawing Supplies',NULL,'20'),
('72020200','72020000','3','آماده‌سازی غذا و نوشیدنی','Food Preparation Appliances',NULL,'20'),
('73040100','73040000','3','نگهداری مواد غذایی','Kitchen Storage',NULL,'20'),
('75030200','75030000','3','تابلو، آینه و قاب','Pictures/Mirrors/Frames',NULL,'20'),
('86010100','86010000','3','بازی فکری و پازل','Board Games/Puzzles',NULL,'20'),
('93030500','93030000','3','آلوئه‌ورا','Aloe - Live Plants',NULL,'20'),
('62060400','62060000','3','برنامه‌ریزی و نظم‌دهی','Planning Stationery',NULL,'30'),
('63010400','63010000','3','پاپوش خانگی','Indoor Footwear',NULL,'30'),
('64010200','64010000','3','کیف و اکسسوری حمل','Personal Carriers',NULL,'30'),
('67010200','67010000','3','لباس یکسره','Full Body Wear',NULL,'30'),
('70010700','70010000','3','کاغذ و کارت‌سازی','Paper/Card Making',NULL,'30'),
('72020800','72020000','3','خانه هوشمند','Smart Home Equipment',NULL,'30'),
('86010200','86010000','3','عروسک','Dolls/Soft Toys',NULL,'30'),
('93032500','93030000','3','کالاتیا','Calathea - Live Plants',NULL,'30');
