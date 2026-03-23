"""AI 뉴스 기사 자동 작성 모듈

Gemini API로 크롤링한 원문을 한국어 뉴스 기사로 변환하고
Notion DB 아이템의 하부 페이지로 저장한다.
"""

import json
import os
import re

import google.generativeai as genai
from notion_client import Client

_configured = False


def _ensure_configured():
    """Gemini API 설정을 확인하고 초기화한다."""
    global _configured
    if not _configured:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return False
        genai.configure(api_key=api_key)
        _configured = True
    return True


def write_article(notion_page_id, title, description="", source_name=""):
    """기사를 생성하고 Notion 하부 페이지로 저장하는 통합 함수.

    Args:
        notion_page_id: Notion DB 레코드의 page ID
        title: 원문 제목 (영어)
        description: 원문 요약/설명 (영어)
        source_name: 출처 이름 (예: "Product Hunt", "Hacker News")
    """
    if not _ensure_configured():
        print("  ⚠️ GEMINI_API_KEY 미설정, 기사 생성 건너뜀")
        return False

    try:
        article = _generate_article(title, description, source_name)
        if article:
            _save_to_notion(notion_page_id, article)
            print(f"  📝 기사 생성: {article['headline']}")
            return True
    except Exception as e:
        print(f"  ⚠️ 기사 생성 실패: {e}")
    return False


def _generate_article(title, description, source_name):
    """Gemini API로 한국어 뉴스 기사를 생성한다."""
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""당신은 한국의 AI 전문 뉴스 기자입니다. 아래 영문 뉴스 정보를 바탕으로 한국어 뉴스 기사를 작성하세요.

[원문 제목]
{title}

[원문 요약]
{description or '(없음)'}

[출처]
{source_name}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "headline": "한국어 뉴스 제목 (30자 내외, 핵심 정보 포함)",
  "body": ["문단1 텍스트", "문단2 텍스트", "문단3 텍스트", "문단4 텍스트"]
}}

규칙:
1. 객관적이고 전문적인 뉴스 톤으로 작성
2. AI/기술 전문 매체 수준의 품질
3. 4~5개 문단으로 구성, 각 문단 2-3문장
4. 첫 문단은 핵심 사실 요약 (리드)
5. 마지막 문단은 업계 전망이나 의의
6. 전문 용어는 한국어(영어) 병기
7. 추측이나 의견은 삼가고 사실 중심으로 서술"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    # Remove markdown code block wrapper if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    return json.loads(text)


def _save_to_notion(parent_page_id, article_data):
    """Notion DB 레코드의 하부 페이지로 기사를 저장한다."""
    notion = Client(auth=os.environ["NOTION_API_KEY"])

    children = []
    for paragraph in article_data["body"]:
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": paragraph[:2000]}}
                    ]
                },
            }
        )

    notion.pages.create(
        parent={"page_id": parent_page_id},
        properties={
            "title": {
                "title": [
                    {"text": {"content": article_data["headline"][:2000]}}
                ]
            }
        },
        children=children,
    )
