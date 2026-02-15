# extract_prothom_alo_orgids.py
#!/usr/bin/env python3
"""
Extract Prothom Alo e-paper articles (OrgId + share links + MIndex base links).
Date/time use Bangladesh time (Asia/Dhaka).
Date format: DD/MM/YYYY
"""
import os
import sys
import time
import json
import csv
import argparse
from datetime import datetime
from typing import List, Dict, Optional
import requests
import xml.etree.ElementTree as ET

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# ----- CONFIG -----
UEMAIL = "1169c825b8"
EID = "1"
SEDID = "1"
DELAY = 0.5
BASE = "https://epaper.prothomalo.com"
BD_TZ = "Asia/Dhaka"
# ------------------

def now_bd() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BD_TZ))
    return datetime.now()

def today_str(dd_mm_yyyy: Optional[str]) -> str:
    if dd_mm_yyyy:
        return dd_mm_yyyy
    return now_bd().strftime("%d/%m/%Y")

def ts_bd() -> str:
    return now_bd().strftime("%Y%m%d_%H%M%S")

def get_all_pages(edition_id: str, edition_date: str, timeout: int = 20) -> List[Dict]:
    url = f"{BASE}/Home/GetAllpages"
    params = {"editionid": edition_id, "editiondate": edition_date}
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json() or []

def get_stories_on_page(page_id: int, timeout: int = 20) -> List[Dict]:
    url = f"{BASE}/Home/getStoriesOnPage"
    params = {"pageid": page_id}
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json() or []

def make_mindex_link(eid: str, edate: str, sedId: str, pgid: int, uemail: str) -> str:
    return (
        f"{BASE}/Home/MIndex?eid={eid}"
        f"&edate={edate}"
        f"&sedId={sedId}"
        f"&pgid={pgid}"
        f"&isProductPanel=true"
        f"&MagazineEdID=0"
        f"&MagEdDate={edate}"
        f"&isIssueRefresh=False"
        f"&uemail={uemail}"
    )

def make_mshare_link(orgid: str, eid: str, edate: str, sedId: str) -> str:
    return (
        f"{BASE}/Home/MShareArticle?OrgId={orgid}"
        f"&eid={eid}"
        f"&imageview=0"
        f"&epedate={edate}"
        f"&sedId={sedId}"
    )

def to_xml(articles: List[Dict], outpath: str):
    root = ET.Element("Epaper")
    root.set("date", articles[0].get("EditionDate","") if articles else "")
    for a in articles:
        node = ET.SubElement(root, "Article")
        for k, v in a.items():
            child = ET.SubElement(node, k)
            child.text = str(v) if v is not None else ""
    tree = ET.ElementTree(root)
    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    tree.write(outpath, encoding="utf-8", xml_declaration=True)

def run(edition: str, edition_date: Optional[str], out_prefix: str, delay: float):
    edate = today_str(edition_date)
    pages = get_all_pages(edition, edate)
    if not pages:
        print("No pages returned by GetAllpages.", file=sys.stderr)
        return

    articles = []
    for p in pages:
        page_id = p.get("PageId")
        page_no = p.get("PageNo")
        page_title = p.get("NewsProPageTitle", "")
        try:
            stories = get_stories_on_page(page_id)
        except Exception as e:
            print(f"Failed to fetch stories for page {page_id}: {e}", file=sys.stderr)
            stories = []
        for s in stories:
            orgid = s.get("OrgId")
            storyid = s.get("storyid")
            if not orgid:
                continue
            mindex = make_mindex_link(EID, edate, SEDID, page_id, UEMAIL)
            mshare = make_mshare_link(orgid, EID, edate, SEDID)
            article = {
                "OrgId": orgid,
                "StoryId": storyid,
                "PageNo": page_no,
                "PageId": page_id,
                "PageTitle": page_title,
                "EditionId": edition,
                "EditionDate": edate,
                "MShareArticle": mshare,
                "MIndexBase": mindex
            }
            articles.append(article)
        time.sleep(delay)

    ts = ts_bd()
    outdir = f"{out_prefix}_{ts}"
    os.makedirs(outdir, exist_ok=True)

    json_path = os.path.join(outdir, "articles.json")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(articles, jf, ensure_ascii=False, indent=2)

    csv_path = os.path.join(outdir, "articles.csv")
    if articles:
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            writer = csv.DictWriter(cf, fieldnames=list(articles[0].keys()))
            writer.writeheader()
            writer.writerows(articles)
    else:
        open(csv_path, "w").close()

    xml_path = os.path.join(outdir, "articles.xml")
    to_xml(articles, xml_path)

    print(json_path)
    print(csv_path)
    print(xml_path)
    print(f"Total articles: {len(articles)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Prothom Alo e-paper articles")
    parser.add_argument("--edition", "-e", default=EID, help="edition id (default 1)")
    parser.add_argument("--date", "-d", default=None, help="edition date DD/MM/YYYY (default today BD time)")
    parser.add_argument("--output", "-o", default="output/epaper", help="output prefix")
    parser.add_argument("--delay", "-t", type=float, default=DELAY, help="delay between page requests")
    args = parser.parse_args()
    run(args.edition, args.date, args.output, args.delay)
