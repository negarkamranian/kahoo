#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parent.parent
API="https://gpc-api.gs1.org/api/browser/download/publication/{}/json"
HEADERS={"Origin":"https://gpc-browser.gs1.org","Referer":"https://gpc-browser.gs1.org/","Content-Type":"application/json;charset=utf-8","User-Agent":"Mozilla/5.0"}

def download(publication_id,path):
    with urlopen(Request(API.format(publication_id),headers=HEADERS),timeout=120) as response:
        path.write_bytes(response.read())

def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("Childs") or [])

def clean_fa(value):
    return " ".join((value or "").translate(str.maketrans({"ي":"ی","ى":"ی","ك":"ک","ة":"ه","ۀ":"ه"})).split())

def sql(value):
    return "'"+str(value).replace("'","''")+"'"

def main():
    parser=argparse.ArgumentParser(description="Build Kahoo's Iran-relevant GS1 category seed")
    parser.add_argument("--current",type=Path,default=Path("/tmp/gpc-2026.json"))
    parser.add_argument("--persian",type=Path,default=Path("/tmp/gpc-fa-2020.json"))
    parser.add_argument("--output",type=Path,default=ROOT/"data/categories.sql")
    parser.add_argument("--download",action="store_true")
    args=parser.parse_args()
    policy=json.loads((ROOT/"data/gpc_policy.json").read_text())
    if args.download:
        download(policy["source_publication_id"],args.current)
        download(policy["persian_publication_id"],args.persian)
    current=json.loads(args.current.read_text())
    persian=json.loads(args.persian.read_text())
    fa={str(node["Code"]):clean_fa(node["Title"]) for node in walk(persian["Schema"]) if node.get("Active",True)}
    allowed=set(policy["allowed_segments"]);global_terms=tuple(term.lower() for term in policy["excluded_terms"])
    rows=[];excluded=[];untranslated=[]

    def keep(node,segment,path):
        code=str(node["Code"]);title=node["Title"].strip();full_path=" / ".join((*path,title)).lower()
        terms=list(global_terms)
        if segment=="50000000":terms.extend(term.lower() for term in policy["food_excluded_terms"])
        if segment=="51000000":terms.extend(term.lower() for term in policy["healthcare_excluded_terms"])
        matched=next((term for term in terms if term in full_path),None)
        if matched:
            excluded.append((code,title,matched));return None
        children=[child for raw in (node.get("Childs") or []) if raw.get("Active",True) and raw.get("Level",9)<=4 if (child:=keep(raw,segment,(*path,title)))]
        if node["Level"]<4 and not children:return None
        return node,children

    def flatten(item,parent=None,order=0):
        node,children=item;code=str(node["Code"]);label=policy["segment_labels_fa"].get(code) or fa.get(code)
        if not label:
            label=node["Title"].strip();untranslated.append(code)
        rows.append((code,parent,node["Level"],label,node["Title"].strip(),order))
        for index,child in enumerate(children,1):flatten(child,code,index*10)

    for segment_order,node in enumerate(current["Schema"],1):
        code=str(node["Code"])
        if code in allowed and node.get("Active",True):
            item=keep(node,code,())
            if item:flatten(item,None,segment_order*10)

    lines=["-- Generated from GS1 GPC May 2026; do not edit manually.","BEGIN;","CREATE TEMP TABLE _category_seed(code TEXT PRIMARY KEY,parent_code TEXT,level INTEGER,label_fa TEXT,label_en TEXT,sort_order INTEGER);"]
    for row in rows:
        values=",".join("NULL" if value is None else sql(value) for value in row)
        lines.append(f"INSERT INTO _category_seed VALUES({values});")
    lines.extend([
      "INSERT INTO categories(code,parent_code,level,label_fa,label_en,icon,sort_order) SELECT code,parent_code,level,label_fa,label_en,NULL,sort_order FROM _category_seed WHERE level=1 ON CONFLICT(code) DO UPDATE SET parent_code=excluded.parent_code,level=excluded.level,label_fa=excluded.label_fa,label_en=excluded.label_en,icon=NULL,sort_order=excluded.sort_order;",
      "INSERT INTO categories(code,parent_code,level,label_fa,label_en,icon,sort_order) SELECT code,parent_code,level,label_fa,label_en,NULL,sort_order FROM _category_seed WHERE level=2 ON CONFLICT(code) DO UPDATE SET parent_code=excluded.parent_code,level=excluded.level,label_fa=excluded.label_fa,label_en=excluded.label_en,icon=NULL,sort_order=excluded.sort_order;",
      "INSERT INTO categories(code,parent_code,level,label_fa,label_en,icon,sort_order) SELECT code,parent_code,level,label_fa,label_en,NULL,sort_order FROM _category_seed WHERE level=3 ON CONFLICT(code) DO UPDATE SET parent_code=excluded.parent_code,level=excluded.level,label_fa=excluded.label_fa,label_en=excluded.label_en,icon=NULL,sort_order=excluded.sort_order;",
      "INSERT INTO categories(code,parent_code,level,label_fa,label_en,icon,sort_order) SELECT code,parent_code,level,label_fa,label_en,NULL,sort_order FROM _category_seed WHERE level=4 ON CONFLICT(code) DO UPDATE SET parent_code=excluded.parent_code,level=excluded.level,label_fa=excluded.label_fa,label_en=excluded.label_en,icon=NULL,sort_order=excluded.sort_order;",
      "DELETE FROM categories WHERE level=4 AND code NOT IN (SELECT code FROM _category_seed) AND code NOT IN (SELECT category_code FROM merchants) AND code NOT IN (SELECT category_code FROM analytics_events WHERE category_code IS NOT NULL);",
      "DELETE FROM categories WHERE level=3 AND code NOT IN (SELECT code FROM _category_seed) AND code NOT IN (SELECT category_code FROM merchants) AND code NOT IN (SELECT category_code FROM analytics_events WHERE category_code IS NOT NULL) AND code NOT IN (SELECT parent_code FROM categories WHERE parent_code IS NOT NULL);",
      "DELETE FROM categories WHERE level=2 AND code NOT IN (SELECT code FROM _category_seed) AND code NOT IN (SELECT category_code FROM merchants) AND code NOT IN (SELECT category_code FROM analytics_events WHERE category_code IS NOT NULL) AND code NOT IN (SELECT parent_code FROM categories WHERE parent_code IS NOT NULL);",
      "DELETE FROM categories WHERE level=1 AND code NOT IN (SELECT code FROM _category_seed) AND code NOT IN (SELECT category_code FROM merchants) AND code NOT IN (SELECT category_code FROM analytics_events WHERE category_code IS NOT NULL) AND code NOT IN (SELECT parent_code FROM categories WHERE parent_code IS NOT NULL);",
      f"INSERT INTO category_metadata(key,value) VALUES('gpc_source',{sql(policy['source'])}) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
      f"INSERT INTO category_metadata(key,value) VALUES('category_count',{sql(len(rows))}) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
      f"INSERT INTO category_metadata(key,value) VALUES('excluded_branch_count',{sql(len(excluded))}) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
      f"INSERT INTO category_metadata(key,value) VALUES('english_fallback_count',{sql(len(untranslated))}) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
      "DROP TABLE _category_seed;","COMMIT;",""])
    args.output.write_text("\n".join(lines))
    print(json.dumps({"categories":len(rows),"segments":sum(row[2]==1 for row in rows),"families":sum(row[2]==2 for row in rows),"classes":sum(row[2]==3 for row in rows),"bricks":sum(row[2]==4 for row in rows),"excluded_branches":len(excluded),"english_fallbacks":len(untranslated)},ensure_ascii=False))

if __name__=="__main__":main()
