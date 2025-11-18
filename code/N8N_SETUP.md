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
1. [초기 설정] PostgreSQL 노드 - 테이블 생성
   → 한 번만 실행 후 비활성화
   
2. [정기 실행] Schedule Trigger
   ↓
3. RSS Read / HTTP Request (URL 수집)
   ↓
4. Code Node (URL 배열 생성)
   ↓
5. PostgreSQL Query (중복 체크)
   → SELECT url FROM processed_urls WHERE url IN (...)
   ↓
6. Code Node (중복 제외 필터링)
   ↓
7. HTTP Request → FastAPI Login (JWT 토큰)
   ↓
8. HTTP Request → FastAPI Scrape (병렬 스크래핑)
   ↓
9. Filter (성공한 것만)
   ↓
10. Google Sheets (저장)
    ↓
11. PostgreSQL Insert (처리 완료 URL 저장)
```

### 1. PostgreSQL 테이블 생성 (초기 설정)

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

### 2. 중복 URL 체크 (매번 실행)

**노드:** PostgreSQL

```sql
-- 방법 1: 개별 URL 체크 (Item 모드)
SELECT EXISTS(
  SELECT 1 FROM processed_urls WHERE url = $1
) as is_duplicate;
```

**파라미터:**
- `$1`: `{{ $json.url }}`

**방법 2: 대량 URL 체크 (Batch 모드 - 추천!)**

```sql
-- N8N Code 노드에서 먼저 URL 배열 생성
// Code 노드 (JavaScript)
const urls = items.map(item => item.json.url);
return [{ json: { urls } }];

-- PostgreSQL 노드
SELECT url FROM processed_urls 
WHERE url = ANY($1::text[]);
```

**파라미터:**
- `$1`: `{{ $json.urls }}`

### 3. 중복 필터링 (Code 노드)

```javascript
// 처리된 URL 목록 가져오기
const processedUrls = $('PostgreSQL 노드').all()
  .map(item => item.json.url);

// 원본 URL 목록
const allUrls = $('RSS Read').all();

// 중복 제외
const newUrls = allUrls.filter(item => 
  !processedUrls.includes(item.json.url)
);

return newUrls;
```

### 4. FastAPI JWT 토큰 발급

**노드:** HTTP Request

```
Method: POST
URL: http://fastapi:8000/login
Body (JSON):
{
  "username": "n8n_user",
  "password": "secure_password_123"
}
```

**출력:** `access_token` 저장됨

### 5. FastAPI 병렬 스크래핑

**노드:** HTTP Request

```
Method: POST
URL: http://fastapi:8000/scrape/batch
Headers:
  Authorization: Bearer {{ $('JWT Login').item.json.access_token }}
Body (JSON):
{
  "urls": {{ $json.urls }},
  "max_concurrent": 5,
  "stealth_mode": true
}
```

### 6. 처리된 URL 저장

**노드:** PostgreSQL

```sql
-- 개별 저장 (Item 모드)
INSERT INTO processed_urls (url, title, success)
VALUES ($1, $2, $3)
ON CONFLICT (url) DO UPDATE SET
  title = EXCLUDED.title,
  processed_at = CURRENT_TIMESTAMP,
  success = EXCLUDED.success;
```

**파라미터:**
- `$1`: `{{ $json.url }}`
- `$2`: `{{ $json.title }}`
- `$3`: `{{ $json.success }}`

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
SELECT url FROM processed_urls WHERE url = ANY($1::text[])
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
- 50-100개씩 묶어서 처리
- FastAPI의 `max_concurrent` 조절 (CPU 코어 수에 맞춰)

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

## 🎓 N8N 워크플로우 예시 (완전판)

전체 워크플로우 JSON은 다음과 같이 구성할 수 있어요:

```json
{
  "nodes": [
    {
      "name": "Schedule Trigger",
      "type": "n8n-nodes-base.scheduleTrigger",
      "parameters": {
        "rule": {
          "interval": [{ "field": "hours", "hoursInterval": 1 }]
        }
      }
    },
    {
      "name": "PostgreSQL - 테이블 생성",
      "type": "n8n-nodes-base.postgres",
      "parameters": {
        "operation": "executeQuery",
        "query": "CREATE TABLE IF NOT EXISTS processed_urls ..."
      },
      "disabled": true
    },
    {
      "name": "RSS",
      "type": "n8n-nodes-base.rssFeedRead",
      "parameters": {
        "url": "https://news.example.com/rss"
      }
    },
    {
      "name": "PostgreSQL - 중복 체크",
      "type": "n8n-nodes-base.postgres",
      "parameters": {
        "operation": "executeQuery",
        "query": "SELECT url FROM processed_urls WHERE url = ANY($1::text[])",
        "additionalFields": {
          "queryParameters": "={{ [$('Code').item.json.urls] }}"
        }
      }
    },
    {
      "name": "HTTP Request - JWT",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://fastapi:8000/login",
        "jsonParameters": true,
        "options": {
          "bodyContentType": "application/json"
        },
        "bodyParametersJson": "={ \"username\": \"n8n_user\", \"password\": \"secure_password_123\" }"
      }
    },
    {
      "name": "HTTP Request - Scrape",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "http://fastapi:8000/scrape/batch",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {
              "name": "Authorization",
              "value": "=Bearer {{ $('HTTP Request - JWT').item.json.access_token }}"
            }
          ]
        },
        "jsonParameters": true,
        "bodyParametersJson": "={ \"urls\": {{ $json.urls }}, \"max_concurrent\": 5 }"
      }
    },
    {
      "name": "PostgreSQL - 저장",
      "type": "n8n-nodes-base.postgres",
      "parameters": {
        "operation": "insert",
        "table": "processed_urls",
        "columns": "url, title, success",
        "additionalFields": {
          "onConflict": "doUpdate"
        }
      }
    }
  ]
}
```

이제 완벽한 N8N + FastAPI 통합 시스템이 완성되었어요! 🎉
