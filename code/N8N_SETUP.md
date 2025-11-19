# N8N 환경 통합 가이드

이 가이드는 **이미 실행 중인 N8N + PostgreSQL 환경**에 FastAPI 스크래퍼를 추가하는 방법을 설명해요.

> **💡 핵심 아키텍처:**  
> - **FastAPI**: 순수 스크래핑만 (PostgreSQL 의존성 없음)  
> - **N8N**: PostgreSQL 테이블 생성, 중복 체크, 데이터 저장 모두 담당

## 🚀 빠른 시작 (5분 안에 완료!)

```bash
# 1. N8N 네트워크 이름 확인
docker network ls | grep n8n

# 2. 환경 파일 생성
cp env.example .env

# 3. .env 파일 수정 (필수!)
nano .env
# - SECRET_KEY: openssl rand -hex 32 출력값 입력
# - NETWORK_NAME: 1번에서 확인한 네트워크 이름 입력

# 4. 서비스 시작
docker compose up -d

# 5. 확인
curl http://localhost:8000/health
```

**예상 응답 (성공):**
```json
{
  "status": "healthy",
  "browser": "connected",
  "note": "데이터 관리는 N8N PostgreSQL에서 수행됩니다."
}
```

---

## 🎯 전제 조건

✅ N8N이 Docker로 실행 중  
✅ PostgreSQL이 N8N과 함께 실행 중  
✅ N8N과 PostgreSQL이 같은 Docker 네트워크 공유  

## 📋 사전 확인 사항

### 1. N8N 네트워크 이름 확인

```bash
# N8N 컨테이너가 사용하는 네트워크 확인
docker inspect n8n | grep -A 10 Networks

# 또는 모든 네트워크 확인
docker network ls
```

일반적인 네트워크 이름:
- `n8n_network`
- `n8n_default`
- `n8n-network`

### 2. PostgreSQL 컨테이너 정보 확인

```bash
# PostgreSQL 컨테이너명 확인
docker ps | grep postgres

# PostgreSQL 연결 정보 확인 (N8N 환경변수에서)
docker exec n8n env | grep DB
```

필요한 정보:
- **컨테이너명**: 보통 `postgres`, `n8n-postgres`, `n8n_postgres` 등
- **데이터베이스명**: 보통 `n8n` 또는 `postgres`
- **사용자명**: 보통 `postgres`
- **비밀번호**: N8N 설정에서 확인

## 🔧 설정 방법

### 1단계: docker-compose.yml 확인

`docker-compose.yml` 파일에서 **네트워크 이름이 실제 N8N 네트워크와 일치하는지** 확인하세요:

```yaml
networks:
  n8n_network:
    external: true
    name: n8n_network  # ← 여기를 실제 네트워크 이름으로 변경!
```

예시:
```yaml
# N8N 네트워크가 "n8n_default"인 경우
networks:
  n8n_network:
    external: true
    name: n8n_default
```

### 2단계: 환경 변수 설정

`.env` 파일을 생성하고 실제 값으로 수정하세요:

```bash
# .env.example을 복사
cp env.example .env

# .env 파일 수정
nano .env
```

**중요: 다음 값들을 반드시 확인하고 수정하세요:**

```env
# SECRET_KEY는 반드시 변경!
SECRET_KEY=강력한-랜덤-키-여기에-입력-최소-32자

# N8N 네트워크 이름 (확인한 실제 이름)
NETWORK_NAME=n8n_network
```

**주의:** `DATABASE_URL`은 설정하지 않습니다! FastAPI는 PostgreSQL에 연결하지 않아요.

### 3단계: FastAPI 서비스 시작

```bash
# 서비스 시작 (Playwright + FastAPI만)
docker compose up -d

# 로그 확인
docker compose logs -f fastapi
```

### 4단계: 연결 확인

```bash
# 헬스 체크
curl http://localhost:8000/health
```

**예상 응답 (정상):**
```json
{
  "status": "healthy",
  "browser": "connected",
  "note": "데이터 관리는 N8N PostgreSQL에서 수행됩니다."
}
```

## 📊 N8N 워크플로우 설정

