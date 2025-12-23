# knowledge_api.py - 知識庫文件管理 API
"""
提供知識庫文件的上傳、轉換、刪除和索引管理功能
支援：PDF, DOCX, MD, TXT, CSV 檔案
"""

import os
import shutil
import subprocess
import tempfile
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse

# 本地模組
from vectordb import DATA_DIR, BUSINESS_DATA_DIR, BUSINESS_CSV_FILE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.md', '.txt', '.csv', '.rtf'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# 確保目錄存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BUSINESS_DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 工具函數
# ─────────────────────────────────────────────────────────────

def get_file_extension(filename: str) -> str:
    """取得檔案副檔名（小寫）"""
    return Path(filename).suffix.lower()

def is_allowed_file(filename: str) -> bool:
    """檢查檔案類型是否允許"""
    return get_file_extension(filename) in ALLOWED_EXTENSIONS

def safe_filename(filename: str) -> str:
    """產生安全的檔案名稱"""
    # 移除路徑分隔符和特殊字元
    name = os.path.basename(filename)
    # 保留中文字元
    safe_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_')
    result = []
    for char in name:
        if char in safe_chars or '\u4e00' <= char <= '\u9fff':
            result.append(char)
        elif char in ' ':
            result.append('_')
    return ''.join(result) or 'unnamed'

