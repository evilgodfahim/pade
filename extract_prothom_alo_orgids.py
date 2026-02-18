#!/usr/bin/env python3
"""
Prothom Alo e-paper extractor — improved image resolution and dedupe.
- removes leading "ঢাকা সংস্করণ : " from titles
- avoids duplicate items by link or normalized title
- picks highest-resolution image candidate (srcset, data-src, og:image, img src)
"""
import os
import sys
import time
import json
import csv
import re
from datetime import datetime
from email.utils import format_datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin

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
XML_CHUNK_SIZE = 100
EXCLUDE_PHRASE = "পৃষ্ঠার পর"

# remove leading variants of 'ঢাকা সংস্করণ : '
_DHAKA_PREFIX_RE = re.compile(r"^\s*ঢাকা\s*সংস্করণ\s*[:\-]?\s*", flags=re.IGNORECASE)


def now_bd() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(BD_TZ))
    return datetime.now()


def today_str(override: Optional[str]) -> str:
    return override if override else now_bd().strftime("%d/%m/%Y")


def fetch_meta_as_social_bot(url: str) -> Optional[str]:
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200 and "og:title" in r.text:
            return r.text
        return None
    except Exception:
        return None


def fs_request_get(url: str, flaresolverr_url: str, fs_timeout: int = 15) -> Optional[str]:
    python_timeout = fs_timeout + 20
    payload = {"cmd": "request.get", "url": url, "maxTimeout": fs_timeout * 1000, "render": True}
    try:
        r = requests.post(f"{flaresolverr_url.rstrip('/')}/v1", json=payload, timeout=python_timeout)
        r.raise_for_status()
        data = r.json()
        sol = data.get("solution") or data
        if isinstance(sol, dict):
            return sol.get("response")
        return None
    except Exception:
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


# ---------------- image helpers ----------------

def _parse_srcset(srcset: str) -> List[Tuple[str, int]]:
    items: List[Tuple[str, int]] = []
    for part in srcset.split(","):
        p = part.strip()
        if not p:
            continue
        pieces = p.split()
        url = pieces[0]
        w = 0
        if len(pieces) > 1:
            try:
                if pieces[1].endswith("w"):
                    w = int(pieces[1][:-1])
                elif pieces[1].endswith("x"):
                    w = int(float(pieces[1][:-1]) * 100)
            except Exception:
                w = 0
        items.append((url, w))
    return items


def _normalize_image_url(url: str) -> str:
    if not url:
        return url
    # protocol-relative
    if url.startswith("//"):
        url = "https:" + url
    # remove common size query params
    url = re.sub(r'([?&])w=\d+(&|$)', r'\1', url)
    url = re.sub(r'([?&])width=\d+(&|$)', r'\1', url)
    # remove suffixes like _200x200 before extension
    url = re.sub(r'(_\d+x\d+)(\.\w{2,5})$', r'\2', url)
    # remove ".thumbnail" style suffix
    url = re.sub(r'(\.thumbnail)(\.\w{2,5})$', r'\2', url)
    # heuristics
    url = url.replace("/thumb/", "/").replace("/thumbnail/", "/")
    return url


def _head_content_length(url: str, timeout: int = 6) -> Tuple[int, str]:
    try:
        h = requests.head(url, allow_redirects=True, timeout=timeout)
        if h.status_code >= 400:
            return 0, ""
        cl = h.headers.get("Content-Length")
        ct = h.headers.get("Content-Type", "")
        size = int(cl) if cl and cl.isdigit() else 0
        return size, ct
    except Exception:
        return 0, ""


