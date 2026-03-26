"""Shared utilities for article scraping and Notion block conversion."""

import trafilatura


def fetch_article_text(url, max_chars=8000):
    """Fetch article body text from a URL using trafilatura.

    Returns empty string on any failure (best-effort).
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded) or ""
        return text[:max_chars]
    except Exception:
        return ""


def text_to_notion_blocks(text):
    """Convert plain text to a list of Notion paragraph blocks.

    Splits on double newlines. Paragraphs over 2000 chars are further split.
    """
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    blocks = []

    for para in paragraphs:
        # Notion rich_text content limit is 2000 chars per text object
        chunks = [para[i:i + 1900] for i in range(0, len(para), 1900)]
        for chunk in chunks:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                },
            })

    return blocks


def save_original_subpage(notion, parent_page_id, title, text, url, source_name):
    """원문을 노션 하부 페이지(child page)로 저장한다."""
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

    if text:
        for i in range(0, len(text), 1900):
            chunk = text[i:i + 1900]
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
