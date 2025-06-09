import os
from typing import ClassVar
from datetime import timedelta, datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, case
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from jose import JWTError
from watcher import start_watchdog
from models import Base, User, ChatLog
from auth import create_access_token, decode_token, verify_password, get_password_hash

# ====== 重點，只 import 這四個！======
from core import build_qa, reload_qa_chain, chat_memories, qa_chain

# ─────────────── 全域參數與環境設定 ───────────────

DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_KEY:
    raise ValueError("❌ 請先設定 OPENAI_API_KEY")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data/clear")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

print(f"🛠️ Watchdog 監聽目錄：{DATA_DIR}", flush=True)
if not os.path.exists(DATA_DIR):
    print(f"❌ 目錄不存在：{DATA_DIR}", flush=True)
else:
    print(f"📁 監控資料夾存在，內含檔案：{os.listdir(DATA_DIR)}", flush=True)

# ─────────────── 資料模型（Pydantic） ───────────────

class LoginRequest(BaseModel):
    account: str
    password: str

class CreateUserRequest(BaseModel):
    account: str
    password: str
    name: str
    role: str
    department: str

class UpdateProfileRequest(BaseModel):
    name: str
    department: str

class ResetPasswordRequest(BaseModel):
    password: str

class UpdateRoleRequest(BaseModel):
    role: str

class Question(BaseModel):
    question: str
    chat_id: str
    user: str = None
    qa_chain: ClassVar = None

# ─────────────── FastAPI 啟動/關閉流程（lifespan） ───────────────

from langchain.memory import ConversationBufferMemory  # 只用於 chat_memories 初始化

@asynccontextmanager
async def lifespan(app: FastAPI):
    global qa_chain
    qa_chain = build_qa()
    if qa_chain is None:
        print("⚠️ 初次建立知識庫時，build_qa() 回傳 None（資料夾可能空）。", flush=True)
    # 從資料庫還原 chat_memories
    db = SessionLocal()
    rows = db.query(ChatLog.chat_id).distinct().all()
    for row in rows:
        chat_id = row.chat_id
        logs = (
            db.query(ChatLog)
            .filter(ChatLog.chat_id == chat_id)
            .order_by(ChatLog.created_at)
            .all()
        )
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        for log in logs:
            memory.chat_memory.add_user_message(log.question)
            memory.chat_memory.add_ai_message(log.answer)
        chat_memories[chat_id] = memory
    db.close()
    print("👀 [LIFESPAN] 準備啟動 watchdog ...", flush=True)
    observer = start_watchdog()
    print("👀 [LIFESPAN] start_watchdog() 已呼叫", flush=True)
    yield
    observer.stop()
    observer.join()

# ─────────────── FastAPI 初始化 ───────────────

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

# ─────────────── 共用函式：解析 JWT、取得當前使用者 ───────────────

def get_current_user(request: Request) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        data = decode_token(auth.replace("Bearer ", ""))
        db = SessionLocal()
        user = db.query(User).filter(User.account == data.sub).first()
        db.close()
        if not user:
            raise JWTError()
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="無效 Token")

# ─────────────── API 路由區（以下皆原樣保留） ───────────────

@app.post("/login")
def login(req: LoginRequest):
    db = SessionLocal()
    user = db.query(User).filter(User.account == req.account).first()
    if not user or not verify_password(req.password, user.password):
        db.close()
        raise HTTPException(status_code=401, detail="登入失敗")
    token = create_access_token(
        data={"sub": user.account, "name": user.name, "role": user.role},
        expires_delta=timedelta(minutes=60)
    )
    db.close()
    return {
        "token": token,
        "account": user.account,
        "name": user.name
    }

@app.post("/ask")
def ask(q: Question, user: User = Depends(get_current_user)):
    from langchain.memory import ConversationBufferMemory
    global qa_chain
    if q.chat_id not in chat_memories:
        chat_memories[q.chat_id] = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    chain = qa_chain.with_config({"memory": chat_memories[q.chat_id]})
    result = chain.invoke({"input": q.question})
    answer = result["answer"]
    sources = list({os.path.basename(d.metadata.get("source", "")) for d in result.get("context", [])})
    title = q.question[:20]

    db = SessionLocal()
    exists = db.query(ChatLog).filter_by(chat_id=q.chat_id).first()
    db.add(ChatLog(
        user_id=user.id,
        chat_id=q.chat_id,
        title=None if exists else title,
        question=q.question,
        answer=answer,
        created_at=datetime.utcnow()
    ))
    db.commit()
    db.close()

    return {
        "answer": answer,
        "title": title,
        "sources": sources,
        "no_data": len(sources) == 0
    }

