# Playwright Scraper API with JWT

JWT 인증과 병렬 처리 기능을 갖춘 **순수 스크래핑 전문 API**입니다.

> **💡 아키텍처 설계:** FastAPI는 스크래핑만, N8N이 PostgreSQL 데이터 관리를 담당합니다.  
> 자세한 N8N 설정은 **[N8N_SETUP.md](N8N_SETUP.md)** 를 참고하세요!

## 주요 기능

- ✅ **JWT 인증**: Bearer 토큰 기반 보안
- ✅ **병렬 스크래핑**: 최대 10개 URL 동시 처리
- ✅ **리소스 최적화**: Lifespan으로 브라우저 재사용
- ✅ **에러 핸들링**: 타임아웃 및 예외 처리
- ✅ **N8N 통합**: 같은 Docker 네트워크에서 원활한 통신

## 🎨 아키텍처

```
┌─────────────────────────────────────────┐
│              N8N Network                │
│  ┌──────────┐          ┌──────────┐     │
│  │   N8N    │────────▶ │PostgreSQL│     │
│  │          │  dedupe  │          │     │
│  └──────────┘          └──────────┘     │
│       │                                 │
│       │ (새 URL만)                       │
│       ▼                                 │
│  ┌──────────┐         ┌────────────┐    │
│  │ FastAPI  │────────▶│ Playwright │    │
│  │          │         │            │    │
│  └──────────┘         └────────────┘    │
└─────────────────────────────────────────┘
```

**역할 분리:**
- **FastAPI**: 브라우저 자동화, HTML 추출만
- **N8N**: PostgreSQL 테이블 생성, 중복 체크, 데이터 저장
- **Playwright**: 브라우저 서버

## 🚀 빠른 시작 (5분!)

> **⚠️ 필수:** N8N이 이미 실행 중이어야 합니다!

```bash
# 1. N8N 네트워크 확인
docker network ls | grep n8n

# 2. 환경 파일 생성 및 수정
cp env.example .env
nano .env  # SECRET_KEY, NETWORK_NAME 수정

# 3. 서비스 시작
docker compose up -d

# 4. 확인
curl http://localhost:8000/health
```

**자세한 설정은 [N8N_SETUP.md](N8N_SETUP.md) 참고!** 📖

## API 사용 방법

### 1. 로그인 (JWT 토큰 발급)

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "n8n_user",
    "password": "secure_password_123"
  }'
```

**응답 예시:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### 2. 단일 URL 스크래핑

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "wait_for": "networkidle",
    "timeout": 30000
  }'
```

### 3. 병렬 스크래핑 (여러 URL 동시 처리)

```bash
curl -X POST http://localhost:8000/scrape/batch \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      "https://example.com/page1",
      "https://example.com/page2"
    ],
    "max_concurrent": 5
  }'
```

## N8N 통합 예시

### 완전한 워크플로우 구조

```
1. Schedule Trigger               → 매시간 자동 실행
   ↓
2. RSS Read                       → 뉴스 URL 수집
   ↓
3. Code (Link 추출)               → URL을 '|||'로 구분한 문자열로 변환
   ↓
4. PostgreSQL Query (중복 체크)   → string_to_array로 중복 확인
   ↓
5. Code (중복 제거 링크 배열 생성) → 새 URL만 배열로 필터링
   ↓
6. If (URLs 확인)                 → 새 URL이 있는지 확인
   ↓
7. HTTP Request (JWT 발급)        → FastAPI 토큰 발급
   ↓
8. HTTP Request (병렬 스크래핑)   → 병렬 스크래핑 요청
   ↓
9. Filter (성공 필터링)           → success=true만 통과
   ↓
10. Loop Over Items               → 각 아이템 순회 처리
   ↓
11. WebpageContentExtractor       → HTML에서 텍스트 추출
   ↓
12. Code (헤더 포맷 정규화)       → Google Sheets 형식 맞춤
   ↓
13. Google Sheets (Append)        → 데이터 저장
   ↓
14. PostgreSQL Insert             → 처리 완료 URL 저장
```

### 1. Link 추출 (Code 노드)

```javascript
// RSS Read에서 받은 모든 URL을 '|||'로 연결한 문자열 생성
const urls = $input.all().map(item => item.json.link);
const urlString = urls.join('|||');

return { json: { urls: urlString } };
```

### 2. PostgreSQL 중복 체크

```sql
SELECT url FROM processed_urls 
WHERE url = ANY(string_to_array($1, '|||'))
AND success = true;
```

**파라미터:**
- `$1`: `{{ $json.urls }}`

### 3. 중복 제거 링크 배열 생성 (Code 노드)

```javascript
// PostgreSQL에서 조회한 이미 처리된 URL 목록
const processedUrls = $('중복 체크').all()
  .map(item => item.json.url);

// 원본 RSS 데이터
const allItems = $('RSS Read').all();

// 중복이 아닌 URL만 필터링하여 배열로 생성
const newUrls = allItems
  .filter(item => !processedUrls.includes(item.json.link))
  .map(item => item.json.link);

// HTTP Request (Batch) 노드가 받을 수 있는 형태로 반환
return {
  json: {
    urls: newUrls
  }
};
```

### 4. If (새 URL 확인)

**Condition:**
- Type: Array
- Value 1: `{{ $json.urls }}`
- Operation: is not empty

