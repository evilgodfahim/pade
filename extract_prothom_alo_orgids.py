#!/usr/bin/env python3
"""
Prothom Alo e-paper extractor — updated:
- Ensures full article is fetched (accounts for slow load; retries social-bot fetch briefly, falls back to FlareSolverr).
- Parses both main article and linked article sections.
- Excludes an article from XML ONLY when the main article's first non-empty line starts with the phrase "পৃষ্ঠার পর" (or contains it).
  If the phrase appears in linked article or later in the main article, the article is kept.
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
XML_CHUNK_SIZE = 100  # max articles per xml file
EXCLUDE_PHRASE = "পৃষ্ঠার পর"  # phrase used for exclusion only if it is the first non-empty line of main article

def now_bd() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BD_TZ))
    return datetime.now()

def today_str(override: Optional[str]) -> str:
    return override if override else now_bd().strftime("%d/%m/%Y")

def html_has_story_body(html: str) -> bool:
    return bool(re.search(r'id=["\']body["\']|class=["\']story_body["\']', html))

def fetch_meta_as_social_bot(url: str, max_attempts: int = 3, attempt_delay: float = 0.6) -> Optional[str]:
    """
    Try to fetch as facebookexternalhit (fast SSR). If initial response doesn't contain the story body (page loads slowly),
    retry a couple of times with a short delay. Caller can then fallback to FlareSolverr if necessary.
    """
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html"
    }
    print(f"[DEBUG] -> Spoofing Facebook Bot for: {url}")
    for attempt in range(1, max_attempts + 1):
        try:
            start = time.time()
            r = requests.get(url, headers=headers, timeout=10)
            elapsed = time.time() - start
            text = r.text if r.status_code == 200 else ""
            # if og:title exists and the page contains a story body, accept it.
            if r.status_code == 200 and ("og:title" in text or html_has_story_body(text)):
                print(f"[DEBUG] <- Facebook Bot fetch successful (attempt {attempt}) in {elapsed:.2f}s")
                return text
            else:
                print(f"[DEBUG] <- Facebook Bot attempt {attempt} incomplete (status={r.status_code}).")
        except Exception as e:
            print(f"[DEBUG] <- Facebook Bot fetch error on attempt {attempt}: {e}")
        if attempt < max_attempts:
            time.sleep(attempt_delay)
    return None

def fs_request_get(url: str, flaresolverr_url: str, fs_timeout: int = 20) -> Optional[str]:
    """FlareSolverr fallback with render=True to allow client-side content to be included."""
    python_timeout = fs_timeout + 25
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": fs_timeout * 1000,
        "render": True
    }

    print(f"[DEBUG] -> Sending to FlareSolverr Fallback: {url}")
    start_time = time.time()
    try:
        r = requests.post(f"{flaresolverr_url.rstrip('/')}/v1", json=payload, timeout=python_timeout)
        elapsed = time.time() - start_time
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "unknown")
        print(f"[DEBUG] <- FlareSolverr returned '{status}' in {elapsed:.2f}s.")
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
    """
    Returns dict with: title, description (combined main+linked if present), image (last og:image found).
    Also keeps the raw html for additional checks (e.g. start-line exclusion).
    """
    soup = BeautifulSoup(html, "lxml")
    title = ""

    # Prefer og:title matches (take the last article-specific one)
    title_matches = re.findall(r'property=["\']og:title["\']\s+content=(.*?)\s*/>', html, re.IGNORECASE)
    if title_matches:
        raw_title = title_matches[-1].strip()
        title = re.sub(r'^"?Common\s*:\s*', '', raw_title, flags=re.IGNORECASE).strip('"\' ')

    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Extract main article description (collect paragraphs inside #body / .story_body)
    main_desc = ""
    body_div = soup.find(id="body") or soup.find(class_="story_body")
    if body_div:
        # join paragraph texts preserving order; strip empty ones
        p_texts = [p.get_text(separator=" ", strip=True) for p in body_div.find_all("p")]
        p_texts = [t for t in p_texts if t]
        main_desc = "\n\n".join(p_texts)

    # Extract linked article description (if present)
    linked_desc = ""
    linked_div = soup.find(id="divlinkedstorybody") or soup.select_one("#divlinkedstory .divlinkedstorybody")
    if linked_div:
        lp_texts = [p.get_text(separator=" ", strip=True) for p in linked_div.find_all("p")]
        lp_texts = [t for t in lp_texts if t]
        linked_desc = "\n\n".join(lp_texts)

    # Combined description: main + (separator + linked) if linked exists
    description = main_desc
    if linked_desc:
        description = (main_desc + "\n\n---linked---\n\n" + linked_desc) if main_desc else linked_desc

    # Get last og:image or twitter:image
    image = ""
    og_imgs = soup.find_all("meta", property="og:image") or soup.find_all("meta", attrs={"name": "twitter:image"})
    if og_imgs and og_imgs[-1].get("content"):
        image = og_imgs[-1].get("content").strip()

    return {"title": title, "description": description, "image": image, "raw_html": html}

def main_article_starts_with_phrase(html: str, phrase: str) -> bool:
    """
    Check whether the main article's first non-empty paragraph contains the phrase.
    - Only inspects the MAIN article (div#body or .story_body).
    - Returns True only when the FIRST non-empty line in the main article contains the phrase.
    """
    if not html:
        return False
    soup = BeautifulSoup(html, "lxml")
    body_div = soup.find(id="body") or soup.find(class_="story_body")
    if not body_div:
        return False
    # iterate through direct paragraphs in the body in document order
    for el in body_div.find_all(["p", "div"]):
        text = el.get_text(separator=" ", strip=True)
        if not text:
            continue
        # Normalize whitespace
        text_norm = re.sub(r'\s+', ' ', text).strip()
        # If phrase appears in this first non-empty line -> exclude
        if phrase in text_norm:
            return True
        # if first non-empty line does not contain phrase => don't exclude
        return False
    return False

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
            desc_text = a.get("Description") or ""
            desc_html = f'<img src="{_escape_xml(img_url)}" /><br/><br/>' if img_url else ""
            # keep description escaped inside CDATA to avoid XML breakage
            desc_html += _escape_xml(desc_text)

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

            # Hybrid fetch: try social bot with retries, then FlareSolverr render if necessary.
            rendered = fetch_meta_as_social_bot(mshare, max_attempts=3, attempt_delay=0.6)
            if not rendered or not html_has_story_body(rendered):
                rendered = fs_request_get(mshare, flaresolverr_url, fs_timeout=22)

            if not rendered:
                print(f"[WARNING] Content missing for OrgId={orgid}. Saving empty metadata.")
                content = {"title": "", "description": "", "image": "", "raw_html": ""}
            else:
                content = extract_meta_from_html(rendered)
                print(f"[DEBUG] Meta extracted -> Title: '{(content.get('title') or '')[:40]}...' | Image: {'Yes' if content.get('image') else 'No'}")

            # Build article record
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
                "ImageUrl": content.get("image", ""),
                "Link": mshare,
                "MIndexBase": mindex,
                "raw_html": content.get("raw_html", "")
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

    # --- Filter articles for XML using the new rule:
    # Exclude ONLY if the main article's first non-empty line contains EXCLUDE_PHRASE.
    xml_articles = []
    excluded_count = 0
    for a in articles:
        raw_html = a.get("raw_html") or ""
        if main_article_starts_with_phrase(raw_html, EXCLUDE_PHRASE):
            excluded_count += 1
            # keep in JSON/CSV but exclude from XML
            continue
        xml_articles.append(a)

    if excluded_count:
        print(f"[INFO] Excluding {excluded_count} article(s) from XML because the main article starts with '{EXCLUDE_PHRASE}'.")

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
        if idx == 0:
            out_path = xml_base_path
        else:
            out_path = os.path.join(OUT_DIR, f"articles_{idx+1}.xml")
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
