"""Meta AI Blog → Notion DB 자동 수집기

Meta AI 관련 블로그 RSS 피드를 수집한다.
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests as http_requests
from notion_client import Client
from scraper_utils import fetch_article_text, save_original_subpage

KST = timezone(timedelta(hours=9))
_today = datetime.now(timezone.utc).date()
_recent_dates = {(_today - timedelta(days=i)).isoformat() for i in range(2)}
SEEN_FILE = Path(__file__).parent / "seen_meta_ai.json"

RSS_FEEDS = [
    {"url": "https://research.facebook.com/feed/", "source_type": "Meta Research"},
    {"url": "https://code.facebook.com/posts/rss/", "source_type": "Meta Engineering"},
]


def fetch_rss(feed_url):
    """RSS 피드를 파싱하여 아이템 목록을 반환한다."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MetaAIBot/1.0)"}
    resp = http_requests.get(feed_url, headers=headers, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    items = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()

        iso_date = ""
        if pub_date:
            try:
                dt = parsedate_to_datetime(pub_date)
                iso_date = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        desc = item.findtext("description", "").strip()
        desc = re.sub(r'<[^>]+>', '', desc)[:500]

        if title:
            items.append({"title": title, "url": link, "date": iso_date, "description": desc})

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        title = entry.findtext("atom:title", "", ns).strip()
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        updated = entry.findtext("atom:updated", "", ns).strip()

        iso_date = updated[:10] if updated else ""

        content_text = entry.findtext("atom:content", "", ns).strip() or entry.findtext("atom:summary", "", ns).strip()
        desc = re.sub(r'<[^>]+>', '', content_text)[:500]

        if title:
            items.append({"title": title, "url": link, "date": iso_date, "description": desc})

    return items


def get_existing_urls(api_key, database_id, source_type):
    """Notion DB에서 기존 URL 목록을 가져온다."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    api_url = f"https://api.notion.com/v1/databases/{database_id}/query"
    body = {
        "filter": {
            "property": "소스유형",
            "select": {"equals": source_type},
        },
        "page_size": 100,
    }
    existing = set()

    while True:
        resp = http_requests.post(api_url, headers=headers, json=body, timeout=30)
        data = resp.json()
        for pg in data.get("results", []):
            url_prop = pg.get("properties", {}).get("URL", {})
            if url_prop.get("url"):
                existing.add(url_prop["url"])
        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]

    return existing


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return None


def save_seen(keys):
    SEEN_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    print(f"[날짜 필터] 최근 2일만 수집: {sorted(_recent_dates)}")
    seen = load_seen()
    if seen is None:
        print("[Bootstrap] seen 파일 없음, Notion DB에서 기존 URL 로드...")
        all_existing = set()
        for feed in RSS_FEEDS:
            urls = get_existing_urls(os.environ["NOTION_API_KEY"], os.environ["NOTION_DATABASE_ID"], feed["source_type"])
            all_existing.update(urls)
        seen = all_existing

    notion = Client(auth=os.environ["NOTION_API_KEY"])
    database_id = os.environ["NOTION_DATABASE_ID"]

    for feed in RSS_FEEDS:
        print(f"\n{'='*60}")
        print(f"RSS 피드 수집: {feed['source_type']}")
        print(f"URL: {feed['url']}")
        print(f"{'='*60}")

        try:
            items = fetch_rss(feed["url"])
            new_items = [i for i in items if i["url"] and i["url"] not in seen and i.get("date", "") in _recent_dates]
            print(f"[{feed['source_type']}] 전체 {len(items)}개 중 신규 {len(new_items)}개 저장 시작...")

            for item in new_items:
                properties = {
                    "제목": {"title": [{"text": {"content": item["title"][:2000]}}]},
                    "URL": {"url": item["url"]},
                    "소스유형": {"select": {"name": feed["source_type"]}},
                }
                article_text = fetch_article_text(item["url"])
                page = notion.pages.create(parent={"database_id": database_id}, properties=properties)
                save_original_subpage(notion, page["id"], item["title"], article_text, item["url"], feed["source_type"])
                seen.add(item["url"])
                print(f"  ✅ {item['title']} ({item['date']})")
        except Exception as e:
            print(f"  ❌ 에러: {e}")

    save_seen(seen)
    print(f"\n전체 완료! seen 파일 업데이트됨!")
