"""Model Release Notes → Notion DB 자동 수집기

help.openai.com/en/articles/9624314-model-release-notes 페이지를
Playwright로 크롤링하여 신규 모델 릴리즈노트만 Notion DB에 저장한다.
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

MODEL_NOTES_URL = "https://help.openai.com/en/articles/9624314-model-release-notes"
KST = timezone(timedelta(hours=9))
SOURCE_TYPE = "Model Release Notes"
SEEN_FILE = Path(__file__).parent / "seen_model_releases.json"

ENGLISH_MONTHS = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}

MONTH_ABBREV = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def parse_english_date(text):
    """'March 18, 2026' or 'Sep 23, 2025' → '2026-03-18'"""
    # Full month name
    m = re.search(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", text)
    if m:
        month = ENGLISH_MONTHS.get(m.group(1)) or MONTH_ABBREV.get(m.group(1))
        if month:
            return f"{m.group(3)}-{month}-{int(m.group(2)):02d}"
    return None


def fetch_model_releases():
    """Model Release Notes 페이지를 Playwright로 크롤링한다."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page.goto(MODEL_NOTES_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("article", timeout=30000)

        raw = page.evaluate("""
            () => {
                const article = document.querySelector('article');
                if (!article) return [];
                const results = [];

                const headings = article.querySelectorAll('h2');
                for (const h of headings) {
                    const text = h.textContent.trim();
                    if (!text) continue;
                    if (text === 'Was this article helpful?') continue;
                    if (text === 'Model Release Notes') continue;
                    if (text.includes('Need more help')) continue;
                    if (text.includes('Contact us')) continue;

                    const dateMatch = text.match(/\\(([^)]*\\d{4})\\)/);
                    const date = dateMatch ? dateMatch[1] : '';
                    const title = dateMatch
                        ? text.replace(/\\s*\\([^)]*\\d{4}\\)/, '').trim()
                        : text;

                    const id = h.id || '';
                    results.push({ title, date, anchor: id });
                }
                return results;
            }
        """)

        browser.close()

    releases = []
    for item in raw:
        iso_date = parse_english_date(item["date"]) if item["date"] else None
        url = MODEL_NOTES_URL
        if item["anchor"]:
            url += f"#{item['anchor']}"
        releases.append({
            "title": item["title"],
            "url": url,
            "date": iso_date or "",
        })

    return releases


def get_existing_titles(api_key, database_id):
    """Notion DB에서 기존 타이틀 목록을 가져온다."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    api_url = f"https://api.notion.com/v1/databases/{database_id}/query"
    body = {
        "filter": {
            "property": "소스유형",
            "select": {"equals": SOURCE_TYPE},
        },
        "page_size": 100,
    }
    existing = set()

    while True:
        resp = http_requests.post(api_url, headers=headers, json=body, timeout=30)
        data = resp.json()
        for pg in data.get("results", []):
            title_prop = pg.get("properties", {}).get("제목", {})
            title_arr = title_prop.get("title", [])
            if title_arr:
                existing.add(title_arr[0].get("text", {}).get("content", ""))
        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]

    return existing


def load_seen():
    """seen 파일에서 기존 제목 목록을 로드한다."""
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return None


def save_seen(keys):
    """seen 파일에 제목 목록을 저장한다."""
    SEEN_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2))


def save_to_notion(releases):
    """크롤링한 모델 릴리즈노트를 Notion DB에 저장한다."""
    notion = Client(auth=os.environ["NOTION_API_KEY"])
    database_id = os.environ["NOTION_DATABASE_ID"]
    today = datetime.now(KST).strftime("%Y-%m-%d")

    seen = load_seen()
    if seen is None:
        print("[Bootstrap] seen 파일 없음, Notion DB에서 기존 제목 로드...")
        seen = get_existing_titles(os.environ["NOTION_API_KEY"], database_id)

    new_releases = [r for r in releases if r["title"] not in seen]

    print(f"[{today}] 전체 {len(releases)}개 중 신규 {len(new_releases)}개 저장 시작...")

    for release in new_releases:
        properties = {
            "제목": {"title": [{"text": {"content": release["title"]}}]},
            "URL": {"url": release["url"]},
            "소스유형": {"select": {"name": SOURCE_TYPE}},
            "수집일": {"date": {"start": today}},
        }
        if release["date"]:
            properties["발행일"] = {"date": {"start": release["date"]}}
        page = notion.pages.create(
            parent={"database_id": database_id}, properties=properties
        )
        write_article(page["id"], release["title"], "", "Model Releases")
        seen.add(release["title"])
        print(f"  ✅ {release['title']} ({release['date']})")

    save_seen(seen)
    print(f"[완료] {len(new_releases)}개 신규 모델 릴리즈노트 저장, seen 파일 업데이트됨!")


if __name__ == "__main__":
    releases = fetch_model_releases()
    if releases:
        save_to_notion(releases)
    else:
        print("모델 릴리즈노트를 찾지 못했습니다.")
