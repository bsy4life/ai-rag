# app.py - FastAPI 應用 + 修復後的 QA 系統 + 靜態文件服務
import os
import re
import warnings
import logging

# ─────────────────────────────────────────────────────────────
# 🔇 關閉雜訊：必須在導入其他模組之前設定
# ─────────────────────────────────────────────────────────────
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["POSTHOG_DISABLED"] = "true"

# 過濾警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain")
warnings.filterwarnings("ignore", message=".*get_relevant_documents.*")

# 設定 logging - 必須在導入 chromadb 之前
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").disabled = True
logging.getLogger("httpx").setLevel(logging.WARNING)

from typing import Optional, Tuple, Dict, Any
from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

# ==== CSV 直查總開關（預設關閉）====
USE_CSV_DIRECT = os.getenv("BIZ_CSV_DIRECT", "0").lower() in ("1","true","yes")
if USE_CSV_DIRECT:
    from business_csv import query_business_df, paginate_business_table  # 可回退／緊急救援時使用
    # 分頁狀態（僅 CSV 模式用）
    business_query_state: Dict[str, Dict[str, Any]] = {}
else:
    # 預設走 GPT-RAG，不用 CSV 分頁
    business_query_state: Dict[str, Dict[str, Any]] = {}


# 導入修復後的核心模組
from core import get_qa_system, reload_qa_system
from utils import cost_estimator

# 導入新的中介層和錯誤處理
try:
    from middleware import error_handling_middleware, limiter
    from middleware.error_handler import (
        LLMError, DatabaseError, VectorDBError, 
        AuthenticationError, RateLimitError
    )
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler
    _HAS_MIDDLEWARE = True
except ImportError as e:
    _HAS_MIDDLEWARE = False

# 導入數據庫和認證相關模組
from models import Base, User, ChatLog
from auth import verify_password, get_password_hash
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
# CSV direct import moved under USE_CSV_DIRECT
# 導入用戶管理和認證相關模組
from jose import jwt
from datetime import datetime, timedelta
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, status
from sqlalchemy import text

_last_query_df = None
_last_offset = 0

# 設置日誌 - 只設定一次，避免重複
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 降低第三方庫的日誌級別
for noisy_logger in ["uvicorn.access", "uvicorn.error", "httpcore", "httpx"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# 記錄中介層載入狀態
if _HAS_MIDDLEWARE:
    logger.info("✅ 已載入新的中介層和速率限制")
else:
    logger.warning("⚠️ 中介層載入失敗（使用舊版）")

# 全域變數，記錄每個 chat_id 的查詢狀態
business_query_state = {}  # {chat_id: {"last_query": str, "offset": int}}

# 全域變數，記錄每個 chat_id 的對話記憶
chat_memories = {}  # {chat_id: memory_object}

# 修復：正確構建 DATABASE_URL
def get_database_url():
    # 優先使用完整的 DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if database_url and not "${" in database_url:
        return database_url
    
    # 否則從個別環境變數構建
    pg_host = os.getenv("PG_HOST", "localhost")
    pg_port = os.getenv("PG_PORT", "5432")
    pg_user = os.getenv("PG_USER", "ai_user")
    pg_password = os.getenv("PG_PASSWORD", "")
    pg_database = os.getenv("PG_NAME", "ai_db")  # 修改為 PG_NAME
    
    # 確保 port 是數字
    try:
        int(pg_port)
    except ValueError:
        print(f"警告：PG_PORT 值無效：{pg_port}，使用默認值 5432")
        pg_port = "5432"
    
    constructed_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_database}"
    print(f"構建的 DATABASE_URL: postgresql://{pg_user}:***@{pg_host}:{pg_port}/{pg_database}")
    return constructed_url

DATABASE_URL = get_database_url()
if not DATABASE_URL:
    raise ValueError("⛔ 無法獲取有效的 DATABASE_URL")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)

# 確保數據庫表存在
try:
    Base.metadata.create_all(bind=engine)
    print("✅ 數據庫表初始化完成")
