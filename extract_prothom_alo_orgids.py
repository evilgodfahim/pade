#!/usr/bin/env python3
"""
Extract Prothom Alo e-paper article metadata.
Prioritizes Social Bot Spoofing for instant SSR extraction, falls back to FlareSolverr.
Handles broken HTML (missing quotes) and duplicate generic meta tags.
Outputs standard RSS 2.0 format for compatibility with feed readers.
"""
import os
import sys
import time
import json
import csv
import re
from datetime import datetime
from email.utils import format_datetime
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

    # 1. Regex to find ALL og:titles, bypassing BeautifulSoup's broken parsing of unquoted attributes
    title_matches = re.findall(r'property="og:title"\s+content=(.*?)\s*/>', html, re.IGNORECASE)

    if title_matches:
        # Grab the LAST match in the array (the specific article title, ignoring the top generic one)
        raw_title = title_matches[-1].strip()
        # Strip out "Common :" and any quotation marks
        title = re.sub(r'^"?Common\s*:\s*', '', raw_title, flags=re.IGNORECASE).strip('"\' ')

    # 2. Final fallback
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Find ALL descriptions and take the last one
    desc = ""
    og_descs = soup.find_all("meta", property="og:description") or soup.find_all("meta", attrs={"name": "twitter:description"})
    if og_descs and og_descs[-1].get("content"):
        desc = og_descs[-1].get("content").strip()

    # Find ALL images and take the last one
    image = ""
    og_imgs = soup.find_all("meta", property="og:image") or soup.find_all("meta", attrs={"name": "twitter:image"})
    if og_imgs and og_imgs[-1].get("content"):
        image = og_imgs[-1].get("content").strip()

    return {"title": title, "description": desc, "image": image}


def run(edition: str, edition_date_override: Optional[str] = None):
    flaresolverr_url = os.getenv("FLARESOLVERR_URL", "").strip()
    if not flaresolverr_url:
        print("[FATAL] FLARESOLVERR_URL not set. Aborting.", file=sys.stderr)
        sys.exit(2)

    edate = today_str(edition_date_override)
    # Generate an RFC-822 formatted date string for the RSS feed
    rfc_pub_date = format_datetime(now_bd())
    
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

            # --- HYBRID FETCH LOGIC ---
            rendered = fetch_meta_as_social_bot(mshare)

            if not rendered:
                rendered = fs_request_get(mshare, flaresolverr_url, fs_timeout=15)

            if not rendered:
                print(f"[WARNING] Content missing for OrgId={orgid}. Saving empty metadata.")
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

    # --- Write as standard RSS 2.0 ---
    with open(xml_path, "w", encoding="utf-8") as xf:
        xf.write('<?xml version="1.0" encoding="utf-8"?>\n')
        xf.write('<rss version="2.0">\n')
        xf.write('  <channel>\n')
        xf.write(f'    <title>Prothom Alo E-paper ({edate})</title>\n')
        xf.write(f'    <link>{BASE}</link>\n')
        xf.write('    <description>Extracted articles from Prothom Alo E-paper</description>\n')
        xf.write(f'    <pubDate>{rfc_pub_date}</pubDate>\n')
        
        for a in articles:
            # Escape XML special characters safely
            title_safe = str(a.get("Headline") or f"Article {a.get('OrgId')}").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            link_safe = str(a.get("Link") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            guid_safe = str(a.get("OrgId") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
            img_url = a.get("ImageUrl") or ""
            desc_text = a.get("Description") or ""
            
            # Combine image and description safely inside CDATA
            desc_html = f'<img src="{img_url}" /><br/><br/>' if img_url else ""
            desc_html += desc_text
            
            xf.write("    <item>\n")
            xf.write(f"      <title>{title_safe}</title>\n")
            xf.write(f"      <link>{link_safe}</link>\n")
            xf.write(f"      <guid isPermaLink=\"false\">{guid_safe}</guid>\n")
            xf.write(f"      <pubDate>{rfc_pub_date}</pubDate>\n")
            xf.write(f"      <description><![CDATA[{desc_html}]]></description>\n")
            xf.write("    </item>\n")
            
        xf.write("  </channel>\n")
        xf.write("</rss>\n")

    print(f"[SUCCESS] Total articles extracted: {len(articles)}")
    print(f"[SUCCESS] Outputs saved to: {OUT_DIR}/")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", "-e", default=EID)
    parser.add_argument("--date", "-d", default=None)
    args = parser.parse_args()
    run(args.edition, args.date)
