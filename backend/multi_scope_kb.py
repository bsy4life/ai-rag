#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
multi_scope_kb.py - 多層級知識庫系統

支援三層知識庫架構：
1. 公用庫 (Public) - 全公司共用的技術文檔
2. 部門庫 (Department) - 各部門專屬資料
3. 個人庫 (Personal) - 用戶個人筆記與知識

功能：
- 智慧查詢路由：根據問題類型選擇合適的知識庫
- 權限控制：確保用戶只能存取有權限的資料
- 統一介面：對上層提供一致的 API
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# 路徑策略（與 config.py 對齊，並保留向後相容）
# 優先順序：
# 1) KB_ROOT（最精準，直接指定 multi-scope KB 根目錄）
# 2) DATA_DIR / DATA_ROOT（統一 data 根目錄）
# 3) BASE_DIR / APP_DIR（專案根，預設為目前檔案所在目錄）
# ─────────────────────────────────────────────────────────────
BASE_DIR = (
    os.getenv("BASE_DIR")
    or os.getenv("APP_DIR")
    or os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = (
    os.getenv("DATA_DIR")
    or os.getenv("DATA_ROOT")
    or os.path.join(BASE_DIR, "data")
)

# 知識庫根目錄（預設落在 DATA_DIR，避免 docker 內外路徑不一致）
KNOWLEDGE_BASE_ROOT = os.getenv("KB_ROOT") or DATA_DIR

# 各層級目錄
PUBLIC_DIR = os.path.join(KNOWLEDGE_BASE_ROOT, "public")          # 公用庫
DEPARTMENTS_DIR = os.path.join(KNOWLEDGE_BASE_ROOT, "departments") # 部門庫
PERSONAL_DIR = os.path.join(KNOWLEDGE_BASE_ROOT, "personal")       # 個人庫

# 向量庫目錄
VECTORDB_ROOT = os.path.join(KNOWLEDGE_BASE_ROOT, "vectordb")

# 部門對照表
DEPARTMENT_MAPPING = {
    "湖內事業部": "hukou",
    "台北事業部": "taipei", 
    "台中事業部": "taichung",
    "台南事業部": "tainan",
    "高雄事業部": "kaohsiung",
    "管理部": "admin",
    "技術部": "technical",
    "業務部": "sales",
}

# ─────────────────────────────────────────────────────────────
# 資料模型
# ─────────────────────────────────────────────────────────────

class KnowledgeScope(Enum):
    """知識庫層級"""
    PUBLIC = "public"
    DEPARTMENT = "department"
    PERSONAL = "personal"
    ALL = "all"

class DocumentCategory(Enum):
    """文件類別"""
    TECHNICAL = "technical"    # 技術文檔
    BUSINESS = "business"      # 業務資料
    POLICY = "policy"          # 政策規範
    FAQ = "faq"                # 常見問答
    NOTE = "note"              # 個人筆記
    OTHER = "other"            # 其他

@dataclass
class KnowledgeDocument:
    """知識文件"""
    id: str
    title: str
    content: str
    scope: KnowledgeScope
    category: DocumentCategory
    owner: Optional[str] = None       # 擁有者帳號（個人庫）
    department: Optional[str] = None  # 部門代碼（部門庫）
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

@dataclass
class SearchResult:
    """搜尋結果"""
    document: KnowledgeDocument
    score: float
    source: str  # 來源標識

@dataclass
class UserContext:
    """用戶上下文"""
    account: str
    name: str
    department: str
    role: str
    
    @property
    def dept_code(self) -> str:
        """取得部門代碼"""
        return DEPARTMENT_MAPPING.get(self.department, "general")

# ─────────────────────────────────────────────────────────────
# 知識庫管理器
# ─────────────────────────────────────────────────────────────

class MultiScopeKnowledgeBase:
    """多層級知識庫管理器"""
    
    def __init__(self):
        self._ensure_directories()
        self._index_cache = {}
    
    def _ensure_directories(self):
        """確保目錄結構存在"""
        dirs = [
            PUBLIC_DIR,
            os.path.join(PUBLIC_DIR, "technical"),
            os.path.join(PUBLIC_DIR, "policy"),
            os.path.join(PUBLIC_DIR, "faq"),
            DEPARTMENTS_DIR,
            PERSONAL_DIR,
            VECTORDB_ROOT,
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)
    
    def _get_user_dirs(self, user: UserContext) -> Dict[str, str]:
        """取得用戶可存取的目錄"""
        dirs = {
            "public": PUBLIC_DIR,
        }
        
        # 部門目錄
        dept_dir = os.path.join(DEPARTMENTS_DIR, user.dept_code)
        if os.path.exists(dept_dir):
            dirs["department"] = dept_dir
        
        # 個人目錄
        personal_dir = os.path.join(PERSONAL_DIR, user.account)
        os.makedirs(personal_dir, exist_ok=True)
        dirs["personal"] = personal_dir
        
        return dirs
    
    # ─────────────────────────────────────────────────────────
    # 個人筆記管理
    # ─────────────────────────────────────────────────────────
    
    def add_personal_note(
        self,
        user: UserContext,
        title: str,
        content: str,
        category: str = "note",
        tags: List[str] = None
    ) -> Dict[str, Any]:
        """新增個人筆記"""
        personal_dir = os.path.join(PERSONAL_DIR, user.account)
        os.makedirs(personal_dir, exist_ok=True)
        
        # 產生檔案名稱
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in title if c.isalnum() or c in "._- ")[:50]
        filename = f"{timestamp}_{safe_title}.md"
        filepath = os.path.join(personal_dir, filename)
        
        # 產生 ID
        note_id = hashlib.md5(f"{user.account}:{timestamp}:{title}".encode()).hexdigest()[:12]
        
        # 建立 metadata
        metadata = {
            "id": note_id,
            "title": title,
            "category": category,
            "tags": tags or [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        
        # 寫入 Markdown 檔案
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"---\n")
            f.write(f"id: {note_id}\n")
            f.write(f"title: {title}\n")
            f.write(f"category: {category}\n")
            f.write(f"tags: {', '.join(tags or [])}\n")
            f.write(f"created: {metadata['created_at']}\n")
            f.write(f"---\n\n")
            f.write(f"# {title}\n\n")
            f.write(content)
        
        return {
            "success": True,
            "id": note_id,
            "filename": filename,
            "path": filepath,
            "metadata": metadata
        }
    
    def get_personal_notes(
        self,
        user: UserContext,
        category: str = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """取得個人筆記列表"""
        personal_dir = os.path.join(PERSONAL_DIR, user.account)
        
        if not os.path.exists(personal_dir):
            return []
        
        notes = []
        for filename in os.listdir(personal_dir):
            if not filename.endswith(".md"):
                continue
            
            filepath = os.path.join(personal_dir, filename)
            stat = os.stat(filepath)
            
            # 讀取 metadata
            meta = self._parse_note_metadata(filepath)
            
            if category and meta.get("category") != category:
                continue
            
            notes.append({
                "id": meta.get("id", filename),
                "filename": filename,
                "title": meta.get("title", filename),
                "category": meta.get("category", "note"),
                "tags": meta.get("tags", []),
                "size": stat.st_size,
                "created_at": meta.get("created", datetime.fromtimestamp(stat.st_ctime).isoformat()),
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        
        # 依更新時間排序
        notes.sort(key=lambda x: x["updated_at"], reverse=True)
        return notes[:limit]
    
    def get_personal_note(self, user: UserContext, note_id: str) -> Optional[Dict[str, Any]]:
        """取得單一筆記內容"""
        personal_dir = os.path.join(PERSONAL_DIR, user.account)
        
        if not os.path.exists(personal_dir):
            return None
        
        for filename in os.listdir(personal_dir):
            if not filename.endswith(".md"):
                continue
            
            filepath = os.path.join(personal_dir, filename)
            meta = self._parse_note_metadata(filepath)
            
            if meta.get("id") == note_id or filename == note_id:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # 移除 frontmatter
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        content = parts[2].strip()
                
                return {
                    "id": meta.get("id", filename),
                    "filename": filename,
                    "title": meta.get("title", filename),
                    "content": content,
                    "category": meta.get("category", "note"),
                    "tags": meta.get("tags", []),
                }
        
        return None
    
    def update_personal_note(
        self,
        user: UserContext,
        note_id: str,
        title: str = None,
        content: str = None,
        tags: List[str] = None
    ) -> Dict[str, Any]:
        """更新個人筆記"""
        note = self.get_personal_note(user, note_id)
        if not note:
            return {"success": False, "error": "Note not found"}
        
        personal_dir = os.path.join(PERSONAL_DIR, user.account)
        filepath = os.path.join(personal_dir, note["filename"])
        
        # 更新內容
        new_title = title or note["title"]
        new_content = content if content is not None else note["content"]
        new_tags = tags if tags is not None else note["tags"]
        
        # 重寫檔案
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"---\n")
            f.write(f"id: {note_id}\n")
            f.write(f"title: {new_title}\n")
            f.write(f"category: {note.get('category', 'note')}\n")
            f.write(f"tags: {', '.join(new_tags)}\n")
            f.write(f"updated: {datetime.now().isoformat()}\n")
            f.write(f"---\n\n")
            f.write(f"# {new_title}\n\n")
            f.write(new_content)
        
        return {"success": True, "id": note_id}
    
    def delete_personal_note(self, user: UserContext, note_id: str) -> Dict[str, Any]:
        """刪除個人筆記"""
        note = self.get_personal_note(user, note_id)
        if not note:
            return {"success": False, "error": "Note not found"}
        
        personal_dir = os.path.join(PERSONAL_DIR, user.account)
        filepath = os.path.join(personal_dir, note["filename"])
        
        try:
            os.remove(filepath)
            return {"success": True, "deleted": note_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _parse_note_metadata(self, filepath: str) -> Dict[str, Any]:
        """解析筆記的 frontmatter"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            if not content.startswith("---"):
                return {}
            
            parts = content.split("---", 2)
            if len(parts) < 2:
                return {}
            
            meta = {}
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == "tags":
                        meta[key] = [t.strip() for t in value.split(",") if t.strip()]
                    else:
                        meta[key] = value
            
            return meta
        except:
            return {}
    
    # ─────────────────────────────────────────────────────────
    # 知識庫統計
    # ─────────────────────────────────────────────────────────
    
    def get_statistics(self, user: UserContext) -> Dict[str, Any]:
        """取得知識庫統計資訊"""
        stats = {
            "public": self._count_files(PUBLIC_DIR),
            "department": {},
            "personal": 0,
            "total": 0,
        }
        
        # 部門統計
        dept_dir = os.path.join(DEPARTMENTS_DIR, user.dept_code)
        if os.path.exists(dept_dir):
            stats["department"] = {
                "code": user.dept_code,
                "name": user.department,
                "files": self._count_files(dept_dir),
            }
        
        # 個人統計
        personal_dir = os.path.join(PERSONAL_DIR, user.account)
        if os.path.exists(personal_dir):
            stats["personal"] = self._count_files(personal_dir)
        
        stats["total"] = (
            stats["public"]["total"] +
            stats["department"].get("files", {}).get("total", 0) +
            stats["personal"]
        )
        
        return stats
    
    def _count_files(self, directory: str) -> Dict[str, int]:
        """計算目錄中的檔案數"""
        if not os.path.exists(directory):
            return {"total": 0, "by_type": {}}
        
        counts = {"total": 0, "by_type": {}}
        
        for root, _, files in os.walk(directory):
            for f in files:
                if f.startswith("."):
                    continue
                counts["total"] += 1
                ext = os.path.splitext(f)[1].lower()
                counts["by_type"][ext] = counts["by_type"].get(ext, 0) + 1
        
        return counts
    
    # ─────────────────────────────────────────────────────────
    # 檔案列表
    # ─────────────────────────────────────────────────────────
    
    def list_files(
        self,
        user: UserContext,
        scope: KnowledgeScope = KnowledgeScope.ALL
    ) -> Dict[str, List[Dict[str, Any]]]:
        """列出用戶可存取的檔案"""
        result = {}
        
        # 公用庫
        if scope in (KnowledgeScope.ALL, KnowledgeScope.PUBLIC):
            result["public"] = self._list_directory_files(PUBLIC_DIR, "public")
        
        # 部門庫
        if scope in (KnowledgeScope.ALL, KnowledgeScope.DEPARTMENT):
            dept_dir = os.path.join(DEPARTMENTS_DIR, user.dept_code)
            if os.path.exists(dept_dir):
                result["department"] = self._list_directory_files(dept_dir, "department")
            else:
                result["department"] = []
        
        # 個人庫
        if scope in (KnowledgeScope.ALL, KnowledgeScope.PERSONAL):
            personal_dir = os.path.join(PERSONAL_DIR, user.account)
            if os.path.exists(personal_dir):
                result["personal"] = self._list_directory_files(personal_dir, "personal")
            else:
                result["personal"] = []
        
        return result
    
    def _list_directory_files(
        self,
        directory: str,
        scope: str
    ) -> List[Dict[str, Any]]:
        """列出目錄中的檔案"""
        if not os.path.exists(directory):
            return []
        
        files = []
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                if filename.startswith("."):
                    continue
                
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, directory)
                stat = os.stat(filepath)
                
                files.append({
                    "name": filename,
                    "path": rel_path,
                    "scope": scope,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        
        # 依修改時間排序
        files.sort(key=lambda x: x["modified"], reverse=True)
        return files


# ─────────────────────────────────────────────────────────────
# 全域實例
# ─────────────────────────────────────────────────────────────

_kb_instance: Optional[MultiScopeKnowledgeBase] = None

def get_knowledge_base() -> MultiScopeKnowledgeBase:
    """取得知識庫實例"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = MultiScopeKnowledgeBase()
    return _kb_instance
