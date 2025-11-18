from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, HttpUrl, Field
from playwright.async_api import async_playwright, Browser, TimeoutError as PlaywrightTimeout
from typing import Literal, Optional, List
from contextlib import asynccontextmanager
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
import asyncio
import os
import logging
import asyncpg

# ==========================================
# 로깅 설정
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==========================================
# JWT 설정
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# 비밀번호 해싱 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTPBearer 스킴 (JWT 토큰 검증용)
security = HTTPBearer()

# ==========================================
# 전역 변수
# ==========================================
browser: Optional[Browser] = None
db_pool: Optional[asyncpg.Pool] = None

# 간단한 사용자 데이터베이스 (실제 환경에서는 DB 사용)
# 비밀번호: "secure_password_123"의 bcrypt 해시
FAKE_USERS_DB = {
    "n8n_user": {
        "username": "n8n_user",
        "hashed_password": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYzpLaOALem"  # secure_password_123
    }
}

# ==========================================
# PostgreSQL 설정
# ==========================================
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/scraper_db"
)

# ==========================================
# Lifespan Context Manager
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 애플리케이션의 전체 생명주기를 관리해요."""
    global browser, db_pool
    playwright_url = os.getenv("PLAYWRIGHT_SERVER_URL", "ws://playwright:3000")
    playwright_instance = None
    
    logger.info("🚀 FastAPI 서버 시작 중...")
    
    try:
        # 1. Playwright 브라우저 연결
        logger.info(f"📡 Playwright Server에 연결 시도: {playwright_url}")
        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.connect(
            playwright_url,
            timeout=10000
        )
        logger.info("✅ Playwright 브라우저 연결 완료!")
        
        # 2. PostgreSQL 연결 풀 생성
        logger.info(f"🗄️  PostgreSQL에 연결 시도: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        logger.info("✅ PostgreSQL 연결 풀 생성 완료!")
        
        # 3. 테이블 생성 (존재하지 않으면)
        async with db_pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS processed_urls (
                    id SERIAL PRIMARY KEY,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success BOOLEAN DEFAULT TRUE
                )
            ''')
            logger.info("✅ PostgreSQL 테이블 확인/생성 완료!")
        
        logger.info("💡 모든 초기화 완료! 요청을 받을 준비가 되었어요!")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ 초기화 실패: {str(e)}")
        raise
    
    finally:
        logger.info("🛑 FastAPI 서버 종료 중...")
        
        # 브라우저 종료
        if browser:
            await browser.close()
            logger.info("✅ Playwright 브라우저 연결 종료 완료")
        
        if playwright_instance:
            await playwright_instance.stop()
            logger.info("✅ Playwright 인스턴스 종료 완료")
        
        # PostgreSQL 연결 풀 종료
        if db_pool:
            await db_pool.close()
            logger.info("✅ PostgreSQL 연결 풀 종료 완료")

# ==========================================
# FastAPI 애플리케이션 초기화
# ==========================================
app = FastAPI(
    title="Playwright Scraper API with JWT & PostgreSQL",
    description="JWT 인증, 병렬 처리, PostgreSQL 중복 제거 기능을 갖춘 스크래퍼 API",
    version="3.0.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Pydantic 모델 정의
# ==========================================

class LoginRequest(BaseModel):
    """로그인 요청 모델"""
    username: str
    password: str

class TokenResponse(BaseModel):
    """JWT 토큰 응답 모델"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class ScrapeRequest(BaseModel):
    """단일 스크래핑 요청 모델"""
    url: HttpUrl
    wait_for: Literal["load", "domcontentloaded", "networkidle", "commit"] = "networkidle"
    timeout: int = Field(default=30000, ge=1000, le=120000)
    screenshot: bool = Field(default=False)
    block_resources: bool = Field(default=False)

class BatchScrapeRequest(BaseModel):
    """병렬 스크래핑 요청 모델"""
    urls: List[ScrapeRequest]
    max_concurrent: int = Field(
        default=5,
        ge=1,
        le=10,
        description="동시 처리 개수 (1~10)"
    )
    check_duplicates: bool = Field(
        default=True,
        description="PostgreSQL에서 중복 URL 체크 여부"
    )

class ScrapeResponse(BaseModel):
    """단일 스크래핑 응답 모델"""
    url: str
    html: str
    title: str
    success: bool
    is_duplicate: bool = False
    screenshot_base64: Optional[str] = None
    scraped_at: str
    response_time_ms: int
    error: Optional[str] = None