N8N에서 PostgreSQL 테이블 생성부터 데이터 관리까지 모두 수행해요.

### 전체 워크플로우 구조

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

### 1. PostgreSQL 테이블 생성 (초기 설정 - 한 번만 실행)

**노드:** PostgreSQL

```sql
CREATE TABLE IF NOT EXISTS processed_urls (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE
);

-- 인덱스 생성 (성능 향상)
CREATE INDEX IF NOT EXISTS idx_url ON processed_urls(url);
CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_urls(processed_at DESC);
```

**💡 팁:** 이 노드는 한 번만 실행하고 비활성화하세요!

### 2. Schedule Trigger

**설정:**
- Interval: 1 hour (매시간 실행)

### 3. RSS Read

**설정:**
- URL: RSS 피드 주소 (예: `https://news.sbs.co.kr/news/headlineRssFeed.do?plink=RSSREADER`)

### 4. Code (Link 추출)

**JavaScript 코드:**
```javascript
// RSS Read에서 받은 모든 URL을 '|||'로 연결한 문자열 생성
// PostgreSQL에서 string_to_array로 파싱할 수 있도록
const urls = $input.all().map(item => item.json.link);
const urlString = urls.join('|||');

return { json: { urls: urlString } };
```

**설명:**  
PostgreSQL의 `string_to_array` 함수를 사용하기 위해 URL 배열을 '|||'로 구분한 문자열로 변환합니다.

### 5. PostgreSQL Query (중복 체크)

**노드:** PostgreSQL

```sql
-- 이미 처리된(성공한) URL 조회
SELECT url FROM processed_urls 
WHERE url = ANY(string_to_array($1, '|||'))
AND success = true;
```

**설정:**
- Operation: Execute Query
- Query Replacement: `{{ $json.urls }}`

**Always Output Data:** ✅ 체크 (결과가 없어도 다음 노드로 진행)

**설명:**  
`string_to_array($1, '|||')`로 문자열을 배열로 변환한 후 `ANY()`를 사용하여 한 번의 쿼리로 모든 URL의 중복 여부를 확인합니다.

### 6. Code (중복 제거 링크 배열 생성)

**JavaScript 코드:**
```javascript
// PostgreSQL에서 조회한 이미 처리된 URL 목록
const processedUrls = $('중복 체크').all()
  .map(item => item.json.url);

// 원본 RSS 데이터 (모든 정보 포함)
const allItems = $('RSS Read').all();

// 중복이 아닌(DB에 없는) URL만 필터링하여 배열로 생성
const newUrls = allItems
  .filter(item => !processedUrls.includes(item.json.link))
  .map(item => item.json.link);

// HTTP Request (Batch) 노드가 한 번에 받을 수 있는 형태로 반환
return {
  json: {
    urls: newUrls
  }
};
```

**설명:**  
PostgreSQL 중복 체크 결과와 원본 RSS 데이터를 비교하여, 중복이 아닌 URL만 배열로 만듭니다.

### 7. If (새 URL 확인)

**Condition:**
- Type: Array
- Value 1: `{{ $json.urls }}`
- Operation: is not empty

**설명:**  
새로운 URL이 있을 때만 다음 단계(JWT 발급, 스크래핑)로 진행합니다. 모두 중복이면 워크플로우 종료.

### 8. HTTP Request (JWT 토큰 발급)

**설정:**
- Method: POST
- URL: `http://fastapi:8000/login`
- Send Body: ✅
- Body Content Type: JSON
- Body:
  ```json
  {
    "username": "n8n_user",
    "password": "secure_password_123"
  }
  ```

**출력:** `access_token` 저장됨

### 9. HTTP Request (병렬 스크래핑)

**설정:**
- Method: POST
- URL: `http://fastapi:8000/scrape/batch`
- Send Headers: ✅
- Header Parameters:
  - Name: `Authorization`
  - Value: `Bearer {{ $json.access_token }}`
- Send Body: ✅
- Body Parameters:
  - `urls`: `{{ $('중복 제거 링크 배열 생성').item.json.urls }}`
  - `max_concurrent`: `5`
  - `wait_for`: `load`

