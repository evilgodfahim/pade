#!/usr/bin/env python3
"""
Prothom Alo e-paper extractor — use exact xpath for full article extraction.

Behavior summary (strict):
- Fetch page (social-bot retries, fallback to FlareSolverr render).
- Locate the article container using the exact XPath: /html/body/div[1]/div/div[2]/div[2]
  If that XPath fails, fallback to known selectors (#textView or .articles_section_body_textview).
- The description written to JSON/CSV/XML is the full inner-HTML of that container (scripts and ad nodes stripped).
- Exclusion rule: exclude an article from XML ONLY if the first non-empty paragraph inside the main container
  contains the phrase "পৃষ্ঠার পর". If that phrase appears later or inside linked article, keep the article.
- Chunk XML files at 100 items.
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
    import lxml.html
    from lxml import etree as _etree
except Exception:
    lxml = None
    lxml_html = None

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
XML_CHUNK_SIZE = 100
EXCLUDE_PHRASE = "পৃষ্ঠার পর"
MAIN_ARTICLE_XPATH = "/html/body/div[1]/div/div[2]/div[2]"  # exact xpath requested

def now_bd() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BD_TZ))
    return datetime.now()

def today_str(override: Optional[str]) -> str:
    return override if override else now_bd().strftime("%d/%m/%Y")

def fetch_meta_as_social_bot(url: str, max_attempts: int = 3, attempt_delay: float = 0.6) -> Optional[str]:
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html"
    }
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 200 and r.text:
                return r.text
        except Exception:
            pass
        if attempt < max_attempts:
            time.sleep(attempt_delay)
    return None

def fs_request_get(url: str, flaresolverr_url: str, fs_timeout: int = 25) -> Optional[str]:
    payload = {"cmd": "request.get", "url": url, "maxTimeout": fs_timeout * 1000, "render": True}
    try:
        r = requests.post(f"{flaresolverr_url.rstrip('/')}/v1", json=payload, timeout=fs_timeout + 30)
        r.raise_for_status()
        data = r.json()
        sol = data.get("solution")
        if isinstance(sol, dict) and "response" in sol:
            return sol["response"]
        if "response" in data:
            return data["response"]
    except Exception:
        pass
    return None

def fetch_json(url: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def make_mindex_link(eid: str, edate: str, sedId: str, pgid: int, uemail: str) -> str:
    return (
        f"{BASE}/Home/MIndex?eid={eid}&edate={edate}&sedId={sedId}&pgid={pgid}"
        f"&isProductPanel=true&MagazineEdID=0&MagEdDate={edate}"
        f"&isIssueRefresh=False&uemail={uemail}"
    )

def make_mshare_link(orgid: str, eid: str, edate: str, sedId: str) -> str:
    return f"{BASE}/Home/MShareArticle?OrgId={orgid}&eid={eid}&imageview=0&epedate={edate}&sedId={sedId}"

def _remove_unwanted_nodes_lxml(el):
    # remove script/style and ad containers (common patterns)
    for bad in el.xpath('.//script|.//style'):
        bad.getparent().remove(bad)
    # id or class with 'ad' or 'div-gpt-ad'
    for bad in el.xpath('.//*[contains(translate(@id,"AD","ad"), "div-gpt-ad") or contains(translate(@class,"AD","ad"), "ad_inside_text_story") or contains(translate(@class,"AD","ad"), "ad_") or contains(translate(@class,"AD","ad"), "ad") ]'):
        try:
            bad.getparent().remove(bad)
        except Exception:
            pass

def _inner_html_from_lxml_element(el) -> str:
    # include text nodes and element children in order
    nodes = el.xpath('node()')
    parts = []
    for n in nodes:
        if isinstance(n, _etree._Element):
            parts.append(lxml.html.tostring(n, encoding='unicode', method='html'))
        else:
            parts.append(str(n))
    return ''.join(parts).strip()

def extract_full_container_html(html: str) -> Dict[str, str]:
    """
    Return dict:
      - title: best-effort title from og:title or <title>
      - description_html: full inner HTML of MAIN_ARTICLE_XPATH container (with ad/script blocks removed)
      - first_paragraph_text: first non-empty paragraph text (for exclusion check)
      - raw_html: original html
    """
    title = ""
    # title via og:title (last occurrence)
    og_title_matches = re.findall(r'property=["\']og:title["\']\s+content=(.*?)\s*/>', html, re.IGNORECASE)
    if og_title_matches:
        title = re.sub(r'^"?Common\s*:\s*', '', og_title_matches[-1]).strip('"\' ')
    if not title:
        soup = BeautifulSoup(html, "lxml")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

    description_html = ""
    first_para_text = ""

    # Try lxml xpath first (preferred)
    try:
        doc = lxml.html.fromstring(html)
        elems = doc.xpath(MAIN_ARTICLE_XPATH)
        if elems:
            el = elems[0]
            _remove_unwanted_nodes_lxml(el)
            description_html = _inner_html_from_lxml_element(el)
            # first non-empty paragraph inside this container
            p_nodes = el.xpath('.//p')
            for p in p_nodes:
                t = (p.text_content() or "").strip()
                if t:
                    first_para_text = re.sub(r'\s+', ' ', t)
                    break
            return {"title": title, "description_html": description_html, "first_paragraph_text": first_para_text, "raw_html": html}
    except Exception:
        pass

    # Fallback: try CSS selector(s) using BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one("#textView") or soup.select_one(".articles_section_body_textview") or soup.select_one("#article_textview")
    if container:
        # remove scripts and ad-like nodes
        for bad in container.select("script, style, .ad_inside_text_story, [id^=div-gpt-ad]"):
            bad.decompose()
        # get inner HTML
        description_html = ''.join(str(c) for c in container.contents).strip()
        # first non-empty paragraph
        for p in container.find_all("p"):
            t = p.get_text(separator=" ", strip=True)
            if t:
                first_para_text = re.sub(r'\s+', ' ', t)
                break

    return {"title": title, "description_html": description_html, "first_paragraph_text": first_para_text, "raw_html": html}

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
            # Use the full HTML description (already cleaned)
            desc_html = a.get("FullDescriptionHtml") or ""
            # Put inside CDATA
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

        stories = fetch_json(f"{BASE}/Home/getStoriesOnPage", params={"pageid": page_id}) or []
        for s in stories:
            orgid = s.get("OrgId")
            storyid = s.get("storyid")
            if not orgid:
                continue

            mshare = make_mshare_link(orgid, edition, edate, SEDID)
            mindex = make_mindex_link(edition, edate, SEDID, page_id, UEMAIL)

            # fetch: social bot (retries) then flaresolverr render
            rendered = fetch_meta_as_social_bot(mshare, max_attempts=4, attempt_delay=0.8)
            if not rendered or len(rendered) < 2000:
                rendered = fs_request_get(mshare, flaresolverr_url, fs_timeout=28) or rendered

            if not rendered:
                # keep empty but continue
                extracted = {"title": "", "description_html": "", "first_paragraph_text": "", "raw_html": ""}
            else:
                extracted = extract_full_container_html(rendered)

            # get image (last og:image) best-effort
            soup_meta = BeautifulSoup(rendered or "", "lxml")
            img_meta = ""
            og = soup_meta.find_all("meta", property="og:image")
            if og and og[-1].get("content"):
                img_meta = og[-1]["content"].strip()

            article = {
                "OrgId": orgid,
                "StoryId": storyid,
                "PageNo": page_no,
                "PageId": page_id,
                "PageTitle": page_title,
                "EditionId": edition,
                "EditionDate": edate,
                "Headline": extracted.get("title") or "",
                "Description": "",  # legacy plain-text description (kept empty since we must use full HTML)
                "ImageUrl": img_meta,
                "Link": mshare,
                "MIndexBase": mindex,
                "FullDescriptionHtml": extracted.get("description_html") or "",
                "FirstParagraphText": extracted.get("first_paragraph_text") or "",
            }
            articles.append(article)
            time.sleep(DELAY)

    # save JSON and CSV (CSV will contain Headline and a marker; Full HTML kept in JSON)
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(articles, jf, ensure_ascii=False, indent=2)

    # CSV: keep main fields, not full HTML
    fieldnames = ["OrgId", "StoryId", "PageNo", "PageId", "PageTitle", "EditionId", "EditionDate", "Headline", "ImageUrl", "Link", "MIndexBase", "FirstParagraphText"]
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()
        for a in articles:
            row = {k: a.get(k, "") for k in fieldnames}
            writer.writerow(row)

    # Exclude from XML ONLY if first non-empty paragraph inside main container contains EXCLUDE_PHRASE
    xml_articles = []
    excluded_count = 0
    for a in articles:
        first_para = (a.get("FirstParagraphText") or "").strip()
        if first_para and EXCLUDE_PHRASE in first_para:
            excluded_count += 1
            continue
        # If no container was found, keep the item but its FullDescriptionHtml may be empty
        xml_articles.append(a)

    if excluded_count:
        print(f"[INFO] Excluded {excluded_count} article(s) from XML because the main article's first line contained '{EXCLUDE_PHRASE}'")

    # Write XML chunked
    total_xml = len(xml_articles)
    if total_xml == 0:
        _write_rss_chunk([], edate, rfc_pub_date, xml_base_path, 1)
    else:
        num_files = (total_xml + XML_CHUNK_SIZE - 1) // XML_CHUNK_SIZE
        for idx in range(num_files):
            start = idx * XML_CHUNK_SIZE
            end = start + XML_CHUNK_SIZE
            chunk = xml_articles[start:end]
            out_path = xml_base_path if idx == 0 else os.path.join(OUT_DIR, f"articles_{idx+1}.xml")
            _write_rss_chunk(chunk, edate, rfc_pub_date, out_path, idx + 1)

    print(f"[SUCCESS] Extracted: {len(articles)} articles — XML contains: {total_xml} (after exclusions). Outputs in: {OUT_DIR}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", "-e", default=EID)
    parser.add_argument("--date", "-d", default=None)
    args = parser.parse_args()
    run(args.edition, args.date)
