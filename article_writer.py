"""AI 뉴스 기사 자동 작성 모듈

Gemini API로 크롤링한 원문을 한국어 뉴스 기사로 변환하고
Notion DB 아이템의 하부 페이지로 저장한다.

하부 페이지 구조:
  1. 원문 (Original) - 원문 그대로 저장
  2. 뉴스 기사 (Article) - Gemini가 생성한 한국어 기사
  3. 팩트체크 (Verification) - 원문 vs 기사 비교 검증 결과
"""

import json
import os
import re

import requests as http_requests
from bs4 import BeautifulSoup
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


def _fetch_article_content(url):
    """URL에서 기사 본문 텍스트를 추출한다."""
    if not url:
        return ""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = http_requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        article = soup.find("article") or soup.find("main") or soup.body
        if not article:
            return ""

        paragraphs = []
        for p in article.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 30:
                paragraphs.append(text)

        content = "\n\n".join(paragraphs)
        return content[:5000]
    except Exception as e:
        print(f"  ⚠️ 원문 가져오기 실패: {e}")
        return ""


def write_article(notion_page_id, title, description="", source_name="", url=""):
    """기사를 생성하고 Notion 하부 페이지 3개로 저장하는 통합 함수.

    하부 페이지 구조:
      1. 📄 원문 - 원문 콘텐츠 그대로
      2. 📝 뉴스 기사 - Gemini가 생성한 한국어 기사
      3. ✅ 팩트체크 - 원문 vs 기사 비교 검증 결과
    """
    if not _ensure_configured():
        print("  ⚠️ GEMINI_API_KEY 미설정, 기사 생성 건너뜀")
        return False

    try:
        notion = Client(auth=os.environ["NOTION_API_KEY"])

        # 1. 원문 수집
        original_content = _fetch_article_content(url)

        # 하위 페이지 1: 원문 저장
        _save_original_to_notion(notion, notion_page_id, title, original_content, url, source_name)
        print(f"  📄 원문 저장 완료")

        # 2. Gemini로 한국어 기사 생성
        article = _generate_article(title, description, source_name, original_content)
        if not article:
            print("  ⚠️ 기사 생성 실패")
            return False

        # 하위 페이지 2: 뉴스 기사 저장
        _save_article_to_notion(notion, notion_page_id, article)
        print(f"  📝 기사 생성: {article['headline']}")

        # 3. 팩트체크 검증
        verification = _verify_article(title, original_content, article)

        # 하위 페이지 3: 팩트체크 결과 저장
        _save_verification_to_notion(notion, notion_page_id, verification)
        print(f"  ✅ 팩트체크: {verification['result']}")

        return True
    except Exception as e:
        print(f"  ⚠️ 기사 생성 실패: {e}")
    return False


def _generate_article(title, description, source_name, original_content=""):
    """Gemini API로 한국어 뉴스 기사를 생성한다."""
    content_section = f"""
[원문 내용]
{original_content}""" if original_content else ""

    prompt = f"""당신은 한국 최고 수준의 AI/기술 전문 뉴스 기자입니다. 아래 영문 뉴스 정보를 바탕으로 심층 한국어 뉴스 기사를 작성하세요.

[원문 제목]
{title}

[원문 요약]
{description or '(없음)'}
{content_section}
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
        model="gemini-2.5-flash",  # 기사 작성: Flash (빠르고 저렴)
        contents=prompt,
    )
    text = response.text.strip()

    # Remove markdown code block wrapper if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    return json.loads(text)


def _verify_article(title, original_content, article):
    """원문과 생성된 기사를 비교하여 팩트체크한다."""
    if not original_content:
        return {
            "result": "⚠️ 검증 불가",
            "score": 0,
            "issues": ["원문을 가져올 수 없어 검증 불가"],
            "details": "원문 콘텐츠가 없어 팩트체크를 수행할 수 없습니다.",
        }

    article_text = "\n\n".join(article["body"])

    prompt = f"""당신은 뉴스 팩트체커입니다. 아래 원문(영어)과 이를 바탕으로 생성된 한국어 기사를 비교하여 정확성을 검증하세요.

[원문 제목]
{title}

[원문 내용]
{original_content}