**설명:**  
JWT 토큰으로 인증하고, 중복 제거된 URL 배열을 FastAPI에 전송하여 병렬로 스크래핑합니다.

### 10. Filter (성공만 필터링)

**Condition:**
- Type: Boolean
- Value 1: `{{ $json.success }}`
- Operation: is true

**설명:**  
FastAPI는 실패한 요청도 에러를 내지 않고 `success: false` 응답을 주므로, 성공한 것만 필터링합니다.

### 11. Loop Over Items (Split in Batches)

**설정:**
- Batch Size: 1 (각 아이템을 하나씩 처리)
- Options > Reset: ✅ 체크 해제

**설명:**  
각 스크래핑 결과를 순회하면서 처리합니다.

### 12. WebpageContentExtractor

**설정:**
- HTML: `={{ $json.content }}`

**설명:**  
FastAPI에서 받은 HTML content를 텍스트로 추출합니다.

### 13. Code (Google Sheet 헤더 포맷 정규화)

**JavaScript 코드:**
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

// Google Sheets의 헤더명과 정확히 일치하도록 키 이름을 설정
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

**설명:**  
WebpageContentExtractor 결과와 원본 데이터를 결합하여 Google Sheets 헤더 형식에 맞게 정규화합니다.

### 14. Google Sheets (Append row in sheet)

**설정:**
- Operation: Append
- Document ID: 사용할 Google Sheets ID
- Sheet Name: 저장할 시트 이름
- Columns: Auto-map input data

**설명:**  
정규화된 데이터를 Google Sheets에 추가합니다.

### 15. PostgreSQL Insert (처리 완료 URL 저장)

**노드:** PostgreSQL

```sql
-- 처리 완료된 URL을 DB에 저장
INSERT INTO processed_urls (url, title, success)
VALUES ($1, $2, true)
ON CONFLICT (url) DO UPDATE SET
  title = EXCLUDED.title,
  success = true,
  processed_at = CURRENT_TIMESTAMP;
```

**설정:**
- Operation: Execute Query
- Query Replacement: `{{ $json.URL }},{{ $json['제목'] }}`

**설명:**  
Google Sheets 저장까지 성공했을 때만 DB에 기록합니다. 중간에 에러가 나면 DB에 기록되지 않으므로 다음 실행 때 재시도합니다.

## 🔍 트러블슈팅

### 문제 1: "network n8n_network not found"

**원인:** docker-compose.yml의 네트워크 이름이 틀렸어요.

**해결:**
```bash
# 실제 네트워크 이름 확인
docker network ls

# docker-compose.yml 수정
networks:
  n8n_network:
    external: true
    name: [실제_네트워크_이름]  # ← 이거 수정!
```

### 문제 2: N8N에서 FastAPI 연결 안 됨

**원인:** localhost 대신 컨테이너명을 사용해야 해요.

**해결:**
```
❌ 잘못된 예: http://localhost:8000/scrape
✅ 올바른 예: http://fastapi:8000/scrape
              또는
              http://fastapi_scraper:8000/scrape
```

### 문제 3: PostgreSQL 테이블이 없다는 오류

**원인:** N8N에서 테이블을 아직 생성하지 않았어요.

**해결:**
```sql
-- N8N PostgreSQL 노드에서 실행
CREATE TABLE IF NOT EXISTS processed_urls (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE
);
```

### 문제 4: FastAPI에서 "데이터베이스 연결 실패" 오류

**원인:** 없어요! FastAPI는 PostgreSQL에 연결하지 않습니다.

**확인:**
```bash
# FastAPI 로그 확인
docker compose logs fastapi

# DATABASE_URL이 없는지 확인
docker exec fastapi_scraper env | grep DATABASE_URL
# (아무것도 출력되지 않아야 정상!)
```

### 문제 5: N8N PostgreSQL 노드에서 중복 체크 느림

**해결:** 인덱스를 추가하세요.

```sql
-- url 컬럼에 인덱스 생성 (검색 속도 10-100배 향상)
CREATE INDEX IF NOT EXISTS idx_url ON processed_urls(url);

-- 확인
\d processed_urls
```

### 문제 6: Loop Over Items에서 무한 루프

**원인:** Reset 옵션이 체크되어 있어요.

