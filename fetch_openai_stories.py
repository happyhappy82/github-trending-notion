"""OpenAI Stories → Notion DB 자동 수집기

OpenAI Stories 페이지를 Playwright로 크롤링하여
신규 스토리만 Notion DB에 저장한다.
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests as http_requests
from playwright.sync_api import sync_playwright
from notion_client import Client
from article_writer import write_article

OPENAI_STORIES_URL = "https://openai.com/ko-KR/stories/"
KST = timezone(timedelta(hours=9))
SEEN_FILE = Path(__file__).parent / "seen_openai_stories.json"

KOREAN_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")


def parse_korean_date(text):
    """'2026년 2월 4일' → '2026-02-04'"""
    m = KOREAN_DATE_RE.search(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def fetch_stories():
    """OpenAI Stories 페이지를 Playwright로 크롤링하여 스토리 목록을 반환한다."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page.goto(OPENAI_STORIES_URL, wait_until="domcontentloaded", timeout=60000)
        # 스토리 카드가 로드될 때까지 대기
        page.wait_for_selector('a[href*="/index/"]', timeout=30000)

        # "더 로딩하기" 버튼 반복 클릭하여 모든 스토리 로드
        for _ in range(20):
            try:
                btn = page.locator('button:has-text("더 로딩하기")')
                if btn.count() > 0 and btn.is_visible(timeout=3000):
                    btn.click()
                    page.wait_for_timeout(2000)
                else:
                    break
            except Exception:
                break

        # JavaScript로 스토리 데이터 추출
        raw = page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="/index/"]');
                const results = [];
                const seen = new Set();

                links.forEach(link => {
                    const href = link.getAttribute('href');
                    if (!href || seen.has(href)) return;
                    seen.add(href);

                    const timeEl = link.querySelector('time');
                    if (!timeEl) return;

                    const parts = link.innerText.trim().split('\\n').filter(s => s.trim());
                    if (parts.length < 1) return;

                    const title = parts[0].trim();
                    const category = parts.length > 1 ? parts[1].trim() : '';
                    const date = timeEl.textContent.trim();

                    const fullUrl = href.startsWith('/')
                        ? 'https://openai.com' + href
                        : href;

                    results.push({ title, url: fullUrl, category, date });
                });

                return results;
            }
        """)

        browser.close()

    stories = []
    for item in raw:
        iso_date = parse_korean_date(item["date"])
        stories.append({
            "title": item["title"],
            "url": item["url"],
            "category": item["category"],
            "date": iso_date or "",
        })

    return stories


def get_existing_urls(api_key, database_id):
    """Notion DB에서 'OpenAI Stories' 소스유형의 기존 URL 목록을 가져온다."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    api_url = f"https://api.notion.com/v1/databases/{database_id}/query"
    body = {
        "filter": {
            "property": "소스유형",
            "select": {"equals": "OpenAI Stories"},
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
    """seen 파일에서 기존 URL 목록을 로드한다."""
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return None


def save_seen(keys):
    """seen 파일에 URL 목록을 저장한다."""
    SEEN_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2))


def save_to_notion(stories):
    """크롤링한 스토리를 Notion DB에 저장한다 (중복 제외)."""
    notion = Client(auth=os.environ["NOTION_API_KEY"])
    database_id = os.environ["NOTION_DATABASE_ID"]

    seen = load_seen()
    if seen is None:
        print("[Bootstrap] seen 파일 없음, Notion DB에서 기존 URL 로드...")
        seen = get_existing_urls(os.environ["NOTION_API_KEY"], database_id)

    new_stories = [s for s in stories if s["url"] not in seen]

    print(f"전체 {len(stories)}개 중 신규 {len(new_stories)}개 저장 시작...")

    for story in new_stories:
        properties = {
            "제목": {"title": [{"text": {"content": story["title"]}}]},
            "URL": {"url": story["url"]},
            "소스유형": {"select": {"name": "OpenAI Stories"}},
        }
        page = notion.pages.create(
            parent={"database_id": database_id}, properties=properties
        )
        write_article(page["id"], story["title"], story.get("category", ""), "OpenAI Stories")
        seen.add(story["url"])
        print(f"  ✅ {story['title']} ({story['category']}, {story['date']})")

    save_seen(seen)
    print(f"[완료] {len(new_stories)}개 신규 스토리 저장, seen 파일 업데이트됨!")


if __name__ == "__main__":
    stories = fetch_stories()
    if stories:
        save_to_notion(stories)
    else:
        print("스토리를 찾지 못했습니다.")
