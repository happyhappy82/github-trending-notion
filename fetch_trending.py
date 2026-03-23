"""GitHub Trending → Notion DB 자동 수집기"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from notion_client import Client
from article_writer import write_article

GITHUB_TRENDING_URL = "https://github.com/trending"
KST = timezone(timedelta(hours=9))
SEEN_FILE = Path(__file__).parent / "seen_trending.json"


def fetch_trending():
    """GitHub Trending 페이지를 크롤링하여 레포 목록을 반환한다."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GitHubTrendingBot/1.0)"}
    resp = requests.get(GITHUB_TRENDING_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    repos = []

    for article in soup.select("article.Box-row"):
        # 레포 이름
        h2 = article.select_one("h2 a")
        if not h2:
            continue
        repo_name = h2.get("href", "").strip("/")

        # 설명
        p = article.select_one("p")
        description = p.get_text(strip=True) if p else ""

        # 언어
        lang_span = article.select_one("[itemprop='programmingLanguage']")
        language = lang_span.get_text(strip=True) if lang_span else ""

        # 전체 스타
        star_links = article.select("a.Link--muted")
        total_stars = 0
        if star_links:
            star_text = star_links[0].get_text(strip=True).replace(",", "")
            total_stars = int(star_text) if star_text.isdigit() else 0

        # 오늘 스타
        stars_today = 0
        today_span = article.select_one("span.d-inline-block.float-sm-right")
        if today_span:
            match = re.search(r"([\d,]+)", today_span.get_text())
            if match:
                stars_today = int(match.group(1).replace(",", ""))

        repos.append({
            "repo": repo_name,
            "description": description[:2000],
            "language": language,
            "stars": total_stars,
            "stars_today": stars_today,
            "url": f"https://github.com/{repo_name}",
        })

    return repos


KNOWN_LANGUAGES = {
    "Python", "JavaScript", "TypeScript", "Rust", "Go",
    "Java", "C++", "C", "Swift", "Kotlin", "Ruby", "PHP",
}


def get_existing_repos(api_key, database_id):
    """Notion DB에서 기존 레포 URL 목록을 가져온다."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    api_url = f"https://api.notion.com/v1/databases/{database_id}/query"
    body = {
        "filter": {
            "property": "소스유형",
            "select": {"equals": "GitHub Trending"},
        },
        "page_size": 100,
    }
    existing = set()

    while True:
        resp = requests.post(api_url, headers=headers, json=body, timeout=30)
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
    """seen 파일에서 기존 레포 URL 목록을 로드한다."""
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return None


def save_seen(keys):
    """seen 파일에 레포 URL 목록을 저장한다."""
    SEEN_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2))


def save_to_notion(repos):
    """크롤링한 레포 목록을 Notion DB에 저장한다."""
    notion = Client(auth=os.environ["NOTION_API_KEY"])
    database_id = os.environ["NOTION_DATABASE_ID"]
    today = datetime.now(KST).strftime("%Y-%m-%d")

    seen = load_seen()
    if seen is None:
        print("[Bootstrap] seen 파일 없음, Notion DB에서 기존 레포 URL 로드...")
        seen = get_existing_repos(os.environ["NOTION_API_KEY"], database_id)

    new_repos = [r for r in repos if r["url"] and r["url"] not in seen]

    print(f"[GitHub Trending] 전체 {len(repos)}개 중 신규 {len(new_repos)}개 저장 시작...")

    for repo in new_repos:
        lang = repo["language"] if repo["language"] in KNOWN_LANGUAGES else "Other"
        lang_prop = {"select": {"name": lang}} if lang else {"select": None}

        properties = {
            "제목": {"title": [{"text": {"content": repo["repo"]}}]},
            "Language": lang_prop,
            "Stars": {"number": repo["stars"]},
            "Stars Today": {"number": repo["stars_today"]},
            "URL": {"url": repo["url"]},
            "소스유형": {"select": {"name": "GitHub Trending"}},
            "수집일": {"date": {"start": today}},
        }

        page = notion.pages.create(parent={"database_id": database_id}, properties=properties)
        write_article(page["id"], repo["repo"], repo.get("description", ""), "GitHub Trending")
        seen.add(repo["url"])
        print(f"  ✅ {repo['repo']} ({repo['stars']}⭐, +{repo['stars_today']} today)")

    save_seen(seen)
    print(f"[GitHub Trending] {len(new_repos)}개 신규 레포 저장, seen 파일 업데이트됨!")


if __name__ == "__main__":
    repos = fetch_trending()
    if repos:
        save_to_notion(repos)
    else:
        print("트렌딩 레포를 찾지 못했습니다.")
