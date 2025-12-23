#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
knowledge_api_v2.py - 知識庫 API v2

完整的知識庫管理 API，包含：
1. 多層級檔案管理（公用/部門/個人）
2. 個人筆記 CRUD
3. 業務日報處理
4. 文件轉換（PDF/DOCX → Markdown）
5. 統計與監控
"""

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# 本地模組
from multi_scope_kb import (
    get_knowledge_base, UserContext, KnowledgeScope,
    PUBLIC_DIR, DEPARTMENTS_DIR, PERSONAL_DIR, DEPARTMENT_MAPPING
)

router = APIRouter(prefix="/kb", tags=["knowledge-base-v2"])

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.md', '.txt', '.csv', '.rtf', '.xlsx', '.xls'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# 相容舊版路徑
LEGACY_DATA_DIR = os.getenv("DOCS_DIR", os.path.join(os.path.dirname(__file__), "data", "markdown"))
LEGACY_BUSINESS_DIR = os.getenv("BUSINESS_DATA_DIR", os.path.join(os.path.dirname(__file__), "data", "business"))

# ─────────────────────────────────────────────────────────────
# 請求模型
# ─────────────────────────────────────────────────────────────

class NoteCreateRequest(BaseModel):
    title: str
    content: str
    category: str = "note"
    tags: List[str] = []

class NoteUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None

# ─────────────────────────────────────────────────────────────
# 工具函數
# ─────────────────────────────────────────────────────────────

def get_user_from_token(token_payload: dict) -> UserContext:
    """從 JWT payload 建立 UserContext"""
    return UserContext(
        account=token_payload.get("sub", "unknown"),
        name=token_payload.get("name", ""),
        department=token_payload.get("department", ""),
        role=token_payload.get("role", "user"),
    )

def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()

def is_allowed_file(filename: str) -> bool:
    return get_file_extension(filename) in ALLOWED_EXTENSIONS

def safe_filename(filename: str) -> str:
    name = os.path.basename(filename)
    safe_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_')
    result = []
    for char in name:
        if char in safe_chars or '\u4e00' <= char <= '\u9fff':
            result.append(char)
        elif char == ' ':
            result.append('_')
    return ''.join(result) or 'unnamed'

def format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / 1024 / 1024:.1f} MB"

# ─────────────────────────────────────────────────────────────
# 文件轉換
# ─────────────────────────────────────────────────────────────

def convert_pdf_to_markdown(pdf_path: str, output_path: str) -> Dict[str, Any]:
    """PDF 轉 Markdown"""
    try:
        import pdfplumber
        
        content_parts = []
        tables_count = 0
        
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    content_parts.append(f"## Page {i + 1}\n\n{text}")
                
                tables = page.extract_tables()
                for j, table in enumerate(tables):
                    if table:
                        tables_count += 1
                        md_table = _table_to_markdown(table)
                        content_parts.append(f"\n### Table {j + 1}\n\n{md_table}")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# {Path(pdf_path).stem}\n\n")
            f.write('\n\n'.join(content_parts))
        
        return {"success": True, "tables": tables_count}
    except ImportError:
        return _convert_with_pdftotext(pdf_path, output_path)
    except Exception as e:
        return {"success": False, "error": str(e)}

def convert_docx_to_markdown(docx_path: str, output_path: str) -> Dict[str, Any]:
    """DOCX 轉 Markdown"""
    try:
        result = subprocess.run(
            ['pandoc', docx_path, '-o', output_path, '--wrap=none'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _convert_with_pdftotext(pdf_path: str, output_path: str) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# {Path(pdf_path).stem}\n\n```\n{result.stdout}\n```\n")
        
        return {"success": True, "method": "pdftotext"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _table_to_markdown(table: List[List]) -> str:
    if not table:
        return ""
    
    cleaned = [[str(cell) if cell else "" for cell in row] for row in table]
    max_cols = max(len(row) for row in cleaned)
    
    for row in cleaned:
        while len(row) < max_cols:
            row.append("")
    
    lines = [
        "| " + " | ".join(cleaned[0]) + " |",
        "| " + " | ".join(["---"] * max_cols) + " |"
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in cleaned[1:])
    
    return '\n'.join(lines)

def convert_excel_to_markdown(excel_path: str, output_path: str) -> Dict[str, Any]:
    """Excel 轉 Markdown"""
    try:
        import pandas as pd
        
        # 讀取所有工作表
        xlsx = pd.ExcelFile(excel_path)
        content_parts = []
        
        for sheet_name in xlsx.sheet_names:
            df = pd.read_excel(xlsx, sheet_name=sheet_name)
            
            if df.empty:
                continue
            
            content_parts.append(f"## {sheet_name}\n")
            
            # 轉換為 Markdown 表格
            try:
                md_table = df.to_markdown(index=False)
                content_parts.append(md_table)
            except:
                # 退路：手動轉換
                headers = "| " + " | ".join(str(c) for c in df.columns) + " |"
                separator = "| " + " | ".join(["---"] * len(df.columns)) + " |"
                rows = []
                for _, row in df.iterrows():
                    rows.append("| " + " | ".join(str(v) if pd.notna(v) else "" for v in row) + " |")
                content_parts.append(headers + "\n" + separator + "\n" + "\n".join(rows))
            
            content_parts.append("")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# {Path(excel_path).stem}\n\n")
            f.write('\n'.join(content_parts))
        
        return {"success": True, "sheets": len(xlsx.sheet_names)}
    except ImportError:
        return {"success": False, "error": "需要 pandas 和 openpyxl: pip install pandas openpyxl"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def convert_csv_to_markdown(csv_path: str, output_path: str) -> Dict[str, Any]:
    """CSV 轉 Markdown"""
    try:
        import pandas as pd
        
        # 嘗試不同編碼
        df = None
        for enc in ['utf-8', 'utf-8-sig', 'cp950', 'big5', 'gbk']:
            try:
                df = pd.read_csv(csv_path, encoding=enc)
                break
            except:
                continue
        
        if df is None:
            return {"success": False, "error": "無法讀取 CSV 檔案"}
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# {Path(csv_path).stem}\n\n")
            
            try:
                f.write(df.to_markdown(index=False))
            except:
                # 手動轉換
                headers = "| " + " | ".join(str(c) for c in df.columns) + " |"
                separator = "| " + " | ".join(["---"] * len(df.columns)) + " |"
                f.write(headers + "\n" + separator + "\n")
                for _, row in df.iterrows():
                    f.write("| " + " | ".join(str(v) if pd.notna(v) else "" for v in row) + " |\n")
        
        return {"success": True, "rows": len(df)}
    except ImportError:
        return {"success": False, "error": "需要 pandas: pip install pandas"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────────────────────
# API: 統計與概覽
# ─────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(user_account: str = "", user_department: str = ""):
    """取得知識庫統計"""
    kb = get_knowledge_base()
    
    # 簡易用戶上下文（實際應從 JWT 取得）
    user = UserContext(
        account=user_account or "guest",
        name="",
        department=user_department or "",
        role="user"
    )
    
    stats = kb.get_statistics(user)
    
    # 加入舊版相容統計
    legacy_tech = 0
    legacy_biz = 0
    
    if os.path.exists(LEGACY_DATA_DIR):
        legacy_tech = len([f for f in os.listdir(LEGACY_DATA_DIR) if not f.startswith(".")])
    
    if os.path.exists(LEGACY_BUSINESS_DIR):
        csv_path = os.path.join(LEGACY_BUSINESS_DIR, "clean_business.csv")
        if os.path.exists(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                legacy_biz = len(df)
            except:
                pass
    
    return {
        "multi_scope": stats,
        "legacy": {
            "technical_files": legacy_tech,
            "business_records": legacy_biz,
        },
        "departments": list(DEPARTMENT_MAPPING.keys()),
    }

@router.get("/files")
async def list_files(
    scope: str = "all",
    user_account: str = "",
    user_department: str = ""
):
    """列出檔案"""
    kb = get_knowledge_base()
    
    user = UserContext(
        account=user_account or "guest",
        name="",
        department=user_department or "",
        role="user"
    )
    
    scope_enum = {
        "all": KnowledgeScope.ALL,
        "public": KnowledgeScope.PUBLIC,
        "department": KnowledgeScope.DEPARTMENT,
        "personal": KnowledgeScope.PERSONAL,
    }.get(scope, KnowledgeScope.ALL)
    
    files = kb.list_files(user, scope_enum)
    
    # 加入舊版檔案
    if scope in ("all", "public"):
        legacy_files = []
        if os.path.exists(LEGACY_DATA_DIR):
            for f in os.listdir(LEGACY_DATA_DIR):
                if f.startswith("."):
                    continue
                filepath = os.path.join(LEGACY_DATA_DIR, f)
                if os.path.isfile(filepath):
                    stat = os.stat(filepath)
                    legacy_files.append({
                        "name": f,
                        "path": f,
                        "scope": "public",
                        "category": "technical",
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })
        
        files["technical"] = legacy_files
    
    return files

# ─────────────────────────────────────────────────────────────
# API: 個人筆記
# ─────────────────────────────────────────────────────────────

@router.post("/notes")
async def create_note(
    request: NoteCreateRequest,
    user_account: str = "",
):
    """新增個人筆記"""
    if not user_account:
        raise HTTPException(status_code=401, detail="需要登入")
    
    kb = get_knowledge_base()
    user = UserContext(account=user_account, name="", department="", role="user")
    
    result = kb.add_personal_note(
        user=user,
        title=request.title,
        content=request.content,
        category=request.category,
        tags=request.tags
    )
    
    return result

@router.get("/notes")
async def list_notes(
    user_account: str = "",
    category: str = None,
    limit: int = 50
):
    """列出個人筆記"""
    if not user_account:
        raise HTTPException(status_code=401, detail="需要登入")
    
    kb = get_knowledge_base()
    user = UserContext(account=user_account, name="", department="", role="user")
    
    notes = kb.get_personal_notes(user, category, limit)
    return {"notes": notes, "total": len(notes)}

@router.get("/notes/{note_id}")
async def get_note(note_id: str, user_account: str = ""):
    """取得單一筆記"""
    if not user_account:
        raise HTTPException(status_code=401, detail="需要登入")
    
    kb = get_knowledge_base()
    user = UserContext(account=user_account, name="", department="", role="user")
    
    note = kb.get_personal_note(user, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="筆記不存在")
    
    return note

@router.put("/notes/{note_id}")
async def update_note(
    note_id: str,
    request: NoteUpdateRequest,
    user_account: str = ""
):
    """更新筆記"""
    if not user_account:
        raise HTTPException(status_code=401, detail="需要登入")
    
    kb = get_knowledge_base()
    user = UserContext(account=user_account, name="", department="", role="user")
    
    result = kb.update_personal_note(
        user=user,
        note_id=note_id,
        title=request.title,
        content=request.content,
        tags=request.tags
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "更新失敗"))
    
    return result

@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, user_account: str = ""):
    """刪除筆記"""
    if not user_account:
        raise HTTPException(status_code=401, detail="需要登入")
    
    kb = get_knowledge_base()
    user = UserContext(account=user_account, name="", department="", role="user")
    
    result = kb.delete_personal_note(user, note_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "刪除失敗"))
    
    return result

# ─────────────────────────────────────────────────────────────
# API: 檔案上傳
# ─────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    scope: str = Form("public"),
    category: str = Form("technical"),
    auto_convert: bool = Form(True),
    user_account: str = Form(""),
    user_department: str = Form("")
):
    """上傳檔案到知識庫"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少檔案名稱")
    
    ext = get_file_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支援的檔案類型: {ext}")
    
    # 決定目標目錄
    if scope == "personal":
        if not user_account:
            raise HTTPException(status_code=401, detail="個人庫需要登入")
        target_dir = os.path.join(PERSONAL_DIR, user_account)
    elif scope == "department":
        dept_code = DEPARTMENT_MAPPING.get(user_department, "general")
        target_dir = os.path.join(DEPARTMENTS_DIR, dept_code)
    else:
        # 公用庫 - 使用舊版路徑相容
        if category == "business":
            target_dir = LEGACY_BUSINESS_DIR
        else:
            target_dir = LEGACY_DATA_DIR
    
    os.makedirs(target_dir, exist_ok=True)
    
    # 儲存檔案
    safe_name = safe_filename(file.filename)
    temp_path = os.path.join(tempfile.gettempdir(), safe_name)
    
    try:
        # 以串流方式寫入暫存檔，避免一次讀入大量記憶體
        total = 0
        chunk_size = 1024 * 1024  # 1MB
        with open(temp_path, 'wb') as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_SIZE:
                    raise HTTPException(status_code=400, detail=f"檔案過大，上限 {MAX_FILE_SIZE // 1024 // 1024}MB")
                f.write(chunk)

        result = {
            "filename": safe_name,
            "original_name": file.filename,
            "size": total,
            "scope": scope,
        }
        
        # 自動轉換
        convertible_exts = {'.pdf', '.docx', '.doc', '.rtf', '.xlsx', '.xls', '.csv'}
        if auto_convert and ext in convertible_exts:
            output_name = Path(safe_name).stem + '.md'
            output_path = os.path.join(target_dir, output_name)
            
            if ext == '.pdf':
                conv_result = convert_pdf_to_markdown(temp_path, output_path)
            elif ext in {'.xlsx', '.xls'}:
                conv_result = convert_excel_to_markdown(temp_path, output_path)
            elif ext == '.csv':
                conv_result = convert_csv_to_markdown(temp_path, output_path)
            else:
                conv_result = convert_docx_to_markdown(temp_path, output_path)
            
            if conv_result.get("success"):
                result["converted"] = True
                result["converted_file"] = output_name
                result["conversion_info"] = conv_result
            else:
                # 轉換失敗，保留原檔
                shutil.copy(temp_path, os.path.join(target_dir, safe_name))
                result["converted"] = False
                result["error"] = conv_result.get("error")
        else:
            shutil.copy(temp_path, os.path.join(target_dir, safe_name))
        
        return result
    
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@router.delete("/files/{filename}")
async def delete_file(
    filename: str,
    scope: str = "public",
    category: str = "technical",
    user_account: str = "",
    user_department: str = ""
):
    """刪除檔案"""
    # 決定目錄
    if scope == "personal":
        if not user_account:
            raise HTTPException(status_code=401, detail="需要登入")
        target_dir = os.path.join(PERSONAL_DIR, user_account)
    elif scope == "department":
        dept_code = DEPARTMENT_MAPPING.get(user_department, "general")
        target_dir = os.path.join(DEPARTMENTS_DIR, dept_code)
    else:
        if category == "business":
            target_dir = LEGACY_BUSINESS_DIR
        else:
            target_dir = LEGACY_DATA_DIR
    
    filepath = os.path.join(target_dir, filename)
    
    # 安全檢查
    if not os.path.abspath(filepath).startswith(os.path.abspath(target_dir)):
        raise HTTPException(status_code=403, detail="存取被拒絕")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="檔案不存在")
    
    try:
        os.remove(filepath)
        return {"success": True, "deleted": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────────────────────
# API: 業務日報
# ─────────────────────────────────────────────────────────────

@router.post("/business/upload")
async def upload_business_report(
    file: UploadFile = File(...),
    months_to_keep: int = Form(12),
    auto_reload: bool = Form(True)
):
    """上傳業務日報"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少檔案")
    
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="只支援 TXT 檔案")
    
    temp_path = os.path.join(tempfile.gettempdir(), f"business_{datetime.now().timestamp()}.txt")
    
    try:
        content = await file.read()
        with open(temp_path, 'wb') as f:
            f.write(content)
        
        # 使用業務處理器
        try:
            from business_processor import process_and_update_knowledge_base
            
            result = process_and_update_knowledge_base(
                input_path=temp_path,
                business_dir=LEGACY_BUSINESS_DIR,
                months_to_keep=months_to_keep,
                trigger_reload=auto_reload
            )
            
            return {
                "success": True,
                "message": "業務日報處理完成",
                "stats": result.get("stats", {}),
                "reloaded": result.get("reloaded", False)
            }
        except ImportError as e:
            raise HTTPException(status_code=500, detail=f"處理模組不可用: {e}")
    
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@router.get("/business/config")
async def get_business_config():
    """取得業務資料設定"""
    csv_path = os.path.join(LEGACY_BUSINESS_DIR, "clean_business.csv")
    
    config = {
        "directory": LEGACY_BUSINESS_DIR,
        "csv_exists": os.path.exists(csv_path),
        "default_months": 12,
    }
    
    if config["csv_exists"]:
        try:
            import pandas as pd
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            config["records"] = len(df)
            
            if "Date" in df.columns:
                dates = df["Date"].dropna()
                if len(dates) > 0:
                    config["date_range"] = {
                        "min": str(dates.min()),
                        "max": str(dates.max())
                    }
            
            if "Worker" in df.columns:
                config["workers"] = int(df["Worker"].nunique())
        except:
            pass
    
    return config