class BatchScrapeResponse(BaseModel):
    """병렬 스크래핑 응답 모델"""
    total_urls: int
    successful: int
    failed: int
    skipped_duplicates: int
    results: List[ScrapeResponse]
    total_time_ms: int

# ==========================================
# JWT 관련 함수
# ==========================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 검증"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """비밀번호 해싱"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """JWT 액세스 토큰 생성"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """JWT 토큰 검증 (의존성 주입용)"""
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않은 인증 토큰이에요",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return username
    
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰 검증에 실패했어요",
            headers={"WWW-Authenticate": "Bearer"},
        )

# ==========================================
# PostgreSQL 중복 체크 함수
# ==========================================

async def check_url_processed(url: str) -> bool:
    """URL이 이미 처리되었는지 확인"""
    global db_pool
    
    if db_pool is None:
        logger.warning("PostgreSQL 연결 풀이 없어요. 중복 체크를 건너뛰어요.")
        return False
    
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval(
                'SELECT EXISTS(SELECT 1 FROM processed_urls WHERE url = $1)',
                url
            )
            return result
    except Exception as e:
        logger.error(f"중복 체크 오류: {str(e)}")
        return False

async def save_processed_url(url: str, title: str, success: bool = True):
    """처리된 URL을 PostgreSQL에 저장"""
    global db_pool
    
    if db_pool is None:
        logger.warning("PostgreSQL 연결 풀이 없어요. URL 저장을 건너뛰어요.")
        return
    
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO processed_urls (url, title, success, processed_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (url) DO UPDATE
                SET title = EXCLUDED.title,
                    success = EXCLUDED.success,
                    processed_at = CURRENT_TIMESTAMP
                ''',
                url, title, success
            )
            logger.debug(f"URL 저장 완료: {url}")
    except Exception as e:
        logger.error(f"URL 저장 오류: {str(e)}")

# ==========================================
# 단일 스크래핑 함수 (내부용)
# ==========================================

async def scrape_single_url(
    request: ScrapeRequest,
    semaphore: Optional[asyncio.Semaphore] = None,
    check_duplicate: bool = False
) -> ScrapeResponse:
    """단일 URL 스크래핑 (병렬 처리용 내부 함수)"""
    global browser
    
    start_time = datetime.now()
    page = None
    
    # 세마포어가 있으면 사용 (동시 실행 제한)
    if semaphore:
        await semaphore.acquire()
    
    try:
        # 중복 체크
        if check_duplicate:
            is_duplicate = await check_url_processed(str(request.url))
            if is_duplicate:
                logger.info(f"⏭️  중복 URL 건너뛰기: {request.url}")
                response_time = int((datetime.now() - start_time).total_seconds() * 1000)
                return ScrapeResponse(
                    url=str(request.url),
                    html="",
                    title="",
                    success=True,
                    is_duplicate=True,
                    scraped_at=datetime.now().isoformat(),
                    response_time_ms=response_time
                )
        
        logger.info(f"🔍 크롤링 시작: {request.url}")
        
        # 페이지 생성
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        # 리소스 차단
        if request.block_resources:
            await page.route("**/*", lambda route: (
                route.abort() if route.request.resource_type in ["image", "font", "stylesheet"]
                else route.continue_()
            ))
        
        page.set_default_timeout(request.timeout)
        
        # 페이지 이동
        await page.goto(
            str(request.url),
            wait_until=request.wait_for,
            timeout=request.timeout
        )
        
        # 컨텐츠 추출
        html_content = await page.content()
        page_title = await page.title()
        
        # 스크린샷
        screenshot_base64 = None
        if request.screenshot:
            import base64
            screenshot_bytes = await page.screenshot(full_page=True, type="png")
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        response_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # PostgreSQL에 저장
        if check_duplicate:
            await save_processed_url(str(request.url), page_title, True)
        
        logger.info(f"✓ 크롤링 완료: {request.url} ({response_time}ms)")
        
        return ScrapeResponse(
            url=str(request.url),
            html=html_content,
            title=page_title,
            success=True,
            is_duplicate=False,
            screenshot_base64=screenshot_base64,
            scraped_at=datetime.now().isoformat(),
            response_time_ms=response_time
        )
    
    except PlaywrightTimeout:
        response_time = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"⏱️  타임아웃: {request.url}")
        return ScrapeResponse(
            url=str(request.url),
            html="",
            title="",
            success=False,
            scraped_at=datetime.now().isoformat(),
            response_time_ms=response_time,
            error="페이지 로딩 타임아웃"
        )
    
    except Exception as e:
        response_time = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"❌ 크롤링 실패: {request.url} - {str(e)}")
        return ScrapeResponse(
            url=str(request.url),
            html="",
            title="",
            success=False,
            scraped_at=datetime.now().isoformat(),
            response_time_ms=response_time,
            error=str(e)
        )
    
    finally:
        if page:
            await page.close()
        
        if semaphore:
            semaphore.release()

# ==========================================
# 엔드포인트: 로그인 (JWT 발급)
# ==========================================

@app.post("/login", response_model=TokenResponse, tags=["Authentication"])
async def login(login_data: LoginRequest):
    """
    로그인하여 JWT 액세스 토큰을 발급받아요.
    
    - **username**: 사용자 이름 (예: n8n_user)
    - **password**: 비밀번호 (예: secure_password_123)
    """
    user = FAKE_USERS_DB.get(login_data.username)
    
    if not user or not verify_password(login_data.password, user["hashed_password"]):
        logger.warning(f"로그인 실패 시도: {login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자 이름 또는 비밀번호가 틀렸어요",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # JWT 토큰 생성
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=access_token_expires
    )
    
    logger.info(f"✅ 로그인 성공: {login_data.username}")
    
    return TokenResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

# ==========================================
# 엔드포인트: 헬스 체크
# ==========================================

@app.get("/", tags=["Health"])
async def root():
    """API 서버 상태 확인"""
    return {
        "status": "ok",
        "message": "Playwright Scraper API with JWT & PostgreSQL",
        "version": "3.0.0"
    }

@app.get("/health", tags=["Health"])
async def health_check():
    """브라우저 및 데이터베이스 연결 상태 확인"""
    global browser, db_pool
    
    browser_status = "not connected"
    db_status = "not connected"
    
    # 브라우저 체크
    if browser:
        try:
            test_page = await browser.new_page()
            await test_page.close()
            browser_status = "connected"
        except Exception as e:
            browser_status = f"error: {str(e)}"
    
    # PostgreSQL 체크
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.fetchval('SELECT 1')
            db_status = "connected"
        except Exception as e:
            db_status = f"error: {str(e)}"
    
    is_healthy = browser_status == "connected" and db_status == "connected"
    
    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "browser": browser_status,
        "database": db_status,
        "optimization": "lifespan + connection pooling"
    }

# ==========================================
# 엔드포인트: 단일 URL 스크래핑
# ==========================================

@app.post("/scrape", response_model=ScrapeResponse, tags=["Scraping"])
async def scrape_url(
    request: ScrapeRequest,
    username: str = Depends(verify_token)
):
    """
    단일 URL을 스크래핑해요. (JWT 인증 필요)
    
    - **Authorization 헤더**: Bearer {access_token}
    """
    global browser
    
    if browser is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="브라우저가 연결되지 않았어요"
        )
    
    logger.info(f"📝 사용자 '{username}'가 단일 스크래핑 요청: {request.url}")
    
    result = await scrape_single_url(request, check_duplicate=False)
    
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": result.error,
                "url": result.url
            }
        )
    
    return result

# ==========================================
# 엔드포인트: 병렬 스크래핑
# ==========================================

@app.post("/scrape/batch", response_model=BatchScrapeResponse, tags=["Scraping"])
async def scrape_batch(
    request: BatchScrapeRequest,
    username: str = Depends(verify_token)
):
    """
    여러 URL을 병렬로 스크래핑해요. (JWT 인증 필요)
    
    - **Authorization 헤더**: Bearer {access_token}
    - **max_concurrent**: 동시 처리 개수 (기본값: 5)
    - **check_duplicates**: PostgreSQL 중복 체크 여부 (기본값: True)
    """
    global browser
    
    if browser is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="브라우저가 연결되지 않았어요"
        )
    
    if not request.urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL 목록이 비어있어요"
        )
    
    logger.info(
        f"📝 사용자 '{username}'가 병렬 스크래핑 요청: "
        f"{len(request.urls)}개 URL, 동시처리 {request.max_concurrent}개"
    )
    
    start_time = datetime.now()
    
    # 세마포어 생성 (동시 실행 제한)
    semaphore = asyncio.Semaphore(request.max_concurrent)
    
    # 병렬 스크래핑 실행
    tasks = [
        scrape_single_url(url_request, semaphore, request.check_duplicates)
        for url_request in request.urls
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=False)
    
    # 통계 계산
    successful = sum(1 for r in results if r.success and not r.is_duplicate)
    failed = sum(1 for r in results if not r.success)
    skipped_duplicates = sum(1 for r in results if r.is_duplicate)
    
    total_time = int((datetime.now() - start_time).total_seconds() * 1000)
    
    logger.info(
        f"✅ 병렬 스크래핑 완료: 총 {len(results)}개 "
        f"(성공: {successful}, 실패: {failed}, 중복: {skipped_duplicates}, {total_time}ms)"
    )
    
    return BatchScrapeResponse(
        total_urls=len(request.urls),
        successful=successful,
        failed=failed,
        skipped_duplicates=skipped_duplicates,
        results=results,
        total_time_ms=total_time
    )

# ==========================================
# 엔드포인트: 처리된 URL 조회
# ==========================================

@app.get("/processed-urls", tags=["Database"])
async def get_processed_urls(
    limit: int = 100,
    offset: int = 0,
    username: str = Depends(verify_token)
):
    """
    PostgreSQL에 저장된 처리된 URL 목록을 조회해요. (JWT 인증 필요)
    
    - **limit**: 반환할 최대 개수 (기본값: 100)
    - **offset**: 건너뛸 개수 (기본값: 0)
    """
    global db_pool
    
    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="데이터베이스가 연결되지 않았어요"
        )
    
    try:
        async with db_pool.acquire() as conn:
            # 총 개수 조회
            total_count = await conn.fetchval('SELECT COUNT(*) FROM processed_urls')
            
            # URL 목록 조회
            rows = await conn.fetch(
                '''
                SELECT id, url, title, processed_at, success
                FROM processed_urls
                ORDER BY processed_at DESC
                LIMIT $1 OFFSET $2
                ''',
                limit, offset
            )
            
            urls = [
                {
                    "id": row["id"],
                    "url": row["url"],
                    "title": row["title"],
                    "processed_at": row["processed_at"].isoformat(),
                    "success": row["success"]
                }
                for row in rows
            ]
            
            return {
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "urls": urls
            }
    
    except Exception as e:
        logger.error(f"처리된 URL 조회 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"데이터베이스 조회 오류: {str(e)}"
        )

# ==========================================
# 엔드포인트: 처리된 URL 삭제
# ==========================================

@app.delete("/processed-urls/{url_id}", tags=["Database"])
async def delete_processed_url(
    url_id: int,
    username: str = Depends(verify_token)
):
    """
    PostgreSQL에서 특정 URL을 삭제해요. (JWT 인증 필요)
    
    - **url_id**: 삭제할 URL의 ID
    """
    global db_pool
    
    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="데이터베이스가 연결되지 않았어요"
        )
    
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                'DELETE FROM processed_urls WHERE id = $1',
                url_id
            )
            
            if result == "DELETE 0":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"ID {url_id}를 찾을 수 없어요"
                )
            
            return {"message": f"ID {url_id} 삭제 완료"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"URL 삭제 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"삭제 오류: {str(e)}"
        )

# ==========================================
# 엔드포인트: 서버 정보
# ==========================================

@app.get("/info", tags=["Info"])
async def server_info():
    """현재 서버의 최적화 상태와 엔드포인트 정보"""
    global browser, db_pool
    
    return {
        "version": "3.0.0",
        "features": {
            "jwt_authentication": "enabled",
            "parallel_scraping": "enabled",
            "duplicate_check": "postgresql"
        },
        "optimization": {
            "lifespan": "enabled",
            "browser_reuse": "enabled",
            "connection_pooling": "enabled"
        },
        "status": {
            "browser_connected": browser is not None,
            "database_connected": db_pool is not None
        },
        "endpoints": {
            "authentication": "/login",
            "single_scrape": "/scrape",
            "batch_scrape": "/scrape/batch",
            "processed_urls": "/processed-urls",
            "health": "/health"
        }
    }