except Exception as e:
    print(f"⚠️ 數據庫表初始化失敗：{e}")
    
    # 檢查是否是數據庫不存在的問題
    if "does not exist" in str(e):
        print("🔧 嘗試創建數據庫...")
        try:
            # 連接到 postgres 默認數據庫來創建新數據庫
            pg_host = os.getenv("PG_HOST", "localhost")
            pg_port = os.getenv("PG_PORT", "5432")
            pg_user = os.getenv("PG_USER", "ai_user")
            pg_password = os.getenv("PG_PASSWORD", "")
            pg_database = os.getenv("PG_NAME", "ai_db")  # 修改為 PG_NAME
            
            # 連接到默認 postgres 數據庫
            admin_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/postgres"
            admin_engine = create_engine(admin_url, isolation_level='AUTOCOMMIT')
            
            with admin_engine.connect() as conn:
                # 檢查數據庫是否已存在
                result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{pg_database}'"))
                if not result.fetchone():
                    # 創建數據庫
                    conn.execute(text(f'CREATE DATABASE "{pg_database}"'))
                    print(f"✅ 數據庫 {pg_database} 創建成功")
                else:
                    print(f"ℹ️ 數據庫 {pg_database} 已存在")
            
            # 重新連接並創建表
            Base.metadata.create_all(bind=engine)
            print("✅ 數據庫表創建成功")
            
        except Exception as db_create_error:
            print(f"❌ 創建數據庫失敗：{db_create_error}")
            raise
    else:
        # 嘗試基本連接測試
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1")).fetchone()
                print("✅ 數據庫連接測試成功")
        except Exception as db_error:
            print(f"❌ 數據庫連接失敗：{db_error}")
            raise

# JWT 和認證設定
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

security = HTTPBearer()

# ─────────────────────────────────────────────────────────────
# FastAPI 應用定義
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="SanShin AI System", version="1.0.0")

# 註冊新的中介層（如果可用）
if _HAS_MIDDLEWARE:
    # 統一錯誤處理中介層
    app.middleware("http")(error_handling_middleware)
    
    # 速率限制
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    logger.info("✅ 已註冊錯誤處理中介層和速率限制")

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# 知識庫管理 API
# ─────────────────────────────────────────────────────────────
try:
    from knowledge_api import router as knowledge_router
    app.include_router(knowledge_router)
    logger.info("已載入知識庫管理 API v1")
except ImportError as e:
    logger.warning(f"知識庫管理 API v1 載入失敗: {e}")

# 載入 v2 API（多層級知識庫）- 可用環境變數關閉
# KB_V2_ENABLED=true/false（預設 true）
KB_V2_ENABLED = os.getenv("KB_V2_ENABLED", "true").strip().lower() in ("1", "true", "yes", "y", "on")

if KB_V2_ENABLED:
    try:
        from knowledge_api_v2 import router as kb_v2_router
        app.include_router(kb_v2_router)
        logger.info("已載入知識庫管理 API v2（多層級）")
    except ImportError as e:
        logger.warning(f"知識庫管理 API v2 載入失敗: {e}")
else:
    logger.info("已關閉知識庫管理 API v2（KB_V2_ENABLED=false）")

# ─────────────────────────────────────────────────────────────
# 靜態文件服務設定
# ─────────────────────────────────────────────────────────────

# 檢查前端目錄是否存在
FRONTEND_DIR = "frontend"
if os.path.exists(FRONTEND_DIR):
    # 掛載靜態文件目錄
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")
    logger.info(f"已掛載前端靜態文件目錄: {FRONTEND_DIR}")
else:
    logger.warning(f"前端目錄不存在: {FRONTEND_DIR}")

# ─────────────────────────────────────────────────────────────
# 輔助函數 - 條件式速率限制
# ─────────────────────────────────────────────────────────────

def conditional_rate_limit(rate: str):
    """條件式速率限制：只有在中介層可用時才應用"""
    def decorator(func):
        if _HAS_MIDDLEWARE:
            # 應用速率限制
            return limiter.limit(rate)(func)
        else:
            # 無速率限制，直接返回原函數
            return func
    return decorator

# ─────────────────────────────────────────────────────────────
# 請求模型
# ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    mode: str = "smart"

class QueryResponse(BaseModel):
    answer: str
    source_type: str
    cost_info: Optional[Dict[str, Any]] = None

class LoginRequest(BaseModel):
    account: str
    password: str

class LoginResponse(BaseModel):
    token: str
    name: str
    message: str = "登入成功"