[생성된 한국어 기사 제목]
{article["headline"]}

[생성된 한국어 기사 본문]
{article_text}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "result": "✅ 통과" 또는 "⚠️ 주의" 또는 "❌ 오류 발견",
  "score": 1~10 (정확도 점수, 10이 완벽),
  "issues": ["발견된 문제1", "발견된 문제2"],
  "details": "전체 검증 요약 (3~5문장)"
}}

검증 항목:
1. 할루시네이션: 원문에 없는 사실이 기사에 추가되었는가?
2. 사실 누락: 원문의 핵심 정보가 기사에서 빠졌는가?
3. 수치 오류: 금액, 날짜, 비율, 건수 등 수치가 정확한가?
4. 고유명사 오류: 기업명, 인물명, 제품명 등이 정확한가?
5. 맥락 왜곡: 원문의 맥락이 기사에서 왜곡되었는가?
6. 번역 오류: 영어→한국어 번역 과정에서 의미가 변질되었는가?

판정 기준:
- ✅ 통과 (8~10점): 모든 사실이 정확하고 핵심 정보가 빠짐없이 포함됨
- ⚠️ 주의 (5~7점): 경미한 누락이나 표현 차이가 있으나 사실 왜곡은 없음
- ❌ 오류 발견 (1~4점): 사실 오류, 할루시네이션, 심각한 누락이 발견됨

issues 배열이 비어있으면 빈 배열 []로 응답하세요."""

    response = _client.models.generate_content(
        model="gemini-2.5-pro",  # 팩트체크: Pro (정확도 우선)
        contents=prompt,
    )
    text = response.text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "result": "⚠️ 검증 실패",
            "score": 0,
            "issues": ["검증 응답 파싱 실패"],
            "details": text[:500],
        }


def _save_original_to_notion(notion, parent_page_id, title, content, url, source_name):
    """원문을 Notion 하부 페이지로 저장한다."""
    children = []

    # 출처 정보
    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "🔗"},
            "rich_text": [{"type": "text", "text": {"content": f"출처: {source_name}\nURL: {url or '없음'}"}}],
        },
    })

    if content:
        # 원문을 2000자 단위로 나눠서 저장
        for i in range(0, len(content), 2000):
            chunk = content[i:i + 2000]
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                },
            })
    else:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "(원문을 가져올 수 없었습니다)"}}]
            },
        })

    notion.pages.create(
        parent={"page_id": parent_page_id},
        properties={
            "title": {"title": [{"text": {"content": f"📄 원문: {title[:100]}"}}]}
        },
        children=children,
    )


def _save_article_to_notion(notion, parent_page_id, article_data):
    """Gemini 생성 기사를 Notion 하부 페이지로 저장한다."""
    children = []
    for paragraph in article_data["body"]:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": paragraph[:2000]}}]
            },
        })

    notion.pages.create(
        parent={"page_id": parent_page_id},
        properties={
            "title": {"title": [{"text": {"content": f"📝 {article_data['headline'][:100]}"}}]}
        },
        children=children,
    )


def _save_verification_to_notion(notion, parent_page_id, verification):
    """팩트체크 결과를 Notion 하부 페이지로 저장한다."""
    result = verification.get("result", "검증 실패")
    score = verification.get("score", 0)
    issues = verification.get("issues", [])
    details = verification.get("details", "")

    children = []

    # 판정 결과 callout
    emoji = "✅" if score >= 8 else "⚠️" if score >= 5 else "❌"
    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": [{"type": "text", "text": {"content": f"판정: {result}\n정확도: {score}/10"}}],
        },
    })

    # 상세 요약
    if details:
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "검증 요약"}}]
            },
        })
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": details[:2000]}}]
            },
        })

    # 발견된 문제
    if issues:
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "발견된 문제"}}]
            },
        })
        for issue in issues:
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": issue[:2000]}}]
                },
            })
    else:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": "발견된 문제 없음"}}]
            },
        })

    notion.pages.create(
        parent={"page_id": parent_page_id},
        properties={
            "title": {"title": [{"text": {"content": f"{emoji} 팩트체크: {result} ({score}/10)"}}]}
        },
        children=children,
    )
