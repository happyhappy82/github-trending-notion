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
        chunks = [para[i:i + 2000] for i in range(0, len(para), 2000)]
        for chunk in chunks:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                },
            })

    return blocks