class AskRequest(BaseModel):
    question: str
    chat_id: str
    user: str
    mode: str = "smart"

class AskResponse(BaseModel):
    answer: str
    title: Optional[str] = None
    sources: Optional[list] = None
    source_type: Optional[str] = None
    images: Optional[list] = None  # 🆕 個人知識庫圖片
    used_provider: Optional[str] = None  # 🆕 本次使用的 LLM provider
    used_model: Optional[str] = None  # 🆕 本次使用的模型
    classification: Optional[Dict] = None  # 🆕 智能路由分類資訊

# ─────────────────────────────────────────────────────────────
# 認證輔助函數
# ─────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """創建 JWT Token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """驗證 JWT Token"""
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        account = payload.get("sub")
        if account is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return payload
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user_from_db(token_data: dict = Depends(verify_token)) -> dict:
    """從數據庫獲取當前用戶"""
    account = token_data.get("sub")
    if not account:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.account == account).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    finally:
        db.close()
# ─────────────────────────────────────────────────────────────
# QA 系統適配器
# ─────────────────────────────────────────────────────────────

class CategorizedQASystem:
    def __init__(self, core_qa_system):
        self.core_qa = core_qa_system
        backend = getattr(core_qa_system, "backend", {})
        self.doc_count = backend.get("doc_count", 0)
        self.file_count = backend.get("file_count", 0)
        self.tech_vectordb = backend.get("retriever")
        self.business_vectordb = backend.get("business_chain")

    @staticmethod
    def _extract_current_question(s: str) -> str:
        m = re.search(r"當前問題[:：]\s*(.+)$", s, re.S)
        return m.group(1).strip() if m else s.strip()

    def ask(self, full_query: str, mode: str = "smart", user_id: str = "default"):
        question = self._extract_current_question(full_query)
        if not question.strip():
            return "請輸入有效的問題。", "system", {}

        # 使用關鍵字參數確保正確傳遞（SimplifiedQASystem 參數順序是 query, user_id, mode）
        answer, source_type, cost = self.core_qa.ask(query=question, user_id=user_id, mode=mode)

        # 🔄 Fallback（受 USE_CSV_DIRECT 控制）：若是業務查詢但回傳太空，才用 CSV 快查補上
        if USE_CSV_DIRECT and (source_type == "business") and (not answer or len(answer.strip()) < 20):
            csv_result = _direct_business_query_text(question)
            if csv_result:
                return csv_result, "business_csv", cost

        return answer, source_type, cost

# ─────────────────────────────────────────────────────────────
# 全域 QA 系統實例管理
# ─────────────────────────────────────────────────────────────
_QA: Optional[CategorizedQASystem] = None
_QA_INIT_LOCK = False  # 簡單的初始化鎖，避免重複初始化

def _build_backend() -> CategorizedQASystem:
    core_qa = get_qa_system()
    if not core_qa:
        raise RuntimeError("無法從 core 模組獲取 QA 系統")
    return CategorizedQASystem(core_qa)

def get_qa_system_for_api() -> Optional[CategorizedQASystem]:
    global _QA, _QA_INIT_LOCK
    
    if _QA is not None:
        return _QA
    
    # 避免重複初始化
    if _QA_INIT_LOCK:
        logger.debug("QA 系統正在初始化中，跳過...")
        return None
    
    _QA_INIT_LOCK = True
    try:
        logger.info("🔧 初始化 QA 系統...")
        _QA = _build_backend()
        logger.info(f"✅ QA 系統初始化完成: {_QA.file_count} 文件, {_QA.doc_count} 塊")
    except Exception as e:
        logger.error(f"❌ 建立 QA 系統失敗：{e}")
        _QA = None
    finally:
        _QA_INIT_LOCK = False
    
    return _QA

def reload_qa_system_for_api() -> bool:
    global _QA
    try:
        core_success = reload_qa_system()
        if core_success:
            _QA = _build_backend()
            return True
        return False
    except Exception as e:
        logger.error(f"重建 QA 系統失敗：{e}")
        return False

