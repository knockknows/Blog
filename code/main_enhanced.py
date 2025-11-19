from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# 비밀번호 해싱 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTPBearer 스킴 (JWT 토큰 검증용)
security = HTTPBearer()

# ==========================================
# 전역 변수
# ==========================================
browser: Optional[Browser] = None

# 간단한 사용자 데이터베이스 (실제 환경에서는 DB 사용)
# 비밀번호: "secure_password_123"의 bcrypt 해시
FAKE_USERS_DB = {
    "n8n_user": {
        "username": "n8n_user",
        "hashed_password": "$2b$12$5SxX04kP/aoQVwdrBW0eZeQGSeaOU2VUtUDFHZWPZ1D7N11ERRS8S"  # secure_password_123
    }
}

# ==========================================
# Lifespan Context Manager
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 애플리케이션의 전체 생명주기를 관리해요."""
    global browser
    playwright_url = os.getenv("PLAYWRIGHT_SERVER_URL", "ws://playwright:3000")
    playwright_instance = None

    logger.info("🚀 FastAPI 서버 시작 중...")

    try:
        # Playwright 브라우저 연결
        logger.info(f"📡 Playwright Server에 연결 시도: {playwright_url}")
        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.connect(
            playwright_url,
            timeout=10000
        )
        logger.info("✅ Playwright 브라우저 연결 완료!")

        yield  # 애플리케이션 실행

    except Exception as e:
        logger.error(f"❌ 초기화 실패: {e}")
        raise
    finally:
        # 리소스 정리
        logger.info("🧹 리소스 정리 중...")
        if browser:
            await browser.close()
            logger.info("✅ 브라우저 종료 완료")
        if playwright_instance:
            await playwright_instance.stop()
            logger.info("✅ Playwright 종료 완료")

# ==========================================
# FastAPI 앱 생성
# ==========================================
app = FastAPI(
    title="N8N Playwright Scraper API",
    description="순수 스크래핑 전문 API (데이터 관리는 N8N이 담당)",
    version="2.0.0",
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
# Pydantic 모델
# ==========================================
class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class ScrapeRequest(BaseModel):
    url: HttpUrl
    wait_for: Literal["load", "domcontentloaded", "networkidle"] = "networkidle"
    timeout: int = Field(default=30000, ge=5000, le=60000)

class BatchScrapeRequest(BaseModel):
    urls: List[HttpUrl]
    wait_for: Literal["load", "domcontentloaded", "networkidle"] = "networkidle"
    timeout: int = Field(default=30000, ge=5000, le=60000)
    max_concurrent: int = Field(default=5, ge=1, le=10)

class ScrapeResponse(BaseModel):
    url: str
    title: str
    content: str
    success: bool
    error: Optional[str] = None

# ==========================================
# JWT 관련 함수
# ==========================================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 검증"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """JWT 액세스 토큰 생성"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """JWT 토큰 검증 및 사용자 정보 추출"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="토큰 검증 실패",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception

# ==========================================
# 스크래핑 함수
# ==========================================
async def scrape_single_url(
    url: str,
    wait_for: str,
    timeout: int
) -> ScrapeResponse:
    """단일 URL 스크래핑"""
    if not browser:
        return ScrapeResponse(
            url=url,
            title="",
            content="",
            success=False,
            error="브라우저가 초기화되지 않았습니다."
        )

    context = None
    page = None

    try:
        # 브라우저 컨텍스트 생성
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # 페이지 이동
        logger.info(f"🌐 스크래핑 시작: {url}")
        await page.goto(str(url), wait_until=wait_for, timeout=timeout)

        # 데이터 추출
        title = await page.title()
        content = await page.content()

        logger.info(f"✅ 스크래핑 성공: {url}")
        return ScrapeResponse(
            url=str(url),
            title=title,
            content=content,
            success=True
        )

    except PlaywrightTimeout:
        logger.error(f"⏰ 타임아웃: {url}")
        return ScrapeResponse(
            url=str(url),
            title="",
            content="",
            success=False,
            error=f"타임아웃 ({timeout}ms 초과)"
        )
    except Exception as e:
        logger.error(f"❌ 스크래핑 실패: {url} - {str(e)}")
        return ScrapeResponse(
            url=str(url),
            title="",
            content="",
            success=False,
            error=str(e)
        )
    finally:
        # 리소스 정리
        if page:
            await page.close()
        if context:
            await context.close()

# ==========================================
# API 엔드포인트
# ==========================================
@app.get("/", tags=["기본"])
async def root():
    """API 정보"""
    return {
        "name": "N8N Playwright Scraper API",
        "version": "2.0.0",
        "description": "순수 스크래핑 전문 API (데이터 관리는 N8N이 담당)",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health", tags=["기본"])
async def health_check():
    """헬스 체크"""
    browser_status = "connected" if browser else "disconnected"
    is_healthy = browser is not None

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "browser": browser_status,
        "note": "데이터 관리는 N8N PostgreSQL에서 수행됩니다."
    }

@app.post("/login", response_model=Token, tags=["인증"])
async def login(request: LoginRequest):
    """
    JWT 토큰 발급

    - **username**: n8n_user
    - **password**: secure_password_123
    """
    user = FAKE_USERS_DB.get(request.username)

    if not user or not verify_password(request.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자명 또는 비밀번호가 잘못되었습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=access_token_expires
    )

    logger.info(f"✅ JWT 토큰 발급: {user['username']}")

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

@app.post("/scrape", response_model=ScrapeResponse, tags=["스크래핑"])
async def scrape(
    request: ScrapeRequest,
    current_user: str = Depends(get_current_user)
):
    """
    단일 URL 스크래핑

    - **url**: 스크래핑할 URL
    - **wait_for**: 페이지 로드 대기 조건 (load, domcontentloaded, networkidle)
    - **timeout**: 타임아웃 (밀리초, 5000~60000)
    """
    logger.info(f"📥 스크래핑 요청: {request.url} (사용자: {current_user})")

    result = await scrape_single_url(
        url=str(request.url),
        wait_for=request.wait_for,
        timeout=request.timeout
    )

    return result

@app.post("/scrape/batch", response_model=List[ScrapeResponse], tags=["스크래핑"])
async def batch_scrape(
    request: BatchScrapeRequest,
    current_user: str = Depends(get_current_user)
):
    """
    병렬 스크래핑 (여러 URL 동시 처리)

    - **urls**: 스크래핑할 URL 리스트
    - **wait_for**: 페이지 로드 대기 조건
    - **timeout**: 타임아웃 (밀리초)
    - **max_concurrent**: 동시 실행 개수 (1~10)
    """
    logger.info(f"📥 병렬 스크래핑 요청: {len(request.urls)}개 URL (사용자: {current_user})")

    # Semaphore로 동시 실행 제한
    semaphore = asyncio.Semaphore(request.max_concurrent)

    async def scrape_with_semaphore(url: HttpUrl):
        async with semaphore:
            return await scrape_single_url(
                url=str(url),
                wait_for=request.wait_for,
                timeout=request.timeout
            )

    # 병렬 실행
    tasks = [scrape_with_semaphore(url) for url in request.urls]
    results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if r.success)
    logger.info(f"✅ 병렬 스크래핑 완료: {success_count}/{len(results)} 성공")

    return results

# ==========================================
# 에러 핸들러
# ==========================================
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logger.error(f"HTTP 예외: {exc.status_code} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"일반 예외: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "서버 내부 오류가 발생했습니다.",
            "detail": str(exc)
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
