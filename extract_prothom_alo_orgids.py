#!/usr/bin/env python3
"""
Extract Prothom Alo e-paper article metadata (Headline, Description, Image, Link).
Optimized for speed: Fetches initial HTML only, no JS rendering delays.
Outputs (overwritten each run):
  - output/articles.json
  - output/articles.csv
  - output/articles.xml

Requires environment:
  FLARESOLVERR_URL  (e.g. http://127.0.0.1:8191) -- mandatory
Date/time uses Bangladesh time (Asia/Dhaka). Date format: DD/MM/YYYY
"""
import os
import sys
import time
import json
import csv
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# CONFIG
BASE = "https://epaper.prothomalo.com"
EID = os.getenv("EDITION_ID", "1")
SEDID = os.getenv("SEDID", "1")
UEMAIL = os.getenv("UEMAIL", "1169c825b8")
DELAY = float(os.getenv("DELAY", "0.2")) # Reduced delay since we aren't doing heavy rendering
OUT_DIR = "output"
BD_TZ = "Asia/Dhaka"


def now_bd() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BD_TZ))
    return datetime.now()


def today_str(override: Optional[str]) -> str:
    return override if override else now_bd().strftime("%d/%m/%Y")


def fs_request_get(url: str, flaresolverr_url: str, timeout: int = 30) -> Optional[str]:
    """
    Use FlareSolverr to fetch a URL quickly.
    We only need the initial HTML for meta tags, so we don't ask it to render/wait.
    """
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": timeout * 1000
        # Removed "render": True. Returns instantly once CF challenge is passed.
    }
    try:
        r = requests.post(f"{flaresolverr_url.rstrip('/')}/v1", json=payload, timeout=timeout + 5)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            sol = data.get("solution")
            if isinstance(sol, dict) and "response" in sol:
                return sol["response"]
            if "response" in data:
                return data["response"]
        return None
    except Exception as e:
        print(f"FlareSolverr fetch failed for {url}: {e}", file=sys.stderr)
        return None


def fetch_json(url: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Failed JSON fetch {url} params={params}: {e}", file=sys.stderr)
        return None


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


def extract_meta_from_html(html: str) -> Dict[str, str]:
    """Extract metadata (title, description, image) from meta tags."""
    soup = BeautifulSoup(html, "lxml")

    # 1. Title / Headline
    title = ""
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og_title and og_title.get("content"):
        title = og_title.get("content").strip()
        if title.startswith("Common : "):
            title = title.replace("Common : ", "", 1).strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    # 2. Description
    desc = ""
    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "twitter:description"})
    if og_desc and og_desc.get("content"):
        desc = og_desc.get("content").strip()

    # 3. Image
    image = ""
    og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", itemprop="image")
    if og_img and og_img.get("content"):
        image = og_img.get("content").strip()

    return {"title": title, "description": desc, "image": image}


def run(edition: str, edition_date_override: Optional[str] = None):
    flaresolverr_url = os.getenv("FLARESOLVERR_URL", "").strip()
    if not flaresolverr_url:
        print("FLARESOLVERR_URL not set. Aborting—all MShareArticle fetches must use FlareSolverr.", file=sys.stderr)
        sys.exit(2)

    edate = today_str(edition_date_override)

    # 1) Get all pages
    pages = fetch_json(f"{BASE}/Home/GetAllpages", params={"editionid": edition, "editiondate": edate})
    if not pages:
        print("No pages returned. Exiting.", file=sys.stderr)
        return

    # Prepare outputs
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "articles.json")
    csv_path = os.path.join(OUT_DIR, "articles.csv")
    xml_path = os.path.join(OUT_DIR, "articles.xml")

    articles = []

    # Iterate pages -> stories
    for p in pages:
        page_id = p.get("PageId")
        page_no = p.get("PageNo")
        page_title = p.get("NewsProPageTitle", "")
        if not page_id:
            continue

        stories = fetch_json(f"{BASE}/Home/getStoriesOnPage", params={"pageid": page_id}) or []
        for s in stories:
            orgid = s.get("OrgId")
            storyid = s.get("storyid")
            if not orgid:
                continue

            # Build URLs
            mshare = make_mshare_link(orgid, edition, edate, SEDID)
            mindex = make_mindex_link(edition, edate, SEDID, page_id, UEMAIL)

            # Fetch the page using fast FlareSolverr
            rendered = fs_request_get(mshare, flaresolverr_url, timeout=30)
            if not rendered:
                print(f"Fetch failed for OrgId={orgid}, URL={mshare}", file=sys.stderr)
                content = {"title": "", "description": "", "image": ""}
            else:
                content = extract_meta_from_html(rendered)

            article = {
                "OrgId": orgid,
                "StoryId": storyid,
                "PageNo": page_no,
                "PageId": page_id,
                "PageTitle": page_title,
                "EditionId": edition,
                "EditionDate": edate,
                "Headline": content["title"],
                "Description": content["description"],
                "ImageUrl": content["image"],
                "Link": mshare,
                "MIndexBase": mindex
            }
            articles.append(article)
            time.sleep(DELAY)

    # Write JSON
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(articles, jf, ensure_ascii=False, indent=2)

    # Write CSV
    if articles:
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            fieldnames = ["OrgId", "StoryId", "PageNo", "PageId", "PageTitle", "EditionId", "EditionDate", "Headline", "Description", "ImageUrl", "Link", "MIndexBase"]
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            for a in articles:
                row = {k: a.get(k, "") for k in fieldnames}
                writer.writerow(row)
    else:
        open(csv_path, "w").close()

    # Write XML
    with open(xml_path, "w", encoding="utf-8") as xf:
        xf.write('<?xml version="1.0" encoding="utf-8"?>\n')
        xf.write(f'<Epaper date="{edate}">\n')
        for a in articles:
            xf.write("  <Article>\n")
            for k, v in a.items():
                if v is None:
                    v = ""
                safe = str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                xf.write(f"    <{k}>{safe}</{k}>\n")
            xf.write("  </Article>\n")
        xf.write("</Epaper>\n")

    print(json_path)
    print(csv_path)
    print(xml_path)
    print(f"Total articles extracted: {len(articles)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract Prothom Alo e-paper articles metadata (fast fetch via FlareSolverr).")
    parser.add_argument("--edition", "-e", default=EID)
    parser.add_argument("--date", "-d", default=None, help="DD/MM/YYYY (default BD today)")
    args = parser.parse_args()
    run(args.edition, args.date)
