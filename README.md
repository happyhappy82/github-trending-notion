# GitHub Trending → Notion

GitHub Trending 레포지토리를 매일 자동으로 크롤링하여 Notion DB에 저장합니다.

## Setup

### 1. Notion Integration 생성
1. https://www.notion.so/my-integrations 에서 새 Integration 생성
2. API Key 복사

### 2. Notion DB 연결
1. 저장할 Notion DB 페이지에서 ... → Connect to → 생성한 Integration 선택

### 3. GitHub Secrets 설정
Repository Settings → Secrets and variables → Actions 에서:
- `NOTION_API_KEY`: Notion Integration API Key
- `NOTION_DATABASE_ID`: Notion DB ID

### 4. 실행
- 자동: 매일 KST 09:00 실행
- 수동: Actions → Fetch GitHub Trending → Run workflow