# ─────────────────────────────────────────────────────────────
# 前端路由
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """提供前端主頁面"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return HTMLResponse("""
        <html>
            <head><title>SanShin AI</title></head>
            <body>
                <h1>SanShin AI System</h1>
                <p>前端文件未找到，但 API 服務正常運行</p>
                <p>API 端點: <a href="/docs">/docs</a></p>
            </body>
        </html>
        """)

@app.get("/sw.js")
async def service_worker():
    """提供 Service Worker 文件"""
    sw_path = os.path.join(FRONTEND_DIR, "sw.js")
    if os.path.exists(sw_path):
        return FileResponse(sw_path, media_type='application/javascript')
    else:
        # 返回一個基本的 Service Worker
        return Response("""
        // 基本 Service Worker
        self.addEventListener('install', function(event) {
            console.log('Service Worker installed');
        });
        
        self.addEventListener('activate', function(event) {
            console.log('Service Worker activated');
        });
        """, media_type='application/javascript')

@app.get("/manifest.json")
async def manifest():
    """提供 PWA manifest 文件"""
    manifest_path = os.path.join(FRONTEND_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type='application/json')
    else:
        # 返回基本的 manifest
        return {
            "name": "SanShin AI",
            "short_name": "SanShin AI",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#2563eb",
            "icons": [
                {
                    "src": "/frontend/icon/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png"
                }
            ]
        }

# ─────────────────────────────────────────────────────────────
# 認證與用戶管理路由
# ─────────────────────────────────────────────────────────────

@app.post("/login", response_model=LoginResponse)
@conditional_rate_limit("10/minute")
async def login(request: Request, login_data: LoginRequest): 
    # 注意：我把原本的參數改名為 login_data 避免與 Request 衝突
    account = login_data.account.strip()
    password = login_data.password.strip()
    
    if not account or not password:
        raise HTTPException(status_code=400, detail="帳號和密碼不能為空")
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.account == account).first()
        if not user or not verify_password(password, user.password):
            raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
        
        token = create_access_token({
            "sub": account,
            "name": user.name,
            "role": user.role,
            "department": user.department
        })
        
        return LoginResponse(token=token, name=user.name)
    finally:
        db.close()

@app.get("/users/me")
async def get_current_user_info(current_user: User = Depends(get_current_user_from_db)):
    """獲取當前用戶信息"""
    return {
        "account": current_user.account,
        "name": current_user.name,
        "department": current_user.department,
        "role": current_user.role
    }

@app.get("/users")
async def list_users(current_user: User = Depends(get_current_user_from_db)):
    """列出所有用戶（僅管理員）"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="權限不足")
    
    db = SessionLocal()
    try:
        users = db.query(User).all()
        return [
            {
                "account": user.account,
                "name": user.name,
                "department": user.department,
                "role": user.role
            }
            for user in users
        ]
    finally:
        db.close()
# CSV direct import moved under USE_CSV_DIRECT
# 紀錄分頁狀態
business_query_state: Dict[str, Dict[str, Any]] = {}

