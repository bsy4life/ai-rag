import os
import time
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import ClassVar, Optional, List
from fastapi import FastAPI, Depends, Request, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from jose import JWTError
from watcher import start_watchdog
from models import Base, User, ChatLog
from auth import create_access_token, decode_token, verify_password, get_password_hash
from core import build_qa, reload_qa_chain, chat_memories, qa_chain
from core import ensure_chinese


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ 請先設定 DATABASE_URL")
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

# ======== Pydantic Schemas ========
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
    user: Optional[str] = None
    qa_chain: ClassVar = None

# ======== 啟動時：重建記憶鏈與 Watchdog ========
from langchain.memory import ConversationBufferMemory

@asynccontextmanager
async def lifespan(app: FastAPI):
    global qa_chain
    qa_chain = build_qa()
    if qa_chain is None:
        print("⚠️ 初次建立知識庫時，build_qa() 回傳 None（資料夾可能空）。", flush=True)
    # 載入舊對話紀錄（重建 chat_memories）
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

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

# ======== Auth 驗證 ========
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

# ======== API ========

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
    
    t0 = time.time()
    result = chain.invoke({"input": q.question})
    print(f"[ask] chain.invoke 耗時 {time.time()-t0:.2f} 秒", flush=True)
    
    answer = result["answer"]
    sources = list({os.path.basename(d.metadata.get("source", "")) for d in result.get("context", [])})
    title = q.question[:20]

    # === 這一行保證回應是中文 ===
    t1 = time.time()
    #answer = ensure_chinese(answer)
    print(f"[ask] ensure_chinese 耗時 {time.time()-t1:.2f} 秒", flush=True)
    # ===========================

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

@app.get("/chat_ids/me")
def chat_ids_me(user: User = Depends(get_current_user)):
    db = SessionLocal()
    logs = db.query(ChatLog).filter_by(user_id=user.id).order_by(ChatLog.created_at).all()
    seen = set()
    ids = []
    for log in logs:
        if log.chat_id not in seen:
            ids.append({"chat_id": log.chat_id, "title": log.title or f"對話 {len(ids) + 1}"})
            seen.add(log.chat_id)
    db.close()
    return ids

@app.get("/chat_logs/{chat_id}")
def get_chat_log(chat_id: str, user: User = Depends(get_current_user)):
    db = SessionLocal()
    logs = (
        db.query(ChatLog)
        .filter(ChatLog.chat_id == chat_id, ChatLog.user_id == user.id)
        .order_by(ChatLog.created_at)
        .all()
    )
    db.close()
    return [
        {
            "id": log.id,
            "question": log.question,
            "answer": log.answer,
            "created_at": log.created_at,
        }
        for log in logs
    ]

@app.put("/chat_logs/{chat_id}/title")
def update_chat_title(chat_id: str, data: dict, user: User = Depends(get_current_user)):
    db = SessionLocal()
    logs = db.query(ChatLog).filter(ChatLog.chat_id == chat_id, ChatLog.user_id == user.id).all()
    for log in logs:
        log.title = data.get("title", "")
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/chat_logs/{chat_id}")
def delete_chat_log(chat_id: str, user: User = Depends(get_current_user)):
    db = SessionLocal()
    logs = db.query(ChatLog).filter(ChatLog.chat_id == chat_id, ChatLog.user_id == user.id).all()
    for log in logs:
        db.delete(log)
    db.commit()
    db.close()
    if chat_id in chat_memories:
        del chat_memories[chat_id]
    return {"ok": True}

@app.get("/users")
def list_users(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="管理員專用")
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    return [
        {
            "account": u.account,
            "name": u.name,
            "department": u.department,
            "role": u.role
        } for u in users
    ]

@app.get("/users/{account}")
def get_user(account: str, user: User = Depends(get_current_user)):
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    db.close()
    if not u:
        raise HTTPException(status_code=404, detail="查無此人")
    if user.role != "admin" and u.account != user.account:
        raise HTTPException(status_code=403, detail="非本人/管理員禁止查詢")
    return {
        "account": u.account,
        "name": u.name,
        "department": u.department,
        "role": u.role
    }

@app.post("/users")
def create_user(data: CreateUserRequest, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="管理員限定")
    db = SessionLocal()
    exists = db.query(User).filter_by(account=data.account).first()
    if exists:
        db.close()
        raise HTTPException(status_code=400, detail="帳號已存在")
    db.add(User(
        account=data.account,
        password=get_password_hash(data.password),
        name=data.name,
        department=data.department,
        role=data.role
    ))
    db.commit()
    db.close()
    return {"ok": True}

@app.put("/users/{account}")
def update_user(account: str, data: UpdateProfileRequest, user: User = Depends(get_current_user)):
    if user.role != "admin" and user.account != account:
        raise HTTPException(status_code=403, detail="權限不足")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="查無此人")
    u.name = data.name
    u.department = data.department
    db.commit()
    db.close()
    return {"ok": True}

@app.put("/users/{account}/password")
def reset_password(account: str, data: ResetPasswordRequest, user: User = Depends(get_current_user)):
    if user.role != "admin" and user.account != account:
        raise HTTPException(status_code=403, detail="權限不足")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="查無此人")
    u.password = get_password_hash(data.password)
    db.commit()
    db.close()
    return {"ok": True}

@app.put("/users/{account}/role")
def update_role(account: str, data: UpdateRoleRequest, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="管理員限定")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="查無此人")
    u.role = data.role
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/users/{account}")
def delete_user(account: str, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="管理員限定")
    db = SessionLocal()
    u = db.query(User).filter(User.account == account).first()
    if not u:
        db.close()
        raise HTTPException(status_code=404, detail="查無此人")
    db.delete(u)
    db.commit()
    db.close()
    return {"ok": True}

@app.get("/frontend/{file_path:path}")
def get_frontend_file(file_path: str):
    full_path = os.path.join(FRONTEND_DIR, file_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404)
    return FileResponse(full_path)
