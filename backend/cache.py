# cache.py - 查詢快取模組
"""
提供查詢結果快取功能，減少重複 API 呼叫
支援記憶體快取和檔案快取
"""

import os
import json
import hashlib
import time
from typing import Optional, Dict, Any
from threading import Lock
from functools import wraps

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────

# 快取預設過期時間（秒）
DEFAULT_TTL = 3600  # 1 小時

# 最大快取條目數
MAX_CACHE_SIZE = 500

# 檔案快取目錄（統一放在 data/cache）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.getenv("CACHE_DIR", os.path.join(BASE_DIR, "data", "cache"))

# ─────────────────────────────────────────────────────────────
# 記憶體快取（LRU）
# ─────────────────────────────────────────────────────────────

class MemoryCache:
    """記憶體 LRU 快取"""
    
    def __init__(self, max_size: int = MAX_CACHE_SIZE, ttl: int = DEFAULT_TTL):
        self.max_size = max_size
        self.ttl = ttl
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.lock = Lock()
    
    def _generate_key(self, query: str, mode: str = "smart") -> str:
        """生成快取鍵"""
        key_str = f"{query.strip().lower()}|{mode}"
        return hashlib.md5(key_str.encode('utf-8')).hexdigest()
    
    def get(self, query: str, mode: str = "smart") -> Optional[str]:
        """取得快取"""
        key = self._generate_key(query, mode)
        
        with self.lock:
            if key not in self.cache:
                return None
            
            entry = self.cache[key]
            
            # 檢查是否過期
            if time.time() - entry['timestamp'] > self.ttl:
                del self.cache[key]
                return None
            
            # 更新存取時間（LRU）
            entry['last_access'] = time.time()
            return entry['result']
    
    def set(self, query: str, result: str, mode: str = "smart"):
        """設定快取"""
        key = self._generate_key(query, mode)
        
        with self.lock:
            # 如果快取已滿，移除最舊的條目
            if len(self.cache) >= self.max_size:
                oldest_key = min(
                    self.cache.keys(),
                    key=lambda k: self.cache[k].get('last_access', 0)
                )
                del self.cache[oldest_key]
            
            self.cache[key] = {
                'result': result,
                'timestamp': time.time(),
                'last_access': time.time(),
                'query': query,
                'mode': mode
            }
    
    def clear(self):
        """清空快取"""
        with self.lock:
            self.cache.clear()
    
    def stats(self) -> Dict:
        """快取統計"""
        with self.lock:
            now = time.time()
            valid_count = sum(
                1 for entry in self.cache.values()
                if now - entry['timestamp'] <= self.ttl
            )
            return {
                'total_entries': len(self.cache),
                'valid_entries': valid_count,
                'max_size': self.max_size,
                'ttl': self.ttl
            }

# ─────────────────────────────────────────────────────────────
# 檔案快取（持久化）
# ─────────────────────────────────────────────────────────────

class FileCache:
    """檔案持久化快取"""
    
    def __init__(self, cache_dir: str = CACHE_DIR, ttl: int = DEFAULT_TTL):
        self.cache_dir = cache_dir
        self.ttl = ttl
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_path(self, key: str) -> str:
        """取得快取檔案路徑"""
        return os.path.join(self.cache_dir, f"{key}.json")
    
    def _generate_key(self, query: str, mode: str = "smart") -> str:
        """生成快取鍵"""
        key_str = f"{query.strip().lower()}|{mode}"
        return hashlib.md5(key_str.encode('utf-8')).hexdigest()
    
    def get(self, query: str, mode: str = "smart") -> Optional[str]:
        """取得快取"""
        key = self._generate_key(query, mode)
        path = self._get_path(key)
        
        if not os.path.exists(path):
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                entry = json.load(f)
            
            # 檢查是否過期
            if time.time() - entry['timestamp'] > self.ttl:
                os.remove(path)
                return None
            
            return entry['result']
        except Exception:
            return None
    
    def set(self, query: str, result: str, mode: str = "smart"):
        """設定快取"""
        key = self._generate_key(query, mode)
        path = self._get_path(key)
        
        entry = {
            'result': result,
            'timestamp': time.time(),
            'query': query,
            'mode': mode
        }
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def clear(self):
        """清空快取"""
        import shutil
        try:
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────
# 全域快取實例
# ─────────────────────────────────────────────────────────────

_memory_cache: Optional[MemoryCache] = None
_file_cache: Optional[FileCache] = None

def get_cache(use_file: bool = False):
    """取得快取實例"""
    global _memory_cache, _file_cache
    
    if use_file:
        if _file_cache is None:
            _file_cache = FileCache()
        return _file_cache
    else:
        if _memory_cache is None:
            _memory_cache = MemoryCache()
        return _memory_cache

# ─────────────────────────────────────────────────────────────
# 裝飾器
# ─────────────────────────────────────────────────────────────

def cached_query(ttl: int = DEFAULT_TTL, use_file: bool = False):
    """
    查詢快取裝飾器
    
    用法：
    @cached_query(ttl=1800)
    def my_query_function(query: str, mode: str = "smart"):
        ...
    """
    def decorator(func):
        cache = get_cache(use_file)
        
        @wraps(func)
        def wrapper(query: str, mode: str = "smart", *args, **kwargs):
            # 嘗試從快取取得
            cached_result = cache.get(query, mode)
            if cached_result is not None:
                return cached_result
            
            # 執行查詢
            result = func(query, mode, *args, **kwargs)
            
            # 存入快取
            if isinstance(result, str):
                cache.set(query, result, mode)
            elif isinstance(result, tuple) and len(result) > 0:
                cache.set(query, result[0], mode)
            
            return result
        
        return wrapper
    return decorator

# ─────────────────────────────────────────────────────────────
# 工具函數
# ─────────────────────────────────────────────────────────────

def clear_all_cache():
    """清空所有快取"""
    if _memory_cache:
        _memory_cache.clear()
    if _file_cache:
        _file_cache.clear()


def get_cache_stats() -> Dict:
    """取得快取統計"""
    stats = {}
    if _memory_cache:
        stats['memory'] = _memory_cache.stats()
    return stats