# ...其餘 /users、/chat_logs 路由全部保留，不用動...




# ─────────────── 帳號管理相關路由 (Users) ───────────────

@app.get("/users")
def list_users(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="限管理員使用")
    db = SessionLocal()
    priority = case((User.role == "admin", 0), else_=1)
    users = db.query(User).order_by(priority.asc(), User.account.asc()).all()
    db.close()
    return [
        {"account": u.account, "name": u.name, "role": u.role, "department": u.department}
        for u in users
    ]

@app.get("/users/{account}")
def get_user_by_account(account: str, current: User = Depends(get_current_user)):
    db = SessionLocal()
    if current.role != "admin" and current.account != account:
        db.close()
        raise HTTPException(status_code=403, detail="限本人或管理員查詢")
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="使用者不存在")
    result = {
        "account": u.account,
        "name": u.name,
        "department": u.department,
        "role": u.role
    }
    db.close()
    return result

@app.post("/users")
def create_user(req: CreateUserRequest, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="限管理員使用")
    db = SessionLocal()
    if db.query(User).filter(User.account == req.account).first():
        db.close()
        raise HTTPException(status_code=400, detail="帳號已存在")
    db.add(User(
        account=req.account,
        password=get_password_hash(req.password),
        name=req.name,
        role=req.role,
        department=req.department
    ))
    db.commit()
    db.close()
    return {"success": True}

@app.put("/users/{account}/profile")
def update_profile(account: str, req: UpdateProfileRequest, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="限管理員操作")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="使用者不存在")
    u.name = req.name
    u.department = req.department
    db.commit()
    db.close()
    return {"success": True}

@app.put("/users/{account}/password")
def reset_password(account: str, req: ResetPasswordRequest, user: User = Depends(get_current_user)):
    if user.role != "admin" and user.account != account:
        raise HTTPException(status_code=403, detail="限本人或管理員修改")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="使用者不存在")
    u.password = get_password_hash(req.password)
    db.commit()
    db.close()
    return {"success": True}

@app.put("/users/{account}/role")
def update_role(account: str, req: UpdateRoleRequest, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="限管理員操作")
    if req.role not in ["admin", "user"]:
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 user")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="使用者不存在")
    u.role = req.role
    db.commit()
    db.close()
    return {"success": True}

@app.delete("/users/{account}")
def delete_user(account: str, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="限管理員使用")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="使用者不存在")
    db.delete(u)
    db.commit()
    db.close()
    return {"success": True}

# ─────────────── ChatLog 相關路由 ───────────────

@app.get("/chat_logs/{chat_id}")
def get_logs(chat_id: str, user: User = Depends(get_current_user)):
    db = SessionLocal()
    logs = db.query(ChatLog).filter_by(user_id=user.id, chat_id=chat_id).order_by(ChatLog.created_at).all()
    result = [
        {
            "question": log.question,
            "answer": log.answer,
            "created_at": log.created_at.strftime("%Y-%m-%d %H:%M")
        } for log in logs
    ]
    db.close()
    return result

@app.get("/chat_ids/me")
def list_user_chat_ids(user: User = Depends(get_current_user)):
    db = SessionLocal()
    subq = (
        db.query(ChatLog.chat_id, ChatLog.title, ChatLog.created_at)
          .filter(ChatLog.user_id == user.id)
          .order_by(ChatLog.chat_id, ChatLog.created_at)
          .distinct(ChatLog.chat_id)
          .all()
    )
    result = [
        {"chat_id": row.chat_id, "title": row.title or "未命名對話"}
        for row in subq
    ]
    db.close()
    return result

@app.put("/chat_logs/{chat_id}/title")
def rename_chat(chat_id: str, payload: dict, user: User = Depends(get_current_user)):
    new_title = payload.get("title", "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="缺少 title")
    db = SessionLocal()
    logs = db.query(ChatLog).filter(ChatLog.user_id == user.id, ChatLog.chat_id == chat_id).all()
    if not logs:
        db.close()
        raise HTTPException(status_code=404, detail="找不到該對話")
    for log in logs:
        log.title = new_title
    db.commit()
    db.close()
    return {"message": "標題更新成功"}

@app.delete("/chat_logs/{chat_id}")
def delete_chat(chat_id: str, user: User = Depends(get_current_user)):
    db = SessionLocal()
    db.query(ChatLog).filter(ChatLog.user_id == user.id, ChatLog.chat_id == chat_id).delete()
    db.commit()
    db.close()
    return {"message": "Chat logs deleted"}
