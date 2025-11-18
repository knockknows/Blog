# N8N 환경 통합 가이드

이 가이드는 **이미 실행 중인 N8N + PostgreSQL 환경**에 FastAPI 스크래퍼를 추가하는 방법을 설명해요.

## 🚀 빠른 시작 (5분 안에 완료!)

```bash
# 1. N8N 네트워크 이름 확인
docker network ls | grep n8n

# 2. PostgreSQL 컨테이너명 확인  
docker ps | grep postgres

# 3. 환경 파일 생성
cp env.example .env

# 4. .env 파일 수정 (필수!)
nano .env
# - SECRET_KEY: openssl rand -hex 32 출력값 입력
# - DATABASE_URL: N8N PostgreSQL 정보 입력
# - NETWORK_NAME: 1번에서 확인한 네트워크 이름 입력

# 5. 서비스 시작
docker compose up -d

# 6. 확인
curl http://localhost:8000/health
```

**예상 응답 (성공):**
```json
{
  "status": "healthy",
  "browser": "connected",
  "database": "connected"
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

### 3. PostgreSQL에 테이블 생성

FastAPI가 사용할 테이블을 미리 만들어요:

```bash
# PostgreSQL 컨테이너 접속
docker exec -it [POSTGRES_CONTAINER_NAME] psql -U postgres -d n8n

# 테이블 생성 (FastAPI가 자동으로 생성하지만, 미리 만들어도 됨)
CREATE TABLE IF NOT EXISTS processed_urls (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE
);

# 확인
\dt
\d processed_urls

# 종료
\q
```

## 🔧 설정 방법

### 1단계: docker-compose.yml 수정

`docker-compose.yml` 파일에서 **네트워크 이름을 실제 N8N 네트워크로 변경**하세요:

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

# PostgreSQL 연결 정보 (N8N 설정과 동일하게)
DATABASE_URL=postgresql://[사용자명]:[비밀번호]@[컨테이너명]:5432/[DB명]

# 예시:
# DATABASE_URL=postgresql://postgres:mypassword@n8n-postgres:5432/n8n
```

### 3단계: FastAPI 서비스 시작

```bash
# 서비스 시작 (PostgreSQL 없이 Playwright + FastAPI만)
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
  "database": "connected",
  "optimization": "lifespan + connection pooling"
}
```

**오류 발생 시:**
```json
{
  "status": "unhealthy",
  "browser": "connected",
  "database": "error: connection refused"
}
```
→ DATABASE_URL 확인 필요!

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

### 문제 2: "could not connect to server: Connection refused"

**원인:** PostgreSQL 컨테이너명이나 연결 정보가 틀렸어요.

**해결:**
```bash
# PostgreSQL 컨테이너명 확인
docker ps | grep postgres

# N8N이 사용하는 PostgreSQL 설정 확인
docker exec n8n env | grep DB

# DATABASE_URL 수정
# postgresql://[user]:[password]@[container_name]:5432/[database]
```

### 문제 3: "relation 'processed_urls' does not exist"

**원인:** 테이블이 생성되지 않았어요.

**해결:**
```bash
# FastAPI 로그 확인 (자동 생성 시도)
docker compose logs fastapi | grep CREATE

# 수동으로 테이블 생성
docker exec -it [postgres_container] psql -U postgres -d n8n
CREATE TABLE IF NOT EXISTS processed_urls (...);
```

### 문제 4: N8N과 같은 네트워크인데도 연결 안 됨

**원인:** 방화벽 또는 네트워크 격리 설정

**해결:**
```bash
# 네트워크 상세 정보 확인
docker network inspect [network_name]

# FastAPI 컨테이너가 네트워크에 제대로 연결됐는지 확인
docker inspect fastapi_scraper | grep -A 20 Networks

# 같은 네트워크의 컨테이너끼리 통신 테스트
docker exec fastapi_scraper ping postgres
```

## 📊 N8N 워크플로우 설정

N8N에서 FastAPI를 사용할 때 주의사항:

### 1. HTTP Request 노드 URL 설정

```
❌ 잘못된 예: http://localhost:8000/scrape/batch
✅ 올바른 예: http://fastapi:8000/scrape/batch
              또는
              http://fastapi_scraper:8000/scrape/batch
```

**이유:** N8N 컨테이너에서는 `localhost`가 아닌 **컨테이너명**으로 접근해야 해요!

### 2. JWT 토큰 발급 노드

```javascript
// HTTP Request 노드 설정
Method: POST
URL: http://fastapi:8000/login
Body:
{
  "username": "n8n_user",
  "password": "secure_password_123"
}
```

### 3. 병렬 스크래핑 노드

```javascript
// HTTP Request 노드 설정
Method: POST
URL: http://fastapi:8000/scrape/batch
Headers:
  Authorization: Bearer {{ $('JWT Login').item.json.access_token }}
Body:
{
  "urls": {{ $json.urls }},
  "max_concurrent": 5,
  "check_duplicates": true
}
```

## 🎯 네트워크 구성도

```
┌─────────────────────────────────────────────────┐
│           N8N Docker Network                     │
│                                                   │
│  ┌──────────┐    ┌────────────┐    ┌─────────┐ │
│  │   N8N    │───▶│ PostgreSQL │◀───│ FastAPI │ │
│  │Container │    │ Container  │    │Container│ │
│  └──────────┘    └────────────┘    └─────────┘ │
│                         ▲                 ▲      │
│                         │                 │      │
│                         └─────────────────┘      │
│                      (같은 네트워크 공유)         │
│                                                   │
│  ┌─────────────┐                                 │
│  │ Playwright  │◀──────────────────────────────┐ │
│  │  Container  │                               │ │
│  └─────────────┘                               │ │
│                                                 │ │
└─────────────────────────────────────────────────┘
                                                  │
Host Machine:                                     │
  - N8N: http://localhost:5678                    │
  - FastAPI: http://localhost:8000                │
  - PostgreSQL: localhost:5432 (포트 노출 시)     │
```

## 📋 체크리스트

배포 전 확인사항:

- [ ] N8N 네트워크 이름 확인 (`docker network ls`)
- [ ] PostgreSQL 컨테이너명 확인 (`docker ps`)
- [ ] PostgreSQL 연결 정보 확인 (사용자명, 비밀번호, DB명)
- [ ] `docker-compose.yml`에서 네트워크 이름 수정
- [ ] `.env` 파일 생성 및 DATABASE_URL 수정
- [ ] SECRET_KEY 변경 (32자 이상 랜덤 문자열)
- [ ] PostgreSQL에 테이블 생성 (선택사항)
- [ ] `docker compose up -d` 실행
- [ ] `/health` 엔드포인트로 연결 확인
- [ ] N8N HTTP Request 노드에서 컨테이너명 사용 확인

## 🔐 보안 권장사항

1. **SECRET_KEY 생성**
   ```bash
   # 강력한 랜덤 키 생성
   openssl rand -hex 32
   ```

2. **PostgreSQL 비밀번호**
   - N8N 설정에서 사용하는 것과 동일하게 설정
   - 프로덕션 환경에서는 강력한 비밀번호 사용

3. **기본 사용자 정보 변경**
   - `main_enhanced.py`에서 `FAKE_USERS_DB` 수정
   - 또는 실제 사용자 데이터베이스 연동

## 📞 추가 도움이 필요하면

문제가 발생하면 다음 정보를 확인하세요:

```bash
# 1. 네트워크 상세 정보
docker network inspect [network_name]

# 2. 컨테이너 로그
docker compose logs fastapi
docker logs n8n
docker logs [postgres_container]

# 3. 컨테이너 연결 정보
docker inspect fastapi_scraper
docker inspect n8n

# 4. PostgreSQL 연결 테스트
docker exec fastapi_scraper ping postgres
docker exec fastapi_scraper nc -zv postgres 5432
```