# ─────────────────────────────────────────────────────────────
# 問答 API
# ─────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse)
@conditional_rate_limit("10/minute")
async def ask_endpoint(
    request: Request,  # 用於速率限制
    req: AskRequest,  # 業務邏輯數據
    current_user: User = Depends(get_current_user_from_db)
):
    """
    主要問答接口
    
    支持自動路由：系統會自動判斷查詢類型（technical/business/personal）
    也支持手動指定 mode 參數以保持向後兼容
    """
    global business_query_state

    # 🟢 Step1: 分頁「繼續」（僅 CSV 直查模式）
    if USE_CSV_DIRECT and req.question.strip() == "繼續":
        state = business_query_state.get(req.chat_id)
        if state:
            df, offset = state["df"], state["offset"]
            answer = paginate_business_table(df, offset=offset, page_size=50)
            state["offset"] += 50
            return AskResponse(
                answer=answer,
                title="繼續查詢",
                source_type="business_csv",
                sources=["business_csv"]
            )
        else:
            return AskResponse(answer="⚠️ 沒有可繼續的查詢，請先輸入新問題。")

    # 🟢 Step2: 嘗試業務查詢（僅 CSV 直查模式）
    if USE_CSV_DIRECT:
        df = query_business_df(req.question)
    else:
        df = None
    if df is not None and len(df) > 0:
        business_query_state[req.chat_id] = {
            "df": df,
            "offset": 50,
        }
        answer = paginate_business_table(df, offset=0, page_size=50)

        # ⚠️ 仍然寫入 ChatLog（保持你的功能）
        db: Session = SessionLocal()
        try:
            title = req.question[:20] + "..." if len(req.question) > 20 else req.question
            exists = db.query(ChatLog).filter_by(chat_id=req.chat_id).first()
            db.add(ChatLog(
                user_id=current_user.id,
                chat_id=req.chat_id,
                title=None if exists else title,
                question=req.question,
                answer=answer,
                created_at=datetime.utcnow()
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Business ask log error: {e}")
        finally:
            db.close()

        return AskResponse(
            answer=answer,
            title=req.question,
            source_type="business_csv",
            sources=["business_csv"]
        )

    # 🟢 Step3: fallback → 原本 QA 流程（完全不動）
    qa = get_qa_system_for_api()
    if not qa:
        raise HTTPException(status_code=503, detail="QA system not available")

    db: Session = SessionLocal()
    try:
        # 🆕 使用智能路由（mode=None 啟用自動判斷）
        answer, source_type, cost_info = qa.ask(req.question, mode=None, user_id=current_user.account)
        title = req.question[:20] + "..." if len(req.question) > 20 else req.question

        exists = db.query(ChatLog).filter_by(chat_id=req.chat_id).first()
        db.add(ChatLog(
            user_id=current_user.id,
            chat_id=req.chat_id,
            title=None if exists else title,
            question=req.question,
            answer=answer,
            created_at=datetime.utcnow()
        ))
        db.commit()

        # 提取圖片資訊和來源
        images = cost_info.get("images", []) if isinstance(cost_info, dict) else []
        sources = cost_info.get("sources", [source_type]) if isinstance(cost_info, dict) else [source_type]
        
        # 🆕 提取智能路由分類資訊
        classification = {
            'detected_type': cost_info.get('detected_type', source_type),
            'confidence': cost_info.get('confidence', 1.0),
            'reasoning': cost_info.get('reasoning', ''),
            'auto_classified': cost_info.get('auto_classified', True),
        } if isinstance(cost_info, dict) else None
        
        # 如果有澄清提示，加到 answer 尾部
        if isinstance(cost_info, dict) and cost_info.get('clarify_hint'):
            answer += cost_info['clarify_hint']

        return AskResponse(
            answer=answer,
            title=title,
            source_type=source_type,
            sources=sources if sources else None,
            images=images if images else None,
            used_provider=(cost_info or {}).get("used_provider"),
            used_model=(cost_info or {}).get("used_model"),
            classification=classification  # 🆕 新增分類資訊
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Ask endpoint error: {e}")
        raise HTTPException(status_code=500, detail="處理問題時發生錯誤")
    finally:
        db.close()

# 聊天記錄相關路由（簡化版）
@app.get("/chat_ids/me")
async def get_user_chats(current_user: User = Depends(get_current_user_from_db)):
    """獲取用戶聊天列表"""
    # 使用現有的數據庫邏輯
    db = SessionLocal()
    try:
        from sqlalchemy import func
        subq = (
            db.query(
                ChatLog.chat_id,
                func.min(ChatLog.created_at).label('first_created_at')
            )
            .filter(ChatLog.user_id == current_user.id)
            .group_by(ChatLog.chat_id)
            .subquery()
        )

        logs = (
            db.query(ChatLog)
            .join(subq, ChatLog.chat_id == subq.c.chat_id)
            .filter(ChatLog.created_at == subq.c.first_created_at)
            .filter(ChatLog.user_id == current_user.id)
            .order_by(ChatLog.created_at.desc())
            .all()
        )

        return [
            {"chat_id": log.chat_id, "title": log.title or "未命名對話"}
            for log in logs
        ]
    finally:
        db.close()

@app.get("/chat_logs/{chat_id}")
async def get_chat_logs(chat_id: str, current_user: User = Depends(get_current_user_from_db)):
    """獲取聊天記錄"""
    db = SessionLocal()
    try:
        logs = db.query(ChatLog).filter_by(user_id=current_user.id, chat_id=chat_id).order_by(ChatLog.created_at).all()
        return [
            {
                "question": log.question,
                "answer": log.answer,
                "created_at": log.created_at.strftime("%Y-%m-%d %H:%M")
            } for log in logs
        ]
    finally:
        db.close()

@app.put("/chat_logs/{chat_id}/title")
async def update_chat_title(chat_id: str, title_data: dict, current_user: User = Depends(get_current_user_from_db)):
    """更新聊天標題"""
    new_title = title_data.get("title", "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="標題不能為空")
    
    db = SessionLocal()
    try:
        logs = db.query(ChatLog).filter(ChatLog.user_id == current_user.id, ChatLog.chat_id == chat_id).all()
        if not logs:
            raise HTTPException(status_code=404, detail="找不到該對話")
        
        for log in logs:
            log.title = new_title
        db.commit()
        return {"message": "標題更新成功"}
    finally:
        db.close()

@app.delete("/chat_logs/{chat_id}")
async def delete_chat(chat_id: str, current_user: User = Depends(get_current_user_from_db)):
    """刪除聊天"""
    db = SessionLocal()
    try:
        deleted_count = db.query(ChatLog).filter(
            ChatLog.user_id == current_user.id, 
            ChatLog.chat_id == chat_id
        ).delete()

        # 同時清除記憶體中的對話記錄
        if chat_id in chat_memories:
            del chat_memories[chat_id]

        db.commit()

        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="找不到該對話")

        return {"message": f"已刪除 {deleted_count} 條聊天記錄"}
    finally:
        db.close()

# ─────────────────────────────────────────────────────────────
# API 路由
# ─────────────────────────────────────────────────────────────

@app.get("/api")
async def api_root():
    return {"message": "SanShin AI API is running", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    qa = get_qa_system_for_api()
    return {
        "status": "healthy" if qa else "unhealthy", 
        "qa_system_loaded": qa is not None,
        "frontend_available": os.path.exists(FRONTEND_DIR)
    }

@app.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest):
    qa = get_qa_system_for_api()
    if not qa:
        raise HTTPException(status_code=503, detail="QA system not available")
    answer, source_type, cost_info = qa.ask(request.query, request.mode)
    return QueryResponse(answer=answer, source_type=source_type, cost_info=cost_info)

@app.get("/system/status")
async def system_status():
    qa = get_qa_system_for_api()
    if not qa:
        return {
            "status": "not_loaded", 
            "tech_files": 0, 
            "tech_chunks": 0, 
            "business_available": False,
            "frontend_available": os.path.exists(FRONTEND_DIR)
        }
    return {
        "status": "loaded",
        "tech_files": qa.file_count,
        "tech_chunks": qa.doc_count,
        "business_available": qa.business_vectordb is not None,
        "retriever_type": type(qa.tech_vectordb).__name__ if qa.tech_vectordb else "None",
        "tech_vector_db_dir": os.getenv("TECH_VDB_DIR"),
        "frontend_available": os.path.exists(FRONTEND_DIR)
    }

@app.post("/system/reload")
async def reload_system():
    success = reload_qa_system_for_api()
    if success:
        qa = get_qa_system_for_api()
        return {
            "status": "success", 
            "tech_files": qa.file_count if qa else 0, 
            "tech_chunks": qa.doc_count if qa else 0
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to reload QA system")

# ─────────────────────────────────────────────────────────────
# 診斷路由
# ─────────────────────────────────────────────────────────────

@app.get("/system/debug")
async def debug_system():
    qa = get_qa_system_for_api()
    if not qa:
        raise HTTPException(status_code=503, detail="QA system not available")
    retriever = qa.tech_vectordb
    return {
        "retriever_class": type(retriever).__name__ if retriever else "None",
        "has_main": hasattr(retriever, "main"),
        "has_bm25": hasattr(retriever, "bm25"),
        "tech_files": qa.file_count,
        "tech_chunks": qa.doc_count,
        "business_enabled": qa.business_vectordb is not None,
        "frontend_dir": FRONTEND_DIR,
        "frontend_exists": os.path.exists(FRONTEND_DIR)
    }

@app.get("/system/files")
async def list_files():
    """列出前端文件結構"""
    if not os.path.exists(FRONTEND_DIR):
        return {"error": f"前端目錄不存在: {FRONTEND_DIR}"}
    
    files = []
    for root, dirs, filenames in os.walk(FRONTEND_DIR):
        for filename in filenames:
            rel_path = os.path.relpath(os.path.join(root, filename), FRONTEND_DIR)
            files.append(rel_path)
    
    return {"frontend_dir": FRONTEND_DIR, "files": files}

@app.get("/system/router-stats")
async def router_stats(current_user: User = Depends(get_current_user_from_db)):
    """
    獲取智能路由器統計數據（需要管理員權限）
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="權限不足")
    
    try:
        from query_router import get_router
        router = get_router()
        stats = router.get_stats()
        
        return {
            "success": True,
            "stats": stats,
            "thresholds": {
                "fast_rule": router.FAST_RULE_THRESHOLD,
                "mixed_search": router.MIXED_SEARCH_THRESHOLD,
                "clarify": router.CLARIFY_THRESHOLD,
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "路由器統計不可用"
        }

# ─────────────────────────────────────────────────────────────
# 錯誤處理
# ─────────────────────────────────────────────────────────────

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    """自定義 404 處理器"""
    path = request.url.path
    
    # 如果是前端相關請求，嘗試返回 index.html
    if path.startswith('/frontend/') and not path.endswith(('.js', '.css', '.png', '.jpg', '.ico')):
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    
    # 返回 JSON 響應而不是字典
    return JSONResponse(
        status_code=404,
        content={"error": "Not Found", "path": path, "message": "請求的資源不存在"}
    )

# ─────────────────────────────────────────────────────────────
# 🆕 個人知識庫 API
# ─────────────────────────────────────────────────────────────

# 嘗試導入個人知識庫模組
try:
    from personal_kb import get_personal_kb, add_document as add_personal_doc, search_personal
    PERSONAL_KB_ENABLED = True
    logger.info("✅ 個人知識庫模組已載入")
except ImportError as e:
    PERSONAL_KB_ENABLED = False
    logger.warning(f"⚠️ 個人知識庫模組未載入: {e}")


@app.post("/kb/personal/upload")
@conditional_rate_limit("20/hour")
async def upload_personal_document(
    request: Request,  # <--- 必須加上這一行
    file: UploadFile = File(...),
    user_account: str = Query(default="default"),
):
    """上傳文件到個人知識庫（已啟用速率限制：20次/小時）"""
    if not PERSONAL_KB_ENABLED:
        raise HTTPException(status_code=503, detail="個人知識庫功能未啟用")
    
    # 檢查格式
    allowed_ext = {'.docx', '.pdf', '.txt', '.md', '.xlsx', '.csv', '.png', '.jpg', '.jpeg', '.gif'}
    ext = os.path.splitext(file.filename)[1].lower()
    
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支援的格式: {ext}")
    
    # 儲存暫存檔
    temp_dir = "/app/data/temp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{user_account}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    
    try:
        content = await file.read()
        
        # 檢查大小 (50MB)
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="檔案太大（上限 50MB）")
        
        with open(temp_path, 'wb') as f:
            f.write(content)
        
        # 處理文件
        result = add_personal_doc(user_account, temp_path, file.filename)
        
        return {
            "success": result.get("success", False),
            "message": "處理完成" if result.get("success") else result.get("error", "處理失敗"),
            "doc_id": result.get("doc_id"),
            "filename": file.filename,
            "chunks": result.get("chunks"),
            "images": result.get("images"),
            "keywords": result.get("keywords", [])[:10],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"個人文件上傳失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.get("/kb/personal/documents")
async def list_personal_documents(user_account: str = Query(default="default")):
    """列出個人知識庫的文件"""
    if not PERSONAL_KB_ENABLED:
        return {"success": False, "documents": [], "error": "個人知識庫未啟用"}
    
    try:
        kb = get_personal_kb(user_account)
        docs = kb.list_documents()
        stats = kb.get_stats()
        
        return {
            "success": True,
            "user_id": user_account,
            "documents": docs,
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"列出個人文件失敗: {e}")
        return {"success": False, "documents": [], "error": str(e)}


@app.delete("/kb/personal/documents/{doc_id}")
async def delete_personal_document(
    doc_id: str,
    user_account: str = Query(default="default"),
):
    """刪除個人知識庫的文件"""
    if not PERSONAL_KB_ENABLED:
        raise HTTPException(status_code=503, detail="個人知識庫未啟用")
    
    try:
        kb = get_personal_kb(user_account)
        success = kb.remove_document(doc_id)
        
        if success:
            return {"success": True, "message": f"文件 {doc_id} 已刪除"}
        else:
            raise HTTPException(status_code=404, detail="文件不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kb/personal/{user_id}/images/{doc_id}/{image_name}")
async def get_personal_image(user_id: str, doc_id: str, image_name: str):
    """取得個人文件的圖片"""
    if not PERSONAL_KB_ENABLED:
        raise HTTPException(status_code=503, detail="個人知識庫未啟用")
    
    try:
        kb = get_personal_kb(user_id)
        image_path = kb.get_image_path(doc_id, image_name)
        
        if image_path and os.path.exists(image_path):
            ext = os.path.splitext(image_name)[1].lower()
            mime_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
            }
            return FileResponse(
                image_path,
                media_type=mime_types.get(ext, 'image/png'),
                headers={"Cache-Control": "max-age=86400"}
            )
        else:
            raise HTTPException(status_code=404, detail="圖片不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# 業務 AI 查詢 API（BI 智能分析）
# ─────────────────────────────────────────────────────────────

try:
    from business_ai_engine import BusinessAIEngine
    _business_ai_engine = None
    
    def get_business_ai():
        global _business_ai_engine
        if _business_ai_engine is None:
            _business_ai_engine = BusinessAIEngine()
        return _business_ai_engine
    
    @app.post("/api/business/ai-query")
    async def business_ai_query(request: Request, current_user: User = Depends(get_current_user_from_db)):
        """
        AI 驅動的業務查詢
        
        支援自然語言查詢，返回 BI 分析結果
        """
        data = await request.json()
        query = data.get("query", "").strip()
        
        if not query:
            return JSONResponse({
                "success": False,
                "error": "請輸入查詢內容"
            }, status_code=400)
        
        try:
            engine = get_business_ai()
            result = engine.query(query)
            
            return JSONResponse({
                "success": result.get("success", False),
                "answer": result.get("answer", ""),
                "insights": result.get("insights", []),
                "recommendations": result.get("recommendations", []),
                "visualizations": result.get("visualizations", []),
                "data_summary": result.get("data_summary", {}),
                "metadata": result.get("metadata", {}),
            })
        except Exception as e:
            logger.error(f"業務 AI 查詢失敗: {e}")
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)
    
    @app.get("/api/business/schema")
    async def business_schema(current_user: User = Depends(get_current_user_from_db)):
        """獲取業務數據 schema 信息"""
        try:
            engine = get_business_ai()
            return JSONResponse(engine.get_schema_info())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.get("/api/business/quick-stats")
    async def business_quick_stats(current_user: User = Depends(get_current_user_from_db)):
        """獲取業務快速統計（儀表板用）"""
        try:
            engine = get_business_ai()
            return JSONResponse(engine.get_quick_stats())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    
    @app.post("/api/business/reload")
    async def business_reload(current_user: User = Depends(get_current_user_from_db)):
        """重新載入業務數據"""
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="權限不足")
        
        try:
            engine = get_business_ai()
            engine.reload_data()
            return JSONResponse({
                "success": True,
                "message": "業務數據已重新載入",
                "schema": engine.get_schema_info()
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)
    
    logger.info("✅ 業務 AI API 端點已註冊")

except ImportError as e:
    logger.warning(f"⚠️ 業務 AI 引擎未載入，相關 API 不可用: {e}")


# ─────────────────────────────────────────────────────────────
# 應用啟動 & 關閉事件
# ─────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """應用啟動事件 - 精簡輸出"""
    print("=" * 50)
    print("🚀 SanShin AI 系統啟動中...")
    print("=" * 50)
    
    # 檢查前端文件（只在找不到時警告）
    if not os.path.exists(FRONTEND_DIR):
        logger.warning(f"⚠️ 前端目錄不存在: {FRONTEND_DIR}")
    
    # 初始化 QA 系統（get_qa_system_for_api 會處理日誌）
    qa = get_qa_system_for_api()
    if not qa:
        logger.warning("⚠️ QA 系統載入失敗，部分功能可能不可用")
    
    print("=" * 50)
    print("✅ SanShin AI 系統就緒")
    print("=" * 50)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 關閉 SanShin AI 系統...")

# ─────────────────────────────────────────────────────────────
# 如果直接執行
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")