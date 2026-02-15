#!/usr/bin/env python3
"""
Extract Prothom Alo e-paper article metadata.
Prioritizes Social Bot Spoofing for instant SSR extraction, falls back to FlareSolverr.
Handles broken HTML (missing quotes) via Regex.
"""
import os
import sys
import time
import json
import csv
import re
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
DELAY = float(os.getenv("DELAY", "0.5"))
OUT_DIR = "output"
BD_TZ = "Asia/Dhaka"


def now_bd() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BD_TZ))
    return datetime.now()


def today_str(override: Optional[str]) -> str:
    return override if override else now_bd().strftime("%d/%m/%Y")


def fetch_meta_as_social_bot(url: str) -> Optional[str]:
    """Pretend to be Facebook to get raw SSR meta tags instantly and bypass JS execution."""
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html"
    }
    print(f"[DEBUG] -> Spoofing Facebook Bot for: {url}")
    try:
        start = time.time()
        r = requests.get(url, headers=headers, timeout=10)
        elapsed = time.time() - start
        
        # Check if it succeeded AND actually contains the meta tags we want
        if r.status_code == 200 and "og:title" in r.text:
            print(f"[DEBUG] <- Facebook Bot fetch successful in {elapsed:.2f}s!")
            return r.text
        else:
            print(f"[DEBUG] <- Facebook Bot missed the tags or got blocked (Status: {r.status_code}).")
            return None
    except Exception as e:
        print(f"[DEBUG] <- Facebook Bot fetch error: {e}")
        return None


def fs_request_get(url: str, flaresolverr_url: str, fs_timeout: int = 15) -> Optional[str]:
    """FlareSolverr fallback if the Social Bot fails."""
    python_timeout = fs_timeout + 20
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": fs_timeout * 1000, 
        "render": True 
    }
    
    print(f"[DEBUG] -> Sending to FlareSolverr Fallback: {url}")
    start_time = time.time()
    try:
        r = requests.post(
            f"{flaresolverr_url.rstrip('/')}/v1", 
            json=payload, 
            timeout=python_timeout
        )
        elapsed = time.time() - start_time
        r.raise_for_status()
        data = r.json()
        
        status = data.get("status", "unknown")
        print(f"[DEBUG] <- FlareSolverr returned '{status}' in {elapsed:.2f} seconds.")
        
        if isinstance(data, dict):
            sol = data.get("solution")
            if isinstance(sol, dict) and "response" in sol:
                return sol["response"]
            if "response" in data:
                return data["response"]
        return None
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[ERROR] <- FlareSolverr fetch failed after {elapsed:.2f}s for {url}: {e}", file=sys.stderr)
        return None


def fetch_json(url: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[ERROR] Failed JSON fetch {url}: {e}", file=sys.stderr)
        return None


def make_mindex_link(eid: str, edate: str, sedId: str, pgid: int, uemail: str) -> str:
    return (
        f"{BASE}/Home/MIndex?eid={eid}&edate={edate}&sedId={sedId}&pgid={pgid}"
        f"&isProductPanel=true&MagazineEdID=0&MagEdDate={edate}"
        f"&isIssueRefresh=False&uemail={uemail}"
    )


def make_mshare_link(orgid: str, eid: str, edate: str, sedId: str) -> str:
    return f"{BASE}/Home/MShareArticle?OrgId={orgid}&eid={eid}&imageview=0&epedate={edate}&sedId={sedId}"


def extract_meta_from_html(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = ""

    # 1. Regex to bypass BeautifulSoup and handle the missing quotation marks.
    match = re.search(r'property="og:title"\s+content=(?:"?Common\s*:\s*)?(.*?)\s*/>', html, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
    
    # 2. Fallback
    if not title:
        og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
        if og_title and og_title.get("content"):
            title = og_title.get("content").strip()
            if title.startswith("Common :"):
                title = title.replace("Common :", "", 1).strip()
                
    # 3. Final fallback
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    desc = ""
    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "twitter:description"}) or soup.find("meta", itemprop="description")
    if og_desc and og_desc.get("content"):
        desc = og_desc.get("content").strip()

    image = ""
    og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", itemprop="image")
    if og_img and og_img.get("content"):
        image = og_img.get("content").strip()

    return {"title": title, "description": desc, "image": image}


def run(edition: str, edition_date_override: Optional[str] = None):
    flaresolverr_url = os.getenv("FLARESOLVERR_URL", "").strip()
    if not flaresolverr_url:
        print("[FATAL] FLARESOLVERR_URL not set. Aborting.", file=sys.stderr)
        sys.exit(2)

    edate = today_str(edition_date_override)
    print(f"[INFO] Starting extraction for Edition: {edition}, Date: {edate}")

    pages = fetch_json(f"{BASE}/Home/GetAllpages", params={"editionid": edition, "editiondate": edate})
    if not pages:
        print("[ERROR] No pages returned. Exiting.", file=sys.stderr)
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "articles.json")
    csv_path = os.path.join(OUT_DIR, "articles.csv")
    xml_path = os.path.join(OUT_DIR, "articles.xml")

    articles = []

    for p in pages:
        page_id = p.get("PageId")
        page_no = p.get("PageNo")
        page_title = p.get("NewsProPageTitle", "")
        if not page_id:
            continue

        print(f"\n[INFO] --- Scanning Page {page_no} (ID: {page_id}) ---")
        stories = fetch_json(f"{BASE}/Home/getStoriesOnPage", params={"pageid": page_id}) or []
        
        for s in stories:
            orgid = s.get("OrgId")
            storyid = s.get("storyid")
            if not orgid:
                continue

            print(f"[INFO] Processing OrgId: {orgid}")
            mshare = make_mshare_link(orgid, edition, edate, SEDID)
            mindex = make_mindex_link(edition, edate, SEDID, page_id, UEMAIL)

            # --- THE NEW HYBRID FETCH LOGIC ---
            # Step 1: Try lightning-fast social bot spoofing
            rendered = fetch_meta_as_social_bot(mshare)
            
            # Step 2: If the bot fails, fallback to FlareSolverr
            if not rendered:
                rendered = fs_request_get(mshare, flaresolverr_url, fs_timeout=15)
            
            # Extract
            if not rendered:
                print(f"[WARNING] Content completely missing for OrgId={orgid}. Saving empty metadata.")
                content = {"title": "", "description": "", "image": ""}
            else:
                content = extract_meta_from_html(rendered)
                print(f"[DEBUG] Meta extracted -> Title: '{content['title'][:40]}...' | Image: {'Yes' if content['image'] else 'No'}")

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
            
            print(f"[DEBUG] Sleeping for {DELAY}s...")
            time.sleep(DELAY)

    print("\n[INFO] Writing files to disk...")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(articles, jf, ensure_ascii=False, indent=2)

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

    print(f"[SUCCESS] Total articles extracted: {len(articles)}")
    print(f"[SUCCESS] Outputs saved to: {OUT_DIR}/")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", "-e", default=EID)
    parser.add_argument("--date", "-d", default=None)
    args = parser.parse_args()
    run(args.edition, args.date)
