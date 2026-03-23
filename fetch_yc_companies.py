"""Y Combinator Companies API → Notion DB 자동 수집기

YC Top Companies를 Algolia API로 수집한다.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests as http_requests
from notion_client import Client
from article_writer import write_article

KST = timezone(timedelta(hours=9))
SEEN_FILE = Path(__file__).parent / "seen_yc_companies.json"

# YC Algolia API 설정
YC_ALGOLIA_APP_ID = "45BWZJ1SGC"
YC_ALGOLIA_API_KEY = "NzllNTY5MzJiZGM2OTY2ZTQwMDEzOTNhYWZiZGRjODlhYzVkNjBmOGRjNzJiMWM4ZTU0ZDlhYTZjOTJiMjlhMWFuYWx5dGljc1RhZ3M9eWNkYyZyZXN0cmljdEluZGljZXM9WUNDb21wYW55X3Byb2R1Y3Rpb24lMkNZQ0NvbXBhbnlfQnlfTGF1bmNoX0RhdGVfcHJvZHVjdGlvbiZ0YWdGaWx0ZXJzPSU1QiUyMnljZGNfcHVibGljJTIyJTVE"
YC_API_URL = f"https://45bwzj1sgc-dsn.algolia.net/1/indexes/YCCompany_production/query"

SOURCE_TYPE = "Y Combinator"


def fetch_yc_companies(hits_per_page=50):
    """YC Algolia API에서 Top Companies를 가져온다."""
    headers = {
        "X-Algolia-Application-Id": YC_ALGOLIA_APP_ID,
        "X-Algolia-API-Key": YC_ALGOLIA_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "query": "",
        "filters": "top_company:true",
        "hitsPerPage": hits_per_page,
        "page": 0,
    }

    resp = http_requests.post(YC_API_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    companies = []
    for hit in data.get("hits", []):
        name = hit.get("name", "").strip()
        one_liner = hit.get("one_liner", "").strip()
        website = hit.get("website", "").strip()
        slug = hit.get("slug", "").strip()

        if not name:
            continue

        # 제목: "{name} - {one_liner}"
        title = f"{name} - {one_liner}" if one_liner else name

        # URL: website 또는 YC 프로필 URL
        url = website if website else f"https://www.ycombinator.com/companies/{slug}"

        companies.append({"title": title, "url": url, "name": name})

    return companies


def get_existing_titles(api_key, database_id, source_type):
    """Notion DB에서 기존 제목 목록을 가져온다 (company name 기반)."""
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
            title_prop = pg.get("properties", {}).get("제목", {})
            title_arr = title_prop.get("title", [])
            if title_arr:
                full_title = title_arr[0].get("text", {}).get("content", "")
                # "Name - one_liner" 형식에서 Name만 추출
                company_name = full_title.split(" - ")[0].strip()
                if company_name:
                    existing.add(company_name)
        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]

    return existing


def load_seen():
    """seen 파일에서 기존 company name 목록을 로드한다."""
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return None


def save_seen(keys):
    """seen 파일에 company name 목록을 저장한다."""
    SEEN_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2))


def save_to_notion(companies):
    """YC Companies를 Notion DB에 저장한다."""
    notion = Client(auth=os.environ["NOTION_API_KEY"])
    database_id = os.environ["NOTION_DATABASE_ID"]

    seen = load_seen()
    if seen is None:
        print("[Bootstrap] seen 파일 없음, Notion DB에서 기존 제목 로드...")
        seen = get_existing_titles(
            os.environ["NOTION_API_KEY"], database_id, SOURCE_TYPE
        )

    # company name 기반 중복 체크
    new_companies = [c for c in companies if c["name"] and c["name"] not in seen]

    print(f"[{SOURCE_TYPE}] 전체 {len(companies)}개 중 신규 {len(new_companies)}개 저장 시작...")

    for company in new_companies:
        properties = {
            "제목": {"title": [{"text": {"content": company["title"][:2000]}}]},
            "URL": {"url": company["url"]},
            "소스유형": {"select": {"name": SOURCE_TYPE}},
        }
        page = notion.pages.create(
            parent={"database_id": database_id}, properties=properties
        )
        # company["title"]에는 "Name - one_liner" 형식이 들어있음
        description = company["title"].split(" - ", 1)[1] if " - " in company["title"] else ""
        write_article(page["id"], company["name"], description, "Y Combinator")
        seen.add(company["name"])
        print(f"  ✅ {company['title']}")

    save_seen(seen)
    print(f"[{SOURCE_TYPE}] {len(new_companies)}개 신규 아이템 저장, seen 파일 업데이트됨!")


if __name__ == "__main__":
    print("=" * 60)
    print(f"YC Companies 수집: {SOURCE_TYPE}")
    print("=" * 60)

    try:
        companies = fetch_yc_companies()
        if companies:
            save_to_notion(companies)
        else:
            print("  YC Companies를 찾지 못했습니다.")
    except Exception as e:
        print(f"  ❌ 에러: {e}")
        raise
