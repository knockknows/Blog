# Playwright Scraper API with JWT

JWT 인증과 병렬 처리 기능을 갖춘 **순수 스크래핑 전문 API**입니다.

> **💡 아키텍처 설계:** FastAPI는 스크래핑만, N8N이 PostgreSQL 데이터 관리를 담당합니다.  
> 자세한 N8N 설정은 **[N8N_SETUP.md](N8N_SETUP.md)** 를 참고하세요!

## 주요 기능

- ✅ **JWT 인증**: Bearer 토큰 기반 보안
- ✅ **병렬 스크래핑**: 최대 10개 URL 동시 처리
- ✅ **Stealth 모드**: 봇 탐지 우회 기능
- ✅ **리소스 최적화**: Lifespan으로 브라우저 재사용
- ✅ **에러 핸들링**: 타임아웃 및 예외 처리
- ✅ **N8N 통합**: 같은 Docker 네트워크에서 원활한 통신

## 🎨 아키텍처

```
┌─────────────────────────────────────────┐
│              N8N Network                 │
│  ┌──────────┐         ┌──────────┐     │
│  │   N8N    │────────▶│PostgreSQL│     │
│  │          │  중복체크 │(테이블생성)│     │
│  └──────────┘  데이터저장 └──────────┘     │
│       │                                  │
│       │ (새 URL만)                       │
│       ▼                                  │
│  ┌──────────┐         ┌──────────┐     │
│  │ FastAPI  │────────▶│ Playwright│     │
│  │(스크래핑)│         │(브라우저) │     │
│  └──────────┘         └──────────┘     │
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
    "timeout": 30000,
    "stealth_mode": false
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
    "max_concurrent": 5,
    "stealth_mode": true
  }'
```

## N8N 통합 예시

### 워크플로우 구조

```
1. [초기 설정] PostgreSQL 노드 (한 번만 실행)
   → CREATE TABLE IF NOT EXISTS processed_urls...
   
2. [정기 실행] Schedule Trigger
   ↓
3. RSS Read (뉴스 URL 수집)
   ↓
4. PostgreSQL Query (중복 체크)
   → SELECT url FROM processed_urls WHERE url = ...
   ↓
5. Filter (중복 아닌 것만)
   ↓
6. HTTP Request → FastAPI (JWT 토큰 발급)
   ↓
7. HTTP Request → FastAPI (병렬 스크래핑)
   ↓
8. Google Sheets (저장)
   ↓
9. PostgreSQL Insert (처리된 URL 저장)
   → INSERT INTO processed_urls(url, title) VALUES...
```

### 1. JWT 토큰 발급 (HTTP Request 노드)

```
Method: POST
URL: http://fastapi:8000/login
Body:
{
  "username": "n8n_user",
  "password": "secure_password_123"
}
```

### 2. 병렬 스크래핑 (HTTP Request 노드)

```
Method: POST
URL: http://fastapi:8000/scrape/batch
Headers:
  Authorization: Bearer {{ $('Get JWT Token').item.json.access_token }}
Body:
{
  "urls": {{ $json.urls }},
  "max_concurrent": 5,
  "stealth_mode": true
}
```

### 3. PostgreSQL 중복 체크 (PostgreSQL 노드)

```sql
-- 중복 확인
SELECT EXISTS(
  SELECT 1 FROM processed_urls WHERE url = {{ $json.url }}
) as is_duplicate;

-- 처리된 URL 저장
INSERT INTO processed_urls (url, title, success)
VALUES ({{ $json.url }}, {{ $json.title }}, true)
ON CONFLICT (url) DO NOTHING;
```

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

2. **Stealth 모드 활용**
   - 봇 탐지 사이트에는 `stealth_mode: true` 설정
   - 약간의 성능 저하 있지만 안전성 향상

3. **브라우저 연결 재사용**
   - Lifespan으로 브라우저 연결 유지
   - 매 요청마다 연결 생성하지 않아 2-3배 빠름

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
