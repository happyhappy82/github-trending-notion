"""GitHub Trending → Notion DB 자동 수집기"""

import os
import re
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup
from notion_client import Client

GITHUB_TRENDING_URL = "https://github.com/trending"
KST = timezone(timedelta(hours=9))


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


def save_to_notion(repos):
    """크롤링한 레포 목록을 Notion DB에 저장한다."""
    notion = Client(auth=os.environ["NOTION_API_KEY"])
    database_id = os.environ["NOTION_DATABASE_ID"]
    today = datetime.now(KST).strftime("%Y-%m-%d")

    print(f"[{today}] {len(repos)}개 트렌딩 레포 저장 시작...")

    for repo in repos:
        lang = repo["language"] if repo["language"] in KNOWN_LANGUAGES else "Other"
        lang_prop = {"select": {"name": lang}} if lang else {"select": None}

        properties = {
            "Repo": {"title": [{"text": {"content": repo["repo"]}}]},
            "Description": {"rich_text": [{"text": {"content": repo["description"]}}]},
            "Language": lang_prop,
            "Stars": {"number": repo["stars"]},
            "Stars Today": {"number": repo["stars_today"]},
            "URL": {"url": repo["url"]},
            "Date": {"date": {"start": today}},
        }

        notion.pages.create(parent={"database_id": database_id}, properties=properties)
        print(f"  ✅ {repo['repo']} ({repo['stars']}⭐, +{repo['stars_today']} today)")

    print(f"[완료] {len(repos)}개 레포 Notion DB에 저장됨!")


if __name__ == "__main__":
    repos = fetch_trending()
    if repos:
        save_to_notion(repos)
    else:
        print("트렌딩 레포를 찾지 못했습니다.")