**해결:**
- Loop Over Items 노드 설정
- Options > Reset: ✅ 체크 해제

### 문제 7: WebpageContentExtractor가 작동하지 않음

**원인:** 노드가 설치되지 않았어요.

**해결:**
```bash
# N8N에서 WebpageContentExtractor 노드 설치
# Settings > Community Nodes > Install
# Package: n8n-nodes-webpage-content-extractor
```

## 🎯 네트워크 구성도

```
┌─────────────────────────────────────────────────┐
│           N8N Docker Network                     │
│                                                   │
│  ┌──────────┐         ┌────────────┐            │
│  │   N8N    │────────▶│ PostgreSQL │            │
│  │          │  테이블생성 │            │            │
│  │          │  중복체크  │            │            │
│  │          │  데이터저장 │            │            │
│  └──────────┘         └────────────┘            │
│       │                                           │
│       │ (새 URL만)                                │
│       ▼                                           │
│  ┌──────────┐         ┌─────────────┐           │
│  │ FastAPI  │────────▶│ Playwright  │           │
│  │(스크래핑)│         │  (브라우저)  │           │
│  └──────────┘         └─────────────┘           │
│                                                   │
└─────────────────────────────────────────────────┘
                                                    
Host Machine:
  - N8N: http://localhost:5678
  - FastAPI: http://localhost:8000
  - Playwright: ws://localhost:3000
```

## 📋 체크리스트

배포 전 확인사항:

- [ ] N8N 네트워크 이름 확인 (`docker network ls`)
- [ ] `docker-compose.yml`에서 네트워크 이름 수정
- [ ] `.env` 파일 생성 및 SECRET_KEY 변경 (32자 이상)
- [ ] `docker compose up -d` 실행
- [ ] `/health` 엔드포인트로 연결 확인
- [ ] N8N PostgreSQL 노드에서 테이블 생성
- [ ] N8N HTTP Request 노드에서 컨테이너명 사용 확인 (http://fastapi:8000)
- [ ] 중복 체크 워크플로우 테스트
- [ ] 병렬 스크래핑 테스트
- [ ] WebpageContentExtractor 노드 설치 확인

## 🔐 보안 권장사항

1. **SECRET_KEY 생성**
   ```bash
   # 강력한 랜덤 키 생성
   openssl rand -hex 32
   ```

2. **기본 사용자 정보 변경**
   - `main_enhanced.py`에서 `FAKE_USERS_DB` 수정
   - 또는 실제 사용자 데이터베이스 연동

3. **PostgreSQL 보안**
   - N8N이 관리하므로 N8N 보안 가이드 따르기
   - 강력한 PostgreSQL 비밀번호 사용

## 💡 성능 최적화 팁

### 1. 대량 URL 처리 시

```sql
-- ❌ 느린 방법: 개별 체크
SELECT EXISTS(SELECT 1 FROM processed_urls WHERE url = $1)

-- ✅ 빠른 방법: 배치 체크
SELECT url FROM processed_urls WHERE url = ANY(string_to_array($1, '|||'))
```

### 2. PostgreSQL 인덱스 활용

```sql
-- url 검색 속도 향상
CREATE INDEX idx_url ON processed_urls(url);

-- 최근 처리 내역 조회 속도 향상
CREATE INDEX idx_processed_at ON processed_urls(processed_at DESC);
```

### 3. N8N 병렬 처리

- N8N Split In Batches 노드 활용
- FastAPI의 `max_concurrent` 조절 (CPU 코어 수에 맞춰)
- 기본값 5개 권장

## 📞 추가 도움이 필요하면

문제가 발생하면 다음 정보를 확인하세요:

```bash
# 1. 네트워크 상세 정보
docker network inspect [network_name]

# 2. 컨테이너 로그
docker compose logs fastapi
docker logs n8n

# 3. FastAPI 컨테이너 정보
docker inspect fastapi_scraper

# 4. 컨테이너 간 통신 테스트
docker exec fastapi_scraper ping playwright
docker exec n8n ping fastapi
```

이제 완벽한 N8N + FastAPI 통합 시스템이 완성되었어요! 🎉
