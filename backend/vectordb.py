# vectordb.py - 向量庫管理模組
"""
ChromaDB 向量庫的建立、管理、清理功能
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, Tuple, List
from threading import Lock

import chromadb
from chromadb.config import Settings

from utils import DocumentType, hash_dir, hash_csv_file

# ─────────────────────────────────────────────────────────────
# 全域 ChromaDB 客戶端（單例模式避免重複初始化）
# ─────────────────────────────────────────────────────────────
_chroma_client: Optional[chromadb.PersistentClient] = None
_client_lock = Lock()

# ─────────────────────────────────────────────────────────────
# 路徑設定
# ─────────────────────────────────────────────────────────────

# 統一目錄結構（全部在 /app/data/ 下）
BASE_DIR = os.getenv("APP_DIR", os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(BASE_DIR, "data")

# 知識庫目錄
DATA_DIR = os.getenv("DOCS_DIR", os.path.join(DATA_ROOT, "markdown"))           # 技術文檔
BUSINESS_DATA_DIR = os.getenv("BUSINESS_DATA_DIR", os.path.join(DATA_ROOT, "business"))
BUSINESS_CSV_FILE = os.getenv("BUSINESS_CSV_FILE", os.path.join(BUSINESS_DATA_DIR, "clean_business.csv"))

# 向量庫路徑（統一用 vectordb_sanshin）
VECTOR_DB_DIR = os.getenv("VECTOR_DB_DIR", os.path.join(DATA_ROOT, "vectordb_sanshin"))

# Collection 名稱
COLLECTION_NAME_TECH = "sanshin_technical_docs"
COLLECTION_NAME_BIZ = "sanshin_business_reports"

# Hash 檔案
HASH_FILE_TECH = os.path.join(VECTOR_DB_DIR, "tech_hash.json")
HASH_FILE_BIZ = os.path.join(VECTOR_DB_DIR, "biz_hash.json")

# ─────────────────────────────────────────────────────────────
# Hash 管理
# ─────────────────────────────────────────────────────────────

def save_hash_with_metadata(h: str, doc_type: DocumentType, stats: Dict):
    """儲存 hash 及統計資訊"""
    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    
    hash_file = HASH_FILE_TECH if doc_type == DocumentType.TECHNICAL else HASH_FILE_BIZ
    
    data = {
        "hash": h,
        "doc_type": doc_type.value,
        "updated_at": datetime.now().isoformat(),
        "stats": stats
    }
    
    try:
        with open(hash_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_hash_with_info(doc_type: DocumentType) -> Tuple[Optional[str], Dict]:
    """載入 hash 及統計資訊"""
    hash_file = HASH_FILE_TECH if doc_type == DocumentType.TECHNICAL else HASH_FILE_BIZ
    
    if not os.path.exists(hash_file):
        return None, {}
    
    try:
        with open(hash_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("hash"), data.get("stats", {})
    except Exception:
        return None, {}


def save_hash(h: str, doc_type: DocumentType = None):
    """簡化版：只儲存 hash"""
    save_hash_with_metadata(h, doc_type or DocumentType.TECHNICAL, {})


def load_hash(doc_type: DocumentType = None) -> Optional[str]:
    """簡化版：只載入 hash"""
    h, _ = load_hash_with_info(doc_type or DocumentType.TECHNICAL)
    return h

# ─────────────────────────────────────────────────────────────
# 摘要報告
# ─────────────────────────────────────────────────────────────

def generate_vectordb_summary() -> str:
    """生成向量庫摘要報告"""
    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    summary_file = os.path.join(VECTOR_DB_DIR, "README.md")
    
    # 載入統計資訊
    _, tech_stats = load_hash_with_info(DocumentType.TECHNICAL)
    _, biz_stats = load_hash_with_info(DocumentType.BUSINESS)
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("# SanShin AI 向量庫摘要報告\n\n")
        f.write(f"**更新時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 技術文檔\n\n")
        if tech_stats:
            f.write(f"- 原始文檔數: {tech_stats.get('original_docs', 'N/A')}\n")
            f.write(f"- 分割後塊數: {tech_stats.get('split_chunks', 'N/A')}\n")
            f.write(f"- 產品型號數: {tech_stats.get('product_codes', 'N/A')}\n")
            f.write(f"- 圖片數量: {tech_stats.get('images', 'N/A')}\n")
        else:
            f.write("- 尚未建立\n")
        
        f.write("\n## 業務資料\n\n")
        if biz_stats:
            f.write(f"- 原始記錄數: {biz_stats.get('original_records', 'N/A')}\n")
            f.write(f"- 有效記錄數: {biz_stats.get('valid_records', 'N/A')}\n")
            f.write(f"- 業務人員數: {biz_stats.get('workers', 'N/A')}\n")
            f.write(f"- 客戶數: {biz_stats.get('customers', 'N/A')}\n")
            f.write(f"- 資料年份: {biz_stats.get('years', 'N/A')}\n")
            f.write(f"- 資料來源: {biz_stats.get('data_source', 'N/A')}\n")
        else:
            f.write("- 尚未建立\n")
        
        f.write("\n## Collection 名稱\n\n")
        f.write(f"- 技術文檔: `{COLLECTION_NAME_TECH}`\n")
        f.write(f"- 業務資料: `{COLLECTION_NAME_BIZ}`\n")
    
    return summary_file

# ─────────────────────────────────────────────────────────────
# 向量庫操作
# ─────────────────────────────────────────────────────────────

def get_chroma_client() -> chromadb.PersistentClient:
    """取得全域 ChromaDB 客戶端（單例模式）"""
    global _chroma_client
    with _client_lock:
        if _chroma_client is None:
            os.makedirs(VECTOR_DB_DIR, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(
                path=VECTOR_DB_DIR,
                settings=Settings(
                    allow_reset=True,
                    anonymized_telemetry=False
                )
            )
        return _chroma_client


def list_vectordb_collections(verbose: bool = False) -> Dict:
    """列出向量庫的所有 collections"""
    result = {
        "collections": [],
        "stats": {}
    }
    
    if not os.path.exists(VECTOR_DB_DIR):
        if verbose:
            print("向量庫目錄不存在")
        return result
    
    try:
        client = get_chroma_client()
        collections = client.list_collections()
        
        if not collections:
            if verbose:
                print("沒有找到任何向量庫集合")
            return result
        
        for collection in collections:
            coll_info = {
                "name": collection.name,
                "count": collection.count()
            }
            
            # 判斷類型
            if "tech" in collection.name.lower():
                coll_info["doc_type"] = "技術文檔"
                result["stats"]["tech_chunks"] = coll_info["count"]
            elif "business" in collection.name.lower() or "biz" in collection.name.lower():
                coll_info["doc_type"] = "業務資料"
                result["stats"]["business_records"] = coll_info["count"]
            
            result["collections"].append(coll_info)
            
            if verbose:
                print(f"- {collection.name}: {coll_info['count']:,} 筆")
        
    except Exception as e:
        if verbose:
            print(f"無法列出集合: {e}")
    
    return result


def cleanup_old_vectordb():
    """清理舊的向量庫檔案"""
    old_dirs = [
        os.path.join(BASE_DIR, "data", "chroma_db"),
        os.path.join(BASE_DIR, "data", "vectordb")
    ]
    
    for old_dir in old_dirs:
        if os.path.exists(old_dir):
            import shutil
            try:
                shutil.rmtree(old_dir)
            except Exception:
                pass


def cleanup_business_vectordb():
    """清理業務向量庫資料"""
    try:
        client = get_chroma_client()
        
        try:
            client.delete_collection(name=COLLECTION_NAME_BIZ)
        except Exception:
            pass
        
        # 刪除相關檔案
        files_to_remove = [
            HASH_FILE_BIZ,
            os.path.join(VECTOR_DB_DIR, "business_reports_info.txt")
        ]
        
        for file_path in files_to_remove:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        
        return True
    except Exception:
        return False


def ensure_csv_file_available() -> bool:
    """確保 CSV 檔案在正確位置"""
    global BUSINESS_CSV_FILE
    
    if os.path.exists(BUSINESS_CSV_FILE):
        return True
    
    search_paths = [
        "/home/aiuser/ai-rag/backend/data/business/clean_business.csv",
        os.path.join(BUSINESS_DATA_DIR, "clean_business.csv"),
        "/home/aiuser/ai-rag/backend/data/clean_business.csv",
        os.path.join(BASE_DIR, "data", "clean_business.csv"),
        "/app/data/business/clean_business.csv",
        "/app/data/clean_business.csv"
    ]
    
    for search_path in search_paths:
        if os.path.exists(search_path):
            expected_path = os.path.join(BUSINESS_DATA_DIR, "clean_business.csv")
            if search_path != expected_path:
                try:
                    os.makedirs(BUSINESS_DATA_DIR, exist_ok=True)
                    if not os.path.exists(expected_path):
                        os.symlink(search_path, expected_path)
                        BUSINESS_CSV_FILE = expected_path
                except Exception:
                    try:
                        import shutil
                        shutil.copy2(search_path, expected_path)
                        BUSINESS_CSV_FILE = expected_path
                    except Exception:
                        BUSINESS_CSV_FILE = search_path
            else:
                BUSINESS_CSV_FILE = search_path
            return True
    
    return False


def diagnose_business_data(*_args, **_kwargs) -> Dict:
    """診斷業務資料狀態"""
    try:
        return list_vectordb_collections()
    except Exception as e:
        print(f"[diag] 無法診斷業務資料：{e}")
        return {}
