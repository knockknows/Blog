# 🚀 빠른 시작 가이드

## 📌 중요: N8N 환경 통합

이 가이드는 **이미 실행 중인 N8N + PostgreSQL 환경**에 FastAPI를 추가하는 방법이에요.
자세한 설정은 **[N8N_SETUP.md](N8N_SETUP.md)** 를 참고하세요!

## 패키지 버전 (최신)

```
FastAPI     : 0.121.1
Uvicorn     : 0.38.0
Playwright  : 1.56.0
Pydantic    : 2.9.2
asyncpg     : 0.30.0
```

## 설치 및 실행

### ⚡ 빠른 시작 (N8N 환경)

```bash
# 1. N8N 네트워크 이름 확인
docker network ls
# 출력 예: n8n_network, n8n_default 등

# 2. PostgreSQL 정보 확인
docker ps | grep postgres
# 컨테이너명 확인: postgres, n8n-postgres 등

# 3. docker-compose.yml 수정
# networks 섹션의 name을 실제 네트워크명으로 변경!
nano docker-compose.yml

# 4. 환경 변수 설정
cp env.example .env
nano .env
# DATABASE_URL을 N8N PostgreSQL 정보로 수정!
# SECRET_KEY를 반드시 변경!

# 5. 서비스 시작
docker-compose up -d

# 6. 확인
curl http://localhost:8000/health
```

### 📋 상세 단계별 가이드

#### 1️⃣ N8N 네트워크 확인

```bash
# N8N이 사용하는 네트워크 확인
docker inspect n8n | grep -A 5 Networks

# 또는
docker network ls | grep n8n
```

#### 2️⃣ docker-compose.yml 수정

```yaml
networks:
  n8n_network:
    external: true
    name: n8n_default  # ← 실제 네트워크명으로 변경!
```

#### 3️⃣ .env 파일 설정

```bash
cp env.example .env
nano .env
```

**필수 수정 항목:**
```env
# 강력한 랜덤 키로 변경!
SECRET_KEY=openssl_rand_hex_32_output_here

# N8N PostgreSQL 정보로 변경!
DATABASE_URL=postgresql://postgres:your_password@postgres:5432/n8n
```

**SECRET_KEY 생성:**
```bash
openssl rand -hex 32
```

#### 4️⃣ 서비스 시작

```bash
# FastAPI + Playwright만 시작 (PostgreSQL은 N8N 것 사용)
docker-compose up -d

# 로그 확인
docker-compose logs -f fastapi
```

## API 테스트

### 1. 헬스 체크

```bash
curl http://localhost:8000/health
```

**예상 응답:**
```json
{
  "status": "healthy",
  "browser": "connected",
  "database": "connected",
  "optimization": "lifespan + connection pooling"
}
```

### 2. JWT 토큰 발급

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "n8n_user",
    "password": "secure_password_123"
  }'
```

**예상 응답:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### 3. 단일 URL 스크래핑

```bash
TOKEN="여기에_발급받은_토큰_입력"

curl -X POST http://localhost:8000/scrape \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "wait_for": "networkidle",
    "timeout": 30000
  }'
```

### 4. 병렬 스크래핑 (여러 URL 동시)

```bash
curl -X POST http://localhost:8000/scrape/batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      {"url": "https://example.com/page1"},
      {"url": "https://example.com/page2"},
      {"url": "https://example.com/page3"}
    ],
    "max_concurrent": 5,
    "check_duplicates": true
  }'
```

### 5. 처리된 URL 조회

```bash
curl -X GET "http://localhost:8000/processed-urls?limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

## PostgreSQL 직접 접속

```bash
# Docker 환경
docker exec -it scraper_postgres psql -U postgres -d scraper_db

# 로컬 환경
psql -U postgres -d scraper_db

# 테이블 확인
\dt

# 데이터 조회
SELECT * FROM processed_urls ORDER BY processed_at DESC LIMIT 10;

# 중복 URL 확인
SELECT url, COUNT(*) FROM processed_urls GROUP BY url HAVING COUNT(*) > 1;
```

## N8N 연동 예시

### 워크플로우 구성

```
1. Schedule Trigger (매시간)
   ↓
2. HTTP Request: POST /login
   Body: {"username": "n8n_user", "password": "secure_password_123"}
   ↓
3. RSS Read: 뉴스 피드
   ↓
4. Code: URL 변환
   ↓
5. HTTP Request: POST /scrape/batch
   Headers: Authorization: Bearer {{ $('2').item.json.access_token }}
   Body: {
     "urls": {{ $json.urls }},
     "max_concurrent": 5,
     "check_duplicates": true
   }
   ↓
6. Filter: is_duplicate = false
   ↓
7. Google Sheets: 저장
```

## 문제 해결

### 브라우저 연결 안 됨

```bash
docker-compose restart playwright
docker-compose logs playwright
```

### PostgreSQL 연결 안 됨

```bash
docker-compose restart postgres
docker-compose logs postgres
```

### JWT 토큰 만료

```bash
# 새 토큰 발급 (유효기간 30분)
curl -X POST http://localhost:8000/login ...
```

### 메모리 부족

```bash
# docker-compose.yml 수정
services:
  fastapi:
    deploy:
      resources:
        limits:
          memory: 2G
```

## 성능 최적화 팁

1. **max_concurrent 조정**: CPU 코어 수에 맞춰 3~10 사이로 설정
2. **block_resources 활성화**: 이미지/CSS 차단으로 30~50% 속도 향상
3. **Connection Pool 크기**: 동시 요청 수에 맞춰 조정 (기본 10)
4. **timeout 설정**: 느린 사이트는 60000ms(60초)로 증가

## 모니터링

```bash
# 실시간 로그
docker-compose logs -f --tail=100 fastapi

# 리소스 사용량
docker stats

# PostgreSQL 상태
docker exec -it scraper_postgres pg_stat_activity
```

## 백업

```bash
# PostgreSQL 백업
docker exec scraper_postgres pg_dump -U postgres scraper_db > backup.sql

# 복원
docker exec -i scraper_postgres psql -U postgres scraper_db < backup.sql
```

## 유용한 명령어

```bash
# 모든 서비스 중지
docker-compose down

# 데이터 삭제 포함 중지
docker-compose down -v

# 서비스 재시작
docker-compose restart

# 특정 서비스만 재시작
docker-compose restart fastapi

# 로그 확인
docker-compose logs -f fastapi

# 컨테이너 내부 접속
docker exec -it fastapi_scraper bash
```

## 다음 단계

- [ ] SECRET_KEY를 강력한 값으로 변경
- [ ] Production 환경에서는 PostgreSQL 비밀번호 변경
- [ ] HTTPS 설정 (Nginx + Let's Encrypt)
- [ ] 로그 파일 로테이션 설정
- [ ] 모니터링 도구 추가 (Grafana, Prometheus)
- [ ] 자동 백업 스크립트 설정
