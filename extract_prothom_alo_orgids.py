#!/usr/bin/env python3
"""
Extract Prothom Alo e-paper articles (OrgId + rendered full article via FlareSolverr).
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
DELAY = float(os.getenv("DELAY", "0.5"))
OUT_DIR = "output"
BD_TZ = "Asia/Dhaka"


def now_bd() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BD_TZ))
    return datetime.now()


def today_str(override: Optional[str]) -> str:
    return override if override else now_bd().strftime("%d/%m/%Y")


def fs_request_get(url: str, flaresolverr_url: str, timeout: int = 60) -> Optional[str]:
    """
    Use FlareSolverr to fetch a URL and return rendered HTML as string.
    Expects FlareSolverr accessible at flaresolverr_url + "/v1".
    """
    payload = {
        "cmd": "request.get",
        "url": url,
        # ask FlareSolverr to render JS (best-effort)
        "maxTimeout": timeout * 1000,
        "render": True,
        # optionally you can set 'waitFor' or 'returnOnlyCookies' depending on FlareSolverr version
    }
    try:
        r = requests.post(f"{flaresolverr_url.rstrip('/')}/v1", json=payload, timeout=timeout + 10)
        r.raise_for_status()
        data = r.json()
        # try to extract rendered HTML content
        if isinstance(data, dict):
            # FlareSolverr returns solution.response in some versions
            sol = data.get("solution")
            if isinstance(sol, dict) and "response" in sol:
                return sol["response"]
            if "response" in data:
                return data["response"]
        return None
    except Exception as e:
        print(f"FlareSolverr fetch failed for {url}: {e}", file=sys.stderr)
        return None


def fetch_json(url: str, params: dict = None, timeout: int = 20) -> Optional[dict]:
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


def extract_article_from_html(html: str) -> Dict[str, str]:
    """Return {'title':..., 'html':..., 'text':...} best-effort from rendered HTML."""
    soup = BeautifulSoup(html, "lxml")

    # title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Try several common selectors. fallback to body.
    selectors = [
        "article",
        ".article",
        ".article-body",
        ".article-content",
        ".story-content",
        "#article",
        "#main",
        ".content"
    ]
    content_el = None
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            content_el = el
            break

    if content_el is None:
        # try main container
        content_el = soup.body

    html_blob = content_el.decode_contents() if content_el else ""
    text = content_el.get_text(separator="\n").strip() if content_el else soup.get_text(separator="\n").strip()
    return {"title": title, "html": html_blob, "text": text}


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

    # Prepare outputs (overwrite each run)
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "articles.json")
    csv_path = os.path.join(OUT_DIR, "articles.csv")
    xml_path = os.path.join(OUT_DIR, "articles.xml")

    articles = []

    # iterate pages -> stories
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

            # Fetch rendered article via FlareSolverr (wait for JS)
            rendered = fs_request_get(mshare, flaresolverr_url, timeout=60)
            if not rendered:
                print(f"Rendered fetch failed for OrgId={orgid}, URL={mshare}", file=sys.stderr)
                content = {"title": "", "html": "", "text": ""}
            else:
                content = extract_article_from_html(rendered)

            article = {
                "OrgId": orgid,
                "StoryId": storyid,
                "PageNo": page_no,
                "PageId": page_id,
                "PageTitle": page_title,
                "EditionId": edition,
                "EditionDate": edate,
                "MShareArticle": mshare,
                "MIndexBase": mindex,
                "Title": content["title"],
                "FullHtml": content["html"],
                "FullText": content["text"]
            }
            articles.append(article)
            time.sleep(DELAY)

    # Write JSON (overwrite)
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(articles, jf, ensure_ascii=False, indent=2)

    # Write CSV (overwrite). FullHtml is kept out of CSV to avoid huge fields; include FullText instead.
    if articles:
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            fieldnames = ["OrgId", "StoryId", "PageNo", "PageId", "PageTitle", "EditionId", "EditionDate", "MShareArticle", "MIndexBase", "Title", "FullText"]
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            for a in articles:
                row = {k: a.get(k, "") for k in fieldnames}
                writer.writerow(row)
    else:
        open(csv_path, "w").close()

    # Write XML (overwrite). FullHtml is escaped; use plain ElementTree-like building via string for CDATA-ish readability.
    with open(xml_path, "w", encoding="utf-8") as xf:
        xf.write('<?xml version="1.0" encoding="utf-8"?>\n')
        xf.write(f'<Epaper date="{edate}">\n')
        for a in articles:
            xf.write("  <Article>\n")
            for k, v in a.items():
                if v is None:
                    v = ""
                # wrap large html in <![CDATA[ ... ]]> to preserve markup
                if k == "FullHtml":
                    xf.write(f"    <{k}><![CDATA[{v}]]></{k}>\n")
                else:
                    safe = str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    xf.write(f"    <{k}>{safe}</{k}>\n")
            xf.write("  </Article>\n")
        xf.write("</Epaper>\n")

    print(json_path)
    print(csv_path)
    print(xml_path)
    print(f"Total articles: {len(articles)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract Prothom Alo e-paper articles (rendered via FlareSolverr).")
    parser.add_argument("--edition", "-e", default=EID)
    parser.add_argument("--date", "-d", default=None, help="DD/MM/YYYY (default BD today)")
    args = parser.parse_args()
    run(args.edition, args.date)
