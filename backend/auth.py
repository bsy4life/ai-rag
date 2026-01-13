# auth.py - SanShin AI 認證模組
# 改用 Werkzeug 密碼驗證（與 Sanshin System 統一）

from werkzeug.security import check_password_hash, generate_password_hash
from jose import JWTError, jwt
from datetime import datetime, timedelta
from pydantic import BaseModel
import os

# JWT 設定 - 建議與 Sanshin System 使用相同的 SECRET_KEY
SECRET_KEY = os.getenv("JWT_SECRET", "sanshin-secret-key-2025")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 預設 7 天

class TokenData(BaseModel):
    sub: str
    name: str
    role: str
    department: str = None

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    驗證密碼
    支援 Werkzeug hash (pbkdf2:sha256 或 scrypt)
    """
    try:
        return check_password_hash(hashed_password, plain_password)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """
    產生密碼 hash
    使用 Werkzeug 的 pbkdf2:sha256
    """
    return generate_password_hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """創建 JWT Token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> TokenData:
    """解碼 JWT Token"""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return TokenData(
        sub=payload.get("sub"),
        name=payload.get("name"),
        role=payload.get("role"),
        department=payload.get("department")
    )