### 5. JWT 토큰 발급 (HTTP Request 노드)

```
Method: POST
URL: http://fastapi:8000/login
Body:
{
  "username": "n8n_user",
  "password": "secure_password_123"
}
```

### 6. 병렬 스크래핑 (HTTP Request 노드)

```
Method: POST
URL: http://fastapi:8000/scrape/batch
Headers:
  Authorization: Bearer {{ $json.access_token }}
Body Parameters:
  - urls: {{ $('중복 제거 링크 배열 생성').item.json.urls }}
  - max_concurrent: 5
  - wait_for: load
```

### 7. Filter (성공만 필터링)

**Condition:**
- Type: Boolean
- Value 1: `{{ $json.success }}`
- Operation: is true

### 8. Loop Over Items (Split in Batches)

배치 처리를 위해 각 아이템을 순회합니다.

### 9. WebpageContentExtractor

FastAPI에서 받은 HTML content를 텍스트로 추출합니다.

**Settings:**
- HTML: `={{ $json.content }}`

### 10. Google Sheet 헤더 포맷 정규화 (Code 노드)

```javascript
// 원본 데이터
const url = $('Loop Over Items').first().json.url;
const originalPubDate = $input.first().json.publishedTime;

// WebpageContentExtractor 결과
const extractedText = $input.first().json.textContent;
const extractedTitle = $input.first().json.title;

// HTTP Request 응답 데이터
const responseTime = $('Loop Over Items').first().json.response_time_ms;

// 현재 시각
const scrapedAt = $('Loop Over Items').first().json.scraped_at;

// Google Sheets의 헤더명과 정확히 일치하도록 설정
return [{
  json: {
    "제목": extractedTitle,
    "URL": url,
    "본문": extractedText,
    "발행일": originalPubDate,
    "스크랩 일시": scrapedAt,
    "응답 시간(ms)": responseTime
  }
}];
```

### 11. PostgreSQL 저장

```sql
INSERT INTO processed_urls (url, title, success)
VALUES ($1, $2, true)
ON CONFLICT (url) DO UPDATE SET
  title = EXCLUDED.title,
  success = true,
  processed_at = CURRENT_TIMESTAMP;
```

**파라미터:**
- `$1`: `{{ $json.URL }}`
- `$2`: `{{ $json['제목'] }}`

## 환경 변수

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SECRET_KEY` | JWT 토큰 암호화 키 (필수 변경!) | - |
| `PLAYWRIGHT_SERVER_URL` | Playwright 서버 주소 | `ws://playwright:3000` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT 토큰 만료 시간(분) | `30` |
| `NETWORK_NAME` | Docker 네트워크 이름 (N8N과 동일) | `n8n_network` |

## 성능 최적화 팁

1. **병렬 처리 개수 조정**
   - CPU 코어 수에 맞춰 `max_concurrent` 값 조정
   - 기본값 5개 권장

2. **브라우저 연결 재사용**
   - Lifespan으로 브라우저 연결 유지
   - 매 요청마다 연결 생성하지 않아 2-3배 빠름

3. **PostgreSQL 인덱스 활용**
   - url 검색 속도 향상을 위한 인덱스 생성
   ```sql
   CREATE INDEX idx_url ON processed_urls(url);
   CREATE INDEX idx_processed_at ON processed_urls(processed_at DESC);
   ```

## 트러블슈팅

### 1. 브라우저 연결 실패

```bash
# Playwright 서비스 재시작
docker compose restart playwright

# 로그 확인
docker compose logs playwright
```

### 2. N8N에서 FastAPI 연결 안 됨

**원인:** localhost 대신 컨테이너명 사용해야 함

```
❌ 잘못된 예: http://localhost:8000/scrape
✅ 올바른 예: http://fastapi:8000/scrape
              또는
              http://fastapi_scraper:8000/scrape
```

### 3. JWT 토큰 만료

```bash
# 새 토큰 발급
curl -X POST http://localhost:8000/login ...
```

### 4. 네트워크 연결 안 됨

```bash
# 네트워크 확인
docker network ls | grep n8n

# docker-compose.yml에서 NETWORK_NAME 수정
networks:
  n8n_network:
    external: true
    name: [실제_네트워크_이름]
```

### 5. PostgreSQL 중복 체크 느림

```sql
-- url 컬럼에 인덱스 생성 (검색 속도 10-100배 향상)
CREATE INDEX IF NOT EXISTS idx_url ON processed_urls(url);

-- 확인
\d processed_urls
```

## 개발 모드 실행

```bash
# 로컬 환경에서 실행
pip install -r requirements.txt
uvicorn main_enhanced:app --reload --host 0.0.0.0 --port 8000
```

## 📊 성능 비교

| 항목 | 순차 처리 | 병렬 처리 (5개) |
|-----|----------|----------------|
| 10개 URL | 약 30초 | 약 10초 |
| 50개 URL | 약 150초 | 약 35초 |
| 100개 URL | 약 300초 | 약 70초 |

**브라우저 재사용 효과:**
- 매번 새 연결: 요청당 2-3초 오버헤드
- Lifespan 재사용: 오버헤드 없음 (2-3배 빠름)

## 라이선스

MIT License

## 기여

버그 리포트 및 기능 제안은 Issues를 통해 알려주세요!
