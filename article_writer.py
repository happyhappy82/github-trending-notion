"""AI 뉴스 기사 자동 작성 모듈

Gemini API로 크롤링한 원문을 한국어 뉴스 기사로 변환하고
Notion DB 아이템의 하부 페이지로 저장한다.
"""

import json
import os
import re

from google import genai
from notion_client import Client

_client = None


def _ensure_configured():
    """Gemini API 설정을 확인하고 초기화한다."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return False
        _client = genai.Client(api_key=api_key)
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
    prompt = f"""당신은 한국 최고 수준의 AI/기술 전문 뉴스 기자입니다. 아래 영문 뉴스 정보를 바탕으로 심층 한국어 뉴스 기사를 작성하세요.

[원문 제목]
{title}

[원문 요약]
{description or '(없음)'}

[출처]
{source_name}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "headline": "한국어 뉴스 제목 (25~35자, 핵심 사실과 수치 포함)",
  "body": ["문단1", "문단2", "문단3", "문단4", "문단5", "문단6"]
}}

기사 작성 규칙:
1. 반드시 6~7개 문단으로 구성한다. 각 문단은 3~4문장, 150~250자 분량이어야 한다.
2. 문단 구조를 반드시 따른다:
   - 1문단(리드): 핵심 사실을 육하원칙(누가, 무엇을, 언제, 어디서)으로 압축 요약
   - 2문단(핵심 내용): 발표/사건의 구체적 내용, 핵심 조항이나 기능을 상세히 설명
   - 3문단(배경/맥락): 이 사건이 왜 중요한지, 어떤 맥락에서 나왔는지 설명
   - 4문단(구체적 수치/사례): 관련 수치, 데이터, 사례, 비교 대상 등 구체적 팩트 제시
   - 5문단(다양한 시각): 찬성/반대 의견, 업계/전문가 반응, 이해관계자 입장 소개
   - 6문단(전망): 향후 일정, 예상되는 파급효과, 업계에 미칠 영향
3. 구체적인 고유명사(기업명, 인물명, 법안명, 제품명)를 적극 사용한다.
4. 수치와 데이터(금액, 비율, 날짜, 건수)가 있으면 반드시 포함한다.
5. 전문 용어는 한국어(영어) 병기한다. 예: 대규모 언어모델(LLM), 생성형 AI(Generative AI)
6. 추측이나 의견은 삼가고 사실 중심으로 서술하되, 전문가 의견은 인용 형태로 포함할 수 있다.
7. 각 문단의 첫 문장은 해당 문단의 핵심을 담아야 한다(역피라미드 구조).
8. 단정적 표현보다 '~으로 분석된다', '~할 것으로 전망된다' 등 객관적 표현을 사용한다."""

    response = _client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
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