def convert_pdf_to_markdown(pdf_path: str, output_path: str) -> Dict[str, Any]:
    """
    將 PDF 轉換為 Markdown
    使用 pdfplumber 提取文字和表格
    """
    try:
        import pdfplumber
        
        content_parts = []
        tables_count = 0
        pages_count = 0
        
        with pdfplumber.open(pdf_path) as pdf:
            pages_count = len(pdf.pages)
            
            for i, page in enumerate(pdf.pages):
                # 提取文字
                text = page.extract_text()
                if text:
                    content_parts.append(f"## Page {i + 1}\n\n{text}")
                
                # 提取表格
                tables = page.extract_tables()
                for j, table in enumerate(tables):
                    if table and len(table) > 0:
                        tables_count += 1
                        # 轉換為 Markdown 表格
                        md_table = convert_table_to_markdown(table)
                        content_parts.append(f"\n### Table {j + 1} (Page {i + 1})\n\n{md_table}")
        
        # 組合內容
        full_content = '\n\n'.join(content_parts)
        
        # 寫入檔案
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# {Path(pdf_path).stem}\n\n")
            f.write(f"> Converted from PDF on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(full_content)
        
        return {
            "success": True,
            "pages": pages_count,
            "tables": tables_count,
            "output_path": output_path
        }
        
    except ImportError:
        # 備用方案：使用 pdftotext
        return convert_pdf_with_pdftotext(pdf_path, output_path)
    except Exception as e:
        return {"success": False, "error": str(e)}

def convert_pdf_with_pdftotext(pdf_path: str, output_path: str) -> Dict[str, Any]:
    """使用 pdftotext 命令行工具轉換 PDF"""
    try:
        # 使用 pdftotext 保留排版
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return {"success": False, "error": f"pdftotext failed: {result.stderr}"}
        
        content = result.stdout
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# {Path(pdf_path).stem}\n\n")
            f.write(f"> Converted from PDF on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write("```\n")
            f.write(content)
            f.write("\n```\n")
        
        return {"success": True, "output_path": output_path, "method": "pdftotext"}
        
    except FileNotFoundError:
        return {"success": False, "error": "pdftotext not installed. Install with: apt-get install poppler-utils"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "PDF conversion timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def convert_docx_to_markdown(docx_path: str, output_path: str) -> Dict[str, Any]:
    """
    將 DOCX 轉換為 Markdown
    使用 pandoc 進行轉換
    """
    try:
        # 使用 pandoc 轉換
        result = subprocess.run(
            ['pandoc', docx_path, '-o', output_path, '--wrap=none'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return {"success": False, "error": f"pandoc failed: {result.stderr}"}
        
        return {"success": True, "output_path": output_path, "method": "pandoc"}
        
    except FileNotFoundError:
        return {"success": False, "error": "pandoc not installed. Install with: apt-get install pandoc"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "DOCX conversion timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def convert_table_to_markdown(table: List[List]) -> str:
    """將表格資料轉換為 Markdown 格式"""
    if not table or len(table) == 0:
        return ""
    
    # 清理 None 值
    cleaned = []
    for row in table:
        cleaned_row = [str(cell) if cell else "" for cell in row]
        cleaned.append(cleaned_row)
    
    if len(cleaned) == 0:
        return ""
    
    # 取得最大欄位數
    max_cols = max(len(row) for row in cleaned)
    
    # 標準化欄位數
    for row in cleaned:
        while len(row) < max_cols:
            row.append("")
    
    # 建立 Markdown 表格
    lines = []
    
    # 標題行
    lines.append("| " + " | ".join(cleaned[0]) + " |")
    
    # 分隔行
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    
    # 資料行
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")
    
    return '\n'.join(lines)

# ─────────────────────────────────────────────────────────────
# API 端點
# ─────────────────────────────────────────────────────────────

@router.get("/files")
async def list_knowledge_files():
    """列出所有知識庫文件"""
    files = []
    
    # 技術文檔
    if os.path.exists(DATA_DIR):
        for filename in os.listdir(DATA_DIR):
            filepath = os.path.join(DATA_DIR, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)
                files.append({
                    "name": filename,
                    "path": filepath,
                    "type": "technical",
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
    
    # 業務資料
    if os.path.exists(BUSINESS_DATA_DIR):
        for filename in os.listdir(BUSINESS_DATA_DIR):
            filepath = os.path.join(BUSINESS_DATA_DIR, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)
                files.append({
                    "name": filename,
                    "path": filepath,
                    "type": "business",
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
    
    # 排序：最新的在前
    files.sort(key=lambda x: x['modified'], reverse=True)
    
    return {
        "files": files,
        "total": len(files),
        "technical_dir": DATA_DIR,
        "business_dir": BUSINESS_DATA_DIR
    }

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    doc_type: str = Form("technical"),
    auto_convert: bool = Form(True)
):
    """
    上傳文件到知識庫
    
    Parameters:
    - file: 上傳的檔案
    - doc_type: 文件類型 (technical/business)
    - auto_convert: 是否自動轉換 PDF/DOCX 為 Markdown
    """
    # 驗證檔案
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    ext = get_file_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # 確定目標目錄
    if doc_type == "business":
        target_dir = BUSINESS_DATA_DIR
    else:
        target_dir = DATA_DIR
    
    os.makedirs(target_dir, exist_ok=True)
    
    # 產生安全檔名
    safe_name = safe_filename(file.filename)
    temp_path = os.path.join(tempfile.gettempdir(), safe_name)
    
    try:
        # 儲存上傳的檔案
        content = await file.read()
        
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"File too large. Max: {MAX_FILE_SIZE // 1024 // 1024}MB")
        
        with open(temp_path, 'wb') as f:
            f.write(content)
        
        result = {
            "filename": safe_name,
            "original_name": file.filename,
            "size": total,
            "type": doc_type
        }
        
        # 自動轉換
        if auto_convert and ext in {'.pdf', '.docx', '.doc', '.rtf'}:
            output_name = Path(safe_name).stem + '.md'
            output_path = os.path.join(target_dir, output_name)
            
            logger.info(f"📄 開始轉換 {ext} 檔案: {safe_name} -> {output_name}")
            
            if ext == '.pdf':
                convert_result = convert_pdf_to_markdown(temp_path, output_path)
            else:
                convert_result = convert_docx_to_markdown(temp_path, output_path)
            
            logger.info(f"📄 轉換結果: {convert_result}")
            
            if convert_result.get("success"):
                result["converted"] = True
                result["converted_file"] = output_name
                result["conversion_info"] = convert_result
                
                # 確認檔案已建立
                if os.path.exists(output_path):
                    logger.info(f"✅ 轉換後檔案已建立: {output_path}")
                else:
                    logger.error(f"❌ 轉換後檔案不存在: {output_path}")
                
                # 🆕 觸發向量庫重建
                try:
                    from core import reload_qa_system
                    reload_result = reload_qa_system()
                    result["vectordb_updated"] = reload_result
                    logger.info(f"✅ 向量庫已更新: {output_name}")
                except Exception as e:
                    logger.error(f"向量庫更新失敗: {e}")
                    result["vectordb_updated"] = False
            else:
                # 轉換失敗，保留原檔
                final_path = os.path.join(target_dir, safe_name)
                shutil.copy(temp_path, final_path)
                result["converted"] = False
                result["conversion_error"] = convert_result.get("error", "Unknown error")
                result["saved_as"] = safe_name
        else:
            # 直接複製檔案
            final_path = os.path.join(target_dir, safe_name)
            shutil.copy(temp_path, final_path)
            result["saved_as"] = safe_name
            
            # 🆕 觸發向量庫重建（如果是 markdown 或 txt）
            if ext in {'.md', '.txt', '.markdown'}:
                try:
                    from core import reload_qa_system
                    reload_result = reload_qa_system()
                    result["vectordb_updated"] = reload_result
                    logger.info(f"✅ 向量庫已更新: {safe_name}")
                except Exception as e:
                    logger.error(f"向量庫更新失敗: {e}")
                    result["vectordb_updated"] = False
        
        return result
        
    finally:
        # 清理暫存檔
        if os.path.exists(temp_path):
            os.remove(temp_path)

@router.delete("/files/{filename}")
async def delete_file(filename: str, doc_type: str = "technical"):
    """刪除知識庫文件"""
    if doc_type == "business":
        target_dir = BUSINESS_DATA_DIR
    else:
        target_dir = DATA_DIR
    
    filepath = os.path.join(target_dir, filename)
    
    # 安全檢查
    if not os.path.abspath(filepath).startswith(os.path.abspath(target_dir)):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        os.remove(filepath)
        return {"success": True, "deleted": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_knowledge_stats():
    """取得知識庫統計資訊"""
    tech_files = 0
    tech_size = 0
    biz_files = 0
    biz_size = 0
    
    # 技術文檔統計
    if os.path.exists(DATA_DIR):
        for filename in os.listdir(DATA_DIR):
            filepath = os.path.join(DATA_DIR, filename)
            if os.path.isfile(filepath):
                tech_files += 1
                tech_size += os.path.getsize(filepath)
    
    # 業務資料統計
    if os.path.exists(BUSINESS_DATA_DIR):
        for filename in os.listdir(BUSINESS_DATA_DIR):
            filepath = os.path.join(BUSINESS_DATA_DIR, filename)
            if os.path.isfile(filepath):
                biz_files += 1
                biz_size += os.path.getsize(filepath)
    
    return {
        "technical": {
            "files": tech_files,
            "size": tech_size,
            "size_mb": round(tech_size / 1024 / 1024, 2),
            "directory": DATA_DIR
        },
        "business": {
            "files": biz_files,
            "size": biz_size,
            "size_mb": round(biz_size / 1024 / 1024, 2),
            "directory": BUSINESS_DATA_DIR
        },
        "total_files": tech_files + biz_files,
        "total_size_mb": round((tech_size + biz_size) / 1024 / 1024, 2)
    }

@router.post("/convert")
async def convert_file(
    file: UploadFile = File(...),
    output_format: str = Form("markdown")
):
    """
    轉換文件格式（不儲存到知識庫）
    
    Parameters:
    - file: 要轉換的檔案
    - output_format: 輸出格式 (markdown/txt)
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    ext = get_file_extension(file.filename)
    if ext not in {'.pdf', '.docx', '.doc', '.rtf'}:
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, DOC, RTF can be converted")
    
    temp_input = os.path.join(tempfile.gettempdir(), f"input_{datetime.now().timestamp()}{ext}")
    temp_output = os.path.join(tempfile.gettempdir(), f"output_{datetime.now().timestamp()}.md")
    
    try:
        content = await file.read()
        with open(temp_input, 'wb') as f:
            f.write(content)
        
        if ext == '.pdf':
            result = convert_pdf_to_markdown(temp_input, temp_output)
        else:
            result = convert_docx_to_markdown(temp_input, temp_output)
        
        if result.get("success"):
            with open(temp_output, 'r', encoding='utf-8') as f:
                converted_content = f.read()
            
            return {
                "success": True,
                "original_name": file.filename,
                "content": converted_content,
                "info": result
            }
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Conversion failed"))
    
    finally:
        if os.path.exists(temp_input):
            os.remove(temp_input)
        if os.path.exists(temp_output):
            os.remove(temp_output)


# ─────────────────────────────────────────────────────────────
# 業務日報專用端點
# ─────────────────────────────────────────────────────────────

@router.post("/upload-business")
async def upload_business_report(
    file: UploadFile = File(...),
    months_to_keep: int = Form(12),
    merge_existing: bool = Form(True),
    auto_reload: bool = Form(True)
):
    """
    上傳並處理 Lotus Notes 匯出的業務日報
    
    Parameters:
    - file: Lotus Notes 匯出的 TXT 檔案
    - months_to_keep: 保留最近幾個月的資料（預設 12 個月）
    - merge_existing: 是否與現有資料合併（增量更新）
    - auto_reload: 處理完成後是否自動重建向量索引
    
    Returns:
    - 處理統計資訊
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    ext = get_file_extension(file.filename)
    if ext != '.txt':
        raise HTTPException(status_code=400, detail="Only TXT files from Lotus Notes are supported")
    
    # 儲存上傳的檔案
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
                business_dir=BUSINESS_DATA_DIR,
                months_to_keep=months_to_keep,
                trigger_reload=auto_reload
            )
            
            return {
                "success": True,
                "message": "業務日報處理完成",
                "original_file": file.filename,
                "months_kept": months_to_keep,
                "stats": result.get("stats", {}),
                "csv_path": result.get("csv_path"),
                "reloaded": result.get("reloaded", False)
            }
            
        except ImportError:
            # 退路：使用簡化版處理
            return await _fallback_business_processing(temp_path, months_to_keep, merge_existing)
    
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def _fallback_business_processing(
    temp_path: str, 
    months_to_keep: int,
    merge_existing: bool
) -> Dict[str, Any]:
    """簡化版業務日報處理（當 business_processor 不可用時）"""
    import re
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    
    # 讀取檔案
    text = None
    for enc in ("utf-8", "utf-8-sig", "cp950", "big5"):
        try:
            with open(temp_path, 'r', encoding=enc, errors='ignore') as f:
                text = f.read()
            break
        except:
            continue
    
    if not text:
        raise HTTPException(status_code=400, detail="無法讀取檔案")
    
    # 計算截止日期
    cutoff = datetime.now() - relativedelta(months=months_to_keep)
    cutoff_str = cutoff.strftime("%Y/%m/%d")
    
    # 簡單統計
    date_pattern = re.compile(r"Date:\s*(\d{4}/\d{1,2}/\d{1,2})")
    dates = date_pattern.findall(text)
    
    total = len(dates)
    filtered = sum(1 for d in dates if d >= cutoff_str)
    
    return {
        "success": True,
        "message": "使用簡化版處理（建議安裝 business_processor.py）",
        "stats": {
            "raw_records": total,
            "after_filter": filtered,
            "cutoff_date": cutoff_str
        },
        "note": "請手動執行 clean_business.py 進行完整處理"
    }


@router.get("/business-config")
async def get_business_config():
    """取得業務資料處理設定"""
    csv_path = os.path.join(BUSINESS_DATA_DIR, "clean_business.csv")
    
    config = {
        "business_dir": BUSINESS_DATA_DIR,
        "csv_exists": os.path.exists(csv_path),
        "default_months_to_keep": 12,
        "supported_formats": [".txt"],
        "auto_reload_available": True
    }
    
    # 如果 CSV 存在，提供統計資訊
    if config["csv_exists"]:
        try:
            import pandas as pd
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            config["current_records"] = len(df)
            
            if "Date" in df.columns:
                dates = df["Date"].dropna()
                if len(dates) > 0:
                    config["date_range"] = {
                        "min": dates.min(),
                        "max": dates.max()
                    }
            
            if "Worker" in df.columns:
                config["workers"] = df["Worker"].nunique()
        except:
            pass
    
    return config
