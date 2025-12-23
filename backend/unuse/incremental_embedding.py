# incremental_embedding.py - 增量 Embedding 管理模組
"""
實現 CSV 業務資料的增量 embedding：
- 偵測新增記錄 → 只 embed 新記錄
- 偵測刪除記錄 → 從向量庫移除
- 偵測修改記錄 → 更新 embedding
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional

try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

# ─────────────────────────────────────────────────────────────
# 常數
# ─────────────────────────────────────────────────────────────

# ID 索引檔案名稱
INDEX_FILE_NAME = "business_record_index.json"

# ─────────────────────────────────────────────────────────────
# 記錄 ID 生成
# ─────────────────────────────────────────────────────────────

def generate_record_id(row: dict) -> str:
    """
    為每筆業務記錄生成唯一 ID
    使用 Date + Worker + Customer + Content 的 hash
    """
    # 組合關鍵欄位
    key_parts = [
        str(row.get('Date', '')).strip(),
        str(row.get('Worker', '')).strip(),
        str(row.get('Customer', '')).strip(),
        str(row.get('Content', ''))[:100].strip(),  # 只取前 100 字元避免太長
    ]
    key_str = '|'.join(key_parts)
    
    # 生成 hash 作為 ID
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()[:16]


def generate_content_hash(row: dict) -> str:
    """
    為記錄內容生成 hash，用於偵測內容變更
    """
    content_parts = [
        str(row.get('Date', '')),
        str(row.get('Worker', '')),
        str(row.get('Customer', '')),
        str(row.get('Class', '')),
        str(row.get('Content', '')),
        str(row.get('Depart', '')),
        str(row.get('Manager', '')),
    ]
    content_str = '|'.join(content_parts)
    return hashlib.md5(content_str.encode('utf-8')).hexdigest()

# ─────────────────────────────────────────────────────────────
# 索引管理
# ─────────────────────────────────────────────────────────────

class RecordIndex:
    """業務記錄索引管理器"""
    
    def __init__(self, index_path: str):
        self.index_path = index_path
        self.records: Dict[str, dict] = {}  # record_id -> {content_hash, row_num, date, ...}
        self._load()
    
    def _load(self):
        """載入索引檔案"""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.records = data.get('records', {})
            except Exception as e:
                print(f"⚠️ 載入索引失敗: {e}")
                self.records = {}
    
    def save(self):
        """儲存索引檔案"""
        try:
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            data = {
                'updated_at': datetime.now().isoformat(),
                'total_records': len(self.records),
                'records': self.records
            }
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ 儲存索引失敗: {e}")
    
    def get_all_ids(self) -> Set[str]:
        """取得所有已索引的記錄 ID"""
        return set(self.records.keys())
    
    def get_record(self, record_id: str) -> Optional[dict]:
        """取得記錄資訊"""
        return self.records.get(record_id)
    
    def add_record(self, record_id: str, content_hash: str, metadata: dict = None):
        """新增記錄到索引"""
        self.records[record_id] = {
            'content_hash': content_hash,
            'indexed_at': datetime.now().isoformat(),
            **(metadata or {})
        }
    
    def remove_record(self, record_id: str):
        """從索引移除記錄"""
        self.records.pop(record_id, None)
    
    def update_record(self, record_id: str, content_hash: str, metadata: dict = None):
        """更新記錄"""
        if record_id in self.records:
            self.records[record_id]['content_hash'] = content_hash
            self.records[record_id]['updated_at'] = datetime.now().isoformat()
            if metadata:
                self.records[record_id].update(metadata)

# ─────────────────────────────────────────────────────────────
# 增量差異計算
# ─────────────────────────────────────────────────────────────

def compute_diff(csv_path: str, index: RecordIndex) -> Tuple[List[dict], List[str], List[dict]]:
    """
    計算 CSV 與現有索引的差異
    
    Returns:
        (to_add, to_delete, to_update)
        - to_add: 需要新增的記錄 [{'record_id': ..., 'row': ..., 'content_hash': ...}, ...]
        - to_delete: 需要刪除的記錄 ID [record_id, ...]
        - to_update: 需要更新的記錄 [{'record_id': ..., 'row': ..., 'content_hash': ...}, ...]
    """
    if not _HAS_PANDAS:
        return [], [], []
    
    if not os.path.exists(csv_path):
        return [], [], []
    
    # 讀取 CSV
    try:
        df = pd.read_csv(csv_path, encoding='utf-8')
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return [], [], []
    
    # 計算 CSV 中每筆記錄的 ID 和 hash
    csv_records: Dict[str, dict] = {}
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        record_id = generate_record_id(row_dict)
        content_hash = generate_content_hash(row_dict)
        csv_records[record_id] = {
            'row': row_dict,
            'row_num': idx,
            'content_hash': content_hash
        }
    
    csv_ids = set(csv_records.keys())
    indexed_ids = index.get_all_ids()
    
    # 計算差異
    new_ids = csv_ids - indexed_ids  # CSV 有，索引沒有 → 新增
    deleted_ids = indexed_ids - csv_ids  # 索引有，CSV 沒有 → 刪除
    common_ids = csv_ids & indexed_ids  # 兩邊都有 → 檢查是否更新
    
    # 需要新增的記錄
    to_add = []
    for rid in new_ids:
        info = csv_records[rid]
        to_add.append({
            'record_id': rid,
            'row': info['row'],
            'content_hash': info['content_hash']
        })
    
    # 需要刪除的記錄
    to_delete = list(deleted_ids)
    
    # 需要更新的記錄（內容 hash 變了）
    to_update = []
    for rid in common_ids:
        csv_hash = csv_records[rid]['content_hash']
        indexed_record = index.get_record(rid)
        if indexed_record and indexed_record.get('content_hash') != csv_hash:
            to_update.append({
                'record_id': rid,
                'row': csv_records[rid]['row'],
                'content_hash': csv_hash
            })
    
    return to_add, to_delete, to_update

# ─────────────────────────────────────────────────────────────
# 增量 Embedding 執行
# ─────────────────────────────────────────────────────────────

def build_document_from_row(row: dict, record_id: str) -> 'Document':
    """從 CSV 行建立 LangChain Document"""
    from langchain_core.documents import Document
    from utils import DocumentType
    
    # 建構內容
    parts = [f"**記錄ID**: {record_id}"]
    
    field_map = {
        'Date': '日期',
        'Worker': '業務人員',
        'Customer': '客戶',
        'Class': '活動類型',
        'Content': '活動內容',
        'Depart': '部門',
        'Manager': '主管',
    }
    
    for en_name, zh_name in field_map.items():
        val = row.get(en_name, '')
        if val and str(val).strip() and str(val).lower() != 'nan':
            parts.append(f"**{zh_name}**: {str(val).strip()}")
    
    content = "\n".join(parts)
    
    # 建構 metadata
    metadata = {
        'doc_type': DocumentType.BUSINESS.value,
        'source': 'business_csv',
        'record_id': record_id,
        'date': str(row.get('Date', '')),
        'worker': str(row.get('Worker', '')),
        'customer': str(row.get('Customer', '')),
        'class': str(row.get('Class', '')),
        'depart': str(row.get('Depart', '')),
    }
    
    return Document(page_content=content, metadata=metadata)


def apply_incremental_changes(
    vectordb,
    index: RecordIndex,
    to_add: List[dict],
    to_delete: List[str],
    to_update: List[dict],
    batch_size: int = 100
) -> dict:
    """
    應用增量變更到向量庫
    
    Returns:
        {'added': int, 'deleted': int, 'updated': int}
    """
    stats = {'added': 0, 'deleted': 0, 'updated': 0}
    
    # 1. 刪除記錄
    if to_delete:
        print(f"   🗑️ 刪除 {len(to_delete)} 筆舊記錄...")
        try:
            # ChromaDB 使用 ids 參數刪除
            vectordb._collection.delete(ids=to_delete)
            for rid in to_delete:
                index.remove_record(rid)
            stats['deleted'] = len(to_delete)
        except Exception as e:
            print(f"   ⚠️ 刪除失敗: {e}")
    
    # 2. 更新記錄（先刪後加）
    if to_update:
        print(f"   🔄 更新 {len(to_update)} 筆記錄...")
        try:
            update_ids = [r['record_id'] for r in to_update]
            vectordb._collection.delete(ids=update_ids)
            
            # 重新加入
            docs = [build_document_from_row(r['row'], r['record_id']) for r in to_update]
            vectordb.add_documents(docs, ids=update_ids)
            
            for r in to_update:
                index.update_record(r['record_id'], r['content_hash'])
            stats['updated'] = len(to_update)
        except Exception as e:
            print(f"   ⚠️ 更新失敗: {e}")
    
    # 3. 新增記錄（分批）
    if to_add:
        print(f"   ➕ 新增 {len(to_add)} 筆記錄...")
        total = len(to_add)
        for i in range(0, total, batch_size):
            batch = to_add[i:i+batch_size]
            try:
                docs = [build_document_from_row(r['row'], r['record_id']) for r in batch]
                ids = [r['record_id'] for r in batch]
                vectordb.add_documents(docs, ids=ids)
                
                for r in batch:
                    index.add_record(r['record_id'], r['content_hash'], {
                        'date': str(r['row'].get('Date', '')),
                        'worker': str(r['row'].get('Worker', ''))
                    })
                
                if (i + batch_size) % 5000 < batch_size:
                    print(f"      📥 新增進度: {min(i + batch_size, total):,} / {total:,}")
            except Exception as e:
                print(f"   ⚠️ 批次新增失敗: {e}")
        
        stats['added'] = len(to_add)
    
    # 儲存索引
    index.save()
    
    return stats

# ─────────────────────────────────────────────────────────────
# 主要入口函數
# ─────────────────────────────────────────────────────────────

def incremental_embed_business_csv(
    csv_path: str,
    vectordb,
    index_dir: str,
    force_rebuild: bool = False
) -> dict:
    """
    增量更新業務 CSV 的 embedding
    
    Args:
        csv_path: CSV 檔案路徑
        vectordb: ChromaDB 向量庫實例
        index_dir: 索引檔案儲存目錄
        force_rebuild: 是否強制全部重建
    
    Returns:
        {'added': int, 'deleted': int, 'updated': int, 'total': int, 'action': str}
    """
    index_path = os.path.join(index_dir, INDEX_FILE_NAME)
    index = RecordIndex(index_path)
    
    # 強制重建：清空索引
    if force_rebuild:
        print("🔄 強制重建模式，清空現有索引...")
        index.records = {}
        index.save()
    
    # 計算差異
    print("📊 分析 CSV 變更...")
    to_add, to_delete, to_update = compute_diff(csv_path, index)
    
    total_changes = len(to_add) + len(to_delete) + len(to_update)
    
    if total_changes == 0:
        print("✅ 業務資料無變更")
        return {
            'added': 0, 'deleted': 0, 'updated': 0,
            'total': len(index.records),
            'action': 'no_change'
        }
    
    print(f"📋 變更摘要: 新增 {len(to_add)} | 刪除 {len(to_delete)} | 更新 {len(to_update)}")
    
    # 應用變更
    stats = apply_incremental_changes(
        vectordb, index,
        to_add, to_delete, to_update,
        batch_size=100
    )
    
    stats['total'] = len(index.records)
    stats['action'] = 'incremental_update'
    
    print(f"✅ 增量更新完成: 共 {stats['total']:,} 筆記錄")
    
    return stats


def get_index_stats(index_dir: str) -> dict:
    """取得索引統計資訊"""
    index_path = os.path.join(index_dir, INDEX_FILE_NAME)
    
    if not os.path.exists(index_path):
        return {'exists': False, 'total_records': 0}
    
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {
            'exists': True,
            'total_records': data.get('total_records', 0),
            'updated_at': data.get('updated_at', 'unknown')
        }
    except Exception:
        return {'exists': False, 'total_records': 0}
