# Playwright Scraper API with JWT & PostgreSQL

JWT 인증, 병렬 처리, PostgreSQL 중복 제거 기능을 갖춘 고급 웹 스크래퍼 API입니다.

> **💡 N8N 환경 최적화:** 이 프로젝트는 N8N과 함께 사용하도록 설계되었으며, N8N의 PostgreSQL을 공유합니다.  
> 자세한 설정은 **[N8N_SETUP.md](N8N_SETUP.md)** 를 참고하세요!

## 주요 기능

- ✅ **JWT 인증**: Bearer 토큰 기반 보안
- ✅ **병렬 스크래핑**: 최대 10개 URL 동시 처리
- ✅ **PostgreSQL 중복 제거**: URL 중복 자동 체크 및 저장 (N8N과 공유)
- ✅ **리소스 최적화**: Lifespan과 Connection Pooling 활용
- ✅ **에러 핸들링**: 타임아웃 및 예외 처리
- ✅ **N8N 통합**: 같은 Docker 네트워크에서 원활한 통신

## 🚀 빠른 시작 (5분!)

> **⚠️ 필수:** N8N과 PostgreSQL이 이미 실행 중이어야 합니다!

```bash
# 1. N8N 네트워크 확인
docker network ls | grep n8n

# 2. 환경 파일 생성 및 수정
cp env.example .env
nano .env  # SECRET_KEY, DATABASE_URL, NETWORK_NAME 수정

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
    "screenshot": false,
    "block_resources": false
  }'
```

### 3. 병렬 스크래핑 (여러 URL 동시 처리)

```bash
curl -X POST http://localhost:8000/scrape/batch \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      {
        "url": "https://example.com/page1",
        "wait_for": "networkidle"
      },
      {
        "url": "https://example.com/page2",
        "wait_for": "load"
      }
    ],
    "max_concurrent": 5,
    "check_duplicates": true
  }'
```

### 4. 처리된 URL 조회

```bash
curl -X GET "http://localhost:8000/processed-urls?limit=10&offset=0" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## N8N 통합 예시

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
  "check_duplicates": true
}
```

## PostgreSQL 직접 접속 (N8N과 공유)

```bash
# N8N의 PostgreSQL 컨테이너 접속
docker exec -it [postgres_container_name] psql -U postgres -d n8n

# 예시:
docker exec -it postgres psql -U postgres -d n8n
# 또는
docker exec -it n8n-postgres psql -U postgres -d n8n

# 테이블 확인
\dt

# 처리된 URL 조회
SELECT * FROM processed_urls ORDER BY processed_at DESC LIMIT 10;

# 중복 URL 확인
SELECT url, COUNT(*) as count 
FROM processed_urls 
GROUP BY url 
HAVING COUNT(*) > 1;
```

## 데이터베이스 스키마

```sql
CREATE TABLE processed_urls (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE
);
```

## 환경 변수

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SECRET_KEY` | JWT 토큰 암호화 키 (필수 변경!) | - |
| `DATABASE_URL` | PostgreSQL 연결 문자열 (N8N과 공유) | `postgresql://postgres:postgres@postgres:5432/n8n` |
| `PLAYWRIGHT_SERVER_URL` | Playwright 서버 주소 | `ws://playwright:3000` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT 토큰 만료 시간(분) | `30` |
| `NETWORK_NAME` | Docker 네트워크 이름 (N8N과 동일) | `n8n_network` |

## 성능 최적화 팁

1. **병렬 처리 개수 조정**
   - CPU 코어 수에 맞춰 `max_concurrent` 값 조정
   - 기본값 5개 권장

2. **리소스 차단 활용**
   - `block_resources: true` 설정으로 이미지/CSS/폰트 차단
   - 속도 30~50% 향상

3. **Connection Pool 크기 조정**
   - `main_enhanced.py`의 `create_pool()` 설정 변경
   - 동시 요청 수에 따라 `max_size` 조정

## 트러블슈팅

### 1. 브라우저 연결 실패

```bash
# Playwright 서비스 재시작
docker compose restart playwright
```

### 2. PostgreSQL 연결 실패 (N8N)

```bash
# N8N PostgreSQL 컨테이너 확인
docker ps | grep postgres

# 로그 확인
docker logs [postgres_container_name]

# FastAPI 로그에서 연결 오류 확인
docker compose logs fastapi | grep -i "database\|postgres"

# DATABASE_URL 확인
docker exec fastapi_scraper env | grep DATABASE_URL
```

**해결 방법:**
- `.env` 파일의 `DATABASE_URL`이 N8N PostgreSQL 정보와 일치하는지 확인
- N8N과 FastAPI가 같은 Docker 네트워크에 있는지 확인
- PostgreSQL 컨테이너명이 정확한지 확인

### 3. JWT 토큰 만료

```bash
# 새 토큰 발급
curl -X POST http://localhost:8000/login ...
```

## 개발 모드 실행

```bash
# 로컬 환경에서 실행
pip install -r requirements.txt
uvicorn main_enhanced:app --reload --host 0.0.0.0 --port 8000
```

## 라이선스

MIT License

## 기여

버그 리포트 및 기능 제안은 Issues를 통해 알려주세요!
