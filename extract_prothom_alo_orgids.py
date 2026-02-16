#!/usr/bin/env python3
"""
Extract Prothom Alo e-paper article metadata and full text.
Prioritizes Social Bot Spoofing for instant SSR extraction, falls back to FlareSolverr.
Handles broken HTML (missing quotes) and duplicate generic meta tags.
Extracts both main article body and linked article body, removing inline ads.
Outputs standard RSS 2.0 format for compatibility with feed readers.
Articles starting with "পৃষ্ঠার পর" are excluded from XML output.
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
FS_TIMEOUT = int(os.getenv("FS_TIMEOUT", "10")) # Reduced to 10s to prevent massive delays
OUT_DIR = "output"
BD_TZ = "Asia/Dhaka"
XML_CHUNK_SIZE = 100  # max articles per xml file

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
        r = requests.get(url, headers=headers, timeout=8)
        elapsed = time.time() - start

        # Ensure the actual article body is present in the static HTML
        if r.status_code == 200 and 'id="body"' in r.text:
            print(f"[DEBUG] <- Facebook Bot fetch successful and body found in {elapsed:.2f}s!")
            return r.text
        else:
            print(f"[DEBUG] <- Facebook Bot missed tags or JS body wasn't rendered (Status: {r.status_code}).")
            return None
    except Exception as e:
        print(f"[DEBUG] <- Facebook Bot fetch error: {e}")
        return None

def fs_request_get(url: str, flaresolverr_url: str, fs_timeout: int) -> Optional[str]:
    """FlareSolverr fallback if the Social Bot fails to get the fully rendered body."""
    python_timeout = fs_timeout + 5
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": fs_timeout * 1000,
        "render": True
    }

    print(f"[DEBUG] -> Sending to FlareSolverr Fallback (max {fs_timeout}s): {url}")
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

def extract_article_data(html: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
    title = ""

    # 1. Regex to find ALL og:titles, bypassing BeautifulSoup's broken parsing of unquoted attributes
    title_matches = re.findall(r'property="og:title"\s+content=(.*?)\s*/>', html, re.IGNORECASE)
    if title_matches:
        raw_title = title_matches[-1].strip()
        title = re.sub(r'^"?Common\s*:\s*', '', raw_title, flags=re.IGNORECASE).strip('"\' ')

    # 2. Final fallback for title
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Meta descriptions and images
    desc = ""
    og_descs = soup.find_all("meta", property="og:description") or soup.find_all("meta", attrs={"name": "twitter:description"})
    if og_descs and og_descs[-1].get("content"):
        desc = og_descs[-1].get("content").strip()

    image = ""
    og_imgs = soup.find_all("meta", property="og:image") or soup.find_all("meta", attrs={"name": "twitter:image"})
    if og_imgs and og_imgs[-1].get("content"):
        image = og_imgs[-1].get("content").strip()

    # 3. Full Text Extraction & Exclusion Logic
    main_body = soup.find("div", id="body")
    linked_body = soup.find("div", id="divlinkedstorybody")

    full_text = ""
    exclude_article = False

    if main_body:
        # Remove embedded ads securely
        for ad in main_body.find_all("div", class_=re.compile(r"ad_inside_text_story", re.IGNORECASE)):
            ad.decompose()
        
        paragraphs = main_body.find_all("p")
        
        # Check ONLY the very first line/paragraph of the main article for the exclusion phrase
        if paragraphs:
            first_line = paragraphs[0].get_text(strip=True)
            if "পৃষ্ঠার পর" in first_line:
                exclude_article = True
        elif main_body.get_text(strip=True)[:50].find("পৃষ্ঠার পর") != -1:
            exclude_article = True

        main_text = "\n\n".join([p.get_text(strip=True) for p in paragraphs])
        full_text += main_text

    if linked_body:
        # Remove embedded ads securely
        for ad in linked_body.find_all("div", class_=re.compile(r"ad_inside_text_story", re.IGNORECASE)):
            ad.decompose()

        linked_paragraphs = linked_body.find_all("p")
        linked_text = "\n\n".join([p.get_text(strip=True) for p in linked_paragraphs])
        
        if full_text and linked_text:
            full_text += "\n\n---\n\n" # Optional separator to denote linked story part
        full_text += linked_text

    return {
        "title": title, 
        "description": desc, 
        "image": image,
        "full_text": full_text.strip(),
        "exclude": exclude_article
    }

def _escape_xml(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _write_rss_chunk(articles_chunk: List[Dict], edate: str, rfc_pub_date: str, xml_out_path: str, file_index: int):
    with open(xml_out_path, "w", encoding="utf-8") as xf:
        xf.write('<?xml version="1.0" encoding="utf-8"?>\n')
        xf.write('<rss version="2.0">\n')
        xf.write('  <channel>\n')
        title_suffix = f" (part {file_index})" if file_index > 1 else ""
        xf.write(f'    <title>Prothom Alo E-paper ({edate}){title_suffix}</title>\n')
        xf.write(f'    <link>{BASE}</link>\n')
        xf.write('    <description>Extracted articles from Prothom Alo E-paper</description>\n')
        xf.write(f'    <pubDate>{rfc_pub_date}</pubDate>\n')

        for a in articles_chunk:
            title_safe = _escape_xml(str(a.get("Headline") or f"Article {a.get('OrgId')}"))
            link_safe = _escape_xml(str(a.get("Link") or ""))
            guid_safe = _escape_xml(str(a.get("OrgId") or ""))

            img_url = a.get("ImageUrl") or ""
            desc_html = f'<img src="{_escape_xml(img_url)}" /><br/><br/>' if img_url else ""
            
            # Write full text as paragraph elements inside the description
            full_text = a.get("FullText") or ""
            if full_text:
                formatted_text = "".join([f"<p>{_escape_xml(p)}</p>" for p in full_text.split("\n\n") if p.strip()])
                desc_html += formatted_text
            else:
                desc_html += _escape_xml(a.get("Description") or "")

            xf.write("    <item>\n")
            xf.write(f"      <title>{title_safe}</title>\n")
            xf.write(f"      <link>{link_safe}</link>\n")
            xf.write(f"      <guid isPermaLink=\"false\">{guid_safe}</guid>\n")
            xf.write(f"      <pubDate>{rfc_pub_date}</pubDate>\n")
            xf.write(f"      <description><![CDATA[{desc_html}]]></description>\n")
            xf.write("    </item>\n")

        xf.write("  </channel>\n")
        xf.write("</rss>\n")

def run(edition: str, edition_date_override: Optional[str] = None):
    flaresolverr_url = os.getenv("FLARESOLVERR_URL", "").strip()
    if not flaresolverr_url:
        print("[FATAL] FLARESOLVERR_URL not set. Aborting.", file=sys.stderr)
        sys.exit(2)

    edate = today_str(edition_date_override)
    rfc_pub_date = format_datetime(now_bd())

    print(f"[INFO] Starting extraction for Edition: {edition}, Date: {edate}")

    pages = fetch_json(f"{BASE}/Home/GetAllpages", params={"editionid": edition, "editiondate": edate})
    if not pages:
        print("[ERROR] No pages returned. Exiting.", file=sys.stderr)
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "articles.json")
    csv_path = os.path.join(OUT_DIR, "articles.csv")
    xml_base_path = os.path.join(OUT_DIR, "articles.xml")

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

            rendered = fetch_meta_as_social_bot(mshare)
            if not rendered:
                rendered = fs_request_get(mshare, flaresolverr_url, fs_timeout=FS_TIMEOUT)

            if not rendered:
                print(f"[WARNING] Content missing for OrgId={orgid}. Saving empty metadata.")
                content = {"title": "", "description": "", "image": "", "full_text": "", "exclude": False}
            else:
                content = extract_article_data(rendered)
                print(f"[DEBUG] Extracted -> Title: '{(content['title'] or '')[:30]}...' | Exclude Flag: {content['exclude']}")

            article = {
                "OrgId": orgid,
                "StoryId": storyid,
                "PageNo": page_no,
                "PageId": page_id,
                "PageTitle": page_title,
                "EditionId": edition,
                "EditionDate": edate,
                "Headline": content.get("title", ""),
                "Description": content.get("description", ""),
                "FullText": content.get("full_text", ""),
                "ImageUrl": content.get("image", ""),
                "Link": mshare,
                "MIndexBase": mindex,
                "ExcludeArticle": content.get("exclude", False)
            }
            articles.append(article)

            print(f"[DEBUG] Sleeping for {DELAY}s...")
            time.sleep(DELAY)

    print("\n[INFO] Writing files to disk...")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(articles, jf, ensure_ascii=False, indent=2)

    if articles:
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            fieldnames = ["OrgId", "StoryId", "PageNo", "PageId", "PageTitle", "EditionId", "EditionDate", "Headline", "Description", "FullText", "ImageUrl", "Link", "MIndexBase", "ExcludeArticle"]
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            for a in articles:
                row = {k: a.get(k, "") for k in fieldnames}
                writer.writerow(row)
    else:
        open(csv_path, "w").close()

    # --- Filter articles for XML (exclude flagged articles) ---
    xml_articles = [a for a in articles if not a.get("ExcludeArticle")]
    
    excluded_count = len(articles) - len(xml_articles)
    if excluded_count:
        print(f"[INFO] Excluding {excluded_count} article(s) from XML because they start with 'পৃষ্ঠার পর'.")

    # --- Write as standard RSS 2.0 with chunking if necessary ---
    total_xml = len(xml_articles)
    if total_xml == 0:
        _write_rss_chunk([], edate, rfc_pub_date, xml_base_path, 1)
        print(f"[SUCCESS] Total articles extracted: {len(articles)} (XML contains 0 items after exclusions)")
        print(f"[SUCCESS] Outputs saved to: {OUT_DIR}/")
        return

    num_files = (total_xml + XML_CHUNK_SIZE - 1) // XML_CHUNK_SIZE
    for idx in range(num_files):
        start = idx * XML_CHUNK_SIZE
        end = start + XML_CHUNK_SIZE
        chunk = xml_articles[start:end]
        out_path = xml_base_path if idx == 0 else os.path.join(OUT_DIR, f"articles_{idx+1}.xml")
        
        print(f"[INFO] Writing XML file {idx+1}/{num_files}: {os.path.basename(out_path)} ({len(chunk)} items)")
        _write_rss_chunk(chunk, edate, rfc_pub_date, out_path, idx+1)

    print(f"[SUCCESS] Total articles extracted: {len(articles)} (XML contains {total_xml} items after exclusions)")
    print(f"[SUCCESS] Outputs saved to: {OUT_DIR}/")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", "-e", default=EID)
    parser.add_argument("--date", "-d", default=None)
    args = parser.parse_args()
    run(args.edition, args.date)