def extract_meta_from_html(html: str, page_url: Optional[str] = None) -> Dict[str, str]:
    """
    Returns dict: {"title":..., "description":..., "image":...}
    Image selection:
     - gather candidates from og:image, link rel=image_src, img srcset, data-src/data-original, src
     - normalize and resolve relative URLs (page_url)
     - probe HEAD for Content-Length and prefer largest image that is an image MIME type
     - fallback to first candidate if probing fails
    """
    soup = BeautifulSoup(html, "lxml")
    title = ""

    # try robust og:title capture (handles broken attributes)
    title_matches = re.findall(r'property=["\']og:title["\']\s+content=(.*?)\s*/?>', html, re.IGNORECASE)
    if title_matches:
        raw_title = title_matches[-1].strip()
        title = re.sub(r'^\"?Common\s*:\s*', '', raw_title, flags=re.IGNORECASE).strip('"\' ')

    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    # description
    desc = ""
    og_descs = soup.find_all("meta", property="og:description") or soup.find_all("meta", attrs={"name": "twitter:description"})
    if og_descs and og_descs[-1].get("content"):
        desc = og_descs[-1].get("content").strip()

    candidates: List[str] = []

    # og:image
    og_imgs = soup.find_all("meta", property="og:image") or soup.find_all("meta", attrs={"name": "twitter:image"})
    if og_imgs and og_imgs[-1].get("content"):
        candidates.append(og_imgs[-1].get("content").strip())

    # link rel=image_src
    link_img = soup.find("link", rel="image_src")
    if link_img and link_img.get("href"):
        candidates.append(link_img.get("href").strip())

    # img tags
    for img in soup.find_all("img"):
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            for u, w in _parse_srcset(srcset):
                candidates.append(u)
            continue
        # lazy attributes
        for attr in ("data-original", "data-src", "data-lazy", "data-defer-src", "data-echo"):
            val = img.get(attr)
            if val:
                candidates.append(val.strip())
                break
        # fallback src
        src = img.get("src")
        if src:
            candidates.append(src.strip())

    # resolve and normalize
    resolved: List[str] = []
    for c in candidates:
        if not c:
            continue
        if c.startswith("//"):
            c = "https:" + c
        if page_url and not re.match(r'^https?:', c):
            c = urljoin(page_url, c)
        c = _normalize_image_url(c)
        if c and c not in resolved:
            resolved.append(c)

    if not resolved:
        return {"title": title, "description": desc, "image": ""}

    # probe HEAD and pick largest image (as proxy for resolution)
    best_url = resolved[0]
    best_size = 0
    for u in resolved:
        size, ctype = _head_content_length(u)
        if ctype and "image" not in ctype.lower():
            continue
        if size > best_size:
            best_size = size
            best_url = u

    return {"title": title, "description": desc, "image": best_url}


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

    pages = fetch_json(f"{BASE}/Home/GetAllpages", params={"editionid": edition, "editiondate": edate})
    if not pages:
        print("[ERROR] No pages returned. Exiting.", file=sys.stderr)
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "articles.json")
    csv_path = os.path.join(OUT_DIR, "articles.csv")
    xml_base_path = os.path.join(OUT_DIR, "articles.xml")

    articles: List[Dict] = []
    seen_links = set()
    seen_titles = set()

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

            rendered = fetch_meta_as_social_bot(mshare)
            if not rendered:
                rendered = fs_request_get(mshare, flaresolverr_url, fs_timeout=15)

            if not rendered:
                content = {"title": "", "description": "", "image": ""}
            else:
                # pass page_url so relative image URLs and srcset entries resolve correctly
                content = extract_meta_from_html(rendered, page_url=mshare)

            raw_title = content.get("title") or ""
            cleaned_title = _DHAKA_PREFIX_RE.sub("", raw_title).strip()

            article = {
                "OrgId": orgid,
                "StoryId": storyid,
                "PageNo": page_no,
                "PageId": page_id,
                "PageTitle": page_title,
                "EditionId": edition,
                "EditionDate": edate,
                "Headline": cleaned_title,
                "Description": content.get("description", ""),
                "ImageUrl": content.get("image", ""),
                "Link": mshare,
                "MIndexBase": mindex
            }

            norm_link = (article.get("Link") or "").strip()
            norm_title = re.sub(r"\s+", " ", (article.get("Headline") or "").strip()).lower()

            if norm_link in seen_links or (norm_title and norm_title in seen_titles):
                # duplicate; skip
                pass
            else:
                articles.append(article)
                if norm_link:
                    seen_links.add(norm_link)
                if norm_title:
                    seen_titles.add(norm_title)

            time.sleep(DELAY)

    # write JSON
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(articles, jf, ensure_ascii=False, indent=2)

    # write CSV
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

    # filter exclusions
    xml_articles = []
    for a in articles:
        desc = (a.get("Description") or "")
        if EXCLUDE_PHRASE in desc:
            continue
        xml_articles.append(a)

    total_xml = len(xml_articles)
    if total_xml == 0:
        _write_rss_chunk([], edate, rfc_pub_date, xml_base_path, 1)
        return

    num_files = (total_xml + XML_CHUNK_SIZE - 1) // XML_CHUNK_SIZE
    for idx in range(num_files):
        start = idx * XML_CHUNK_SIZE
        end = start + XML_CHUNK_SIZE
        chunk = xml_articles[start:end]
        out_path = xml_base_path if idx == 0 else os.path.join(OUT_DIR, f"articles_{idx+1}.xml")
        _write_rss_chunk(chunk, edate, rfc_pub_date, out_path, idx + 1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", "-e", default=EID)
    parser.add_argument("--date", "-d", default=None)
    args = parser.parse_args()
    run(args.edition, args.date)