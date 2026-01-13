# models.py - SanShin AI 資料模型
# 與 Sanshin System 共用 public.users 表

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    """用戶表 - 與 Sanshin System 共用"""
    __tablename__ = "users"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    account = Column(String, unique=True, index=True)
    password = Column(String)
    name = Column(String)
    display_name = Column(String)
    department = Column(String)
    role = Column(String, default='user')
    
    # 擴充欄位
    position_id = Column(Integer)
    department_id = Column(Integer)
    manager_id = Column(Integer)
    emp_no = Column(String)
    permissions = Column(String, default='business_report')
    is_active = Column(Boolean, default=True)

class ChatLog(Base):
    """AI 對話紀錄"""
    __tablename__ = "chat_logs"
    __table_args__ = {'schema': 'public'}
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, index=True)
    title = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("public.users.id"))
    question = Column(Text)
    answer = Column(Text)
    source_type = Column(String, nullable=True)  # 來源類型: tech/business/personal
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")
