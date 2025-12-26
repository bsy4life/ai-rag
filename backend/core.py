# core.py - SanShin AI 核心引擎（整合版）
"""
整合功能：
- 三層檢索：關鍵字精確匹配 + BM25 + 向量
- 分層 LLM：複雜問題用 gpt-4o，簡單問題用 gpt-4o-mini
- Reranker 支援：Cohere / 本地模型
- 完整快取：TTL + 持久化
- 成本估算
- 個人知識庫整合
- 智慧型號識別（SMC, VALQUA, 玖基等）
"""

import os
import re
import json
import hashlib
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from threading import Lock
from functools import lru_cache
from enum import Enum

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# AI 業務引擎（純 AI 驅動的 BI 查詢）
# ═══════════════════════════════════════════════════════════════
try:
    from business_ai_engine import get_business_ai_engine
    _HAS_BUSINESS_AI = True
    logger.info("✅ AI 業務引擎已載入")
except ImportError:
    _HAS_BUSINESS_AI = False
    logger.warning("⚠️ business_ai_engine 未載入，將使用傳統規則查詢")

# ═══════════════════════════════════════════════════════════════
# 查詢增強器（多語言術語擴展）
# ═══════════════════════════════════════════════════════════════
try:
    from query_enhancer import enhance_query, EnhancedQuery
    _HAS_QUERY_ENHANCER = True
    logger.info("✅ 查詢增強器已載入")
except ImportError:
    _HAS_QUERY_ENHANCER = False
    logger.warning("⚠️ query_enhancer 未載入，將使用基本查詢擴展")


# ═══════════════════════════════════════════════════════════════
# LLM Provider / .env 相容層（避免 .env 與 config.py 變數名不同步）
# - 你的 .env 目前用 OPENAI_MODEL_* / ANTHROPIC_MODEL_*，但 config.py 讀 LLM_MODEL_*。
# - 這裡在 import config 之前把環境變數補齊，讓 config.py 不用改也能吃到正確模型。
# ═══════════════════════════════════════════════════════════════

def _bootstrap_llm_env() -> None:
    """在 import config 前，把 .env 的變數名做一次『相容化』。

    目標：
    1) 支援 LLM_PROVIDER=openai / anthropic / auto
    2) auto 時，用 LLM_PRIMARY 決定『主要供應商』來填 LLM_MODEL_*
       （避免 config.py 讀到錯的模型）
    3) docker compose up 一眼看得出路由設定
    """
    raw_provider = (os.getenv("LLM_PROVIDER") or os.getenv("AI_PROVIDER") or "").strip().lower()

    # 允許的 provider: openai / anthropic / auto
    if not raw_provider:
        if os.getenv("ANTHROPIC_API_KEY"):
            raw_provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            raw_provider = "openai"
        else:
            raw_provider = "openai"

    # 統一 provider 名稱，但保留 auto
    provider = raw_provider
    if provider in ("claude", "anthropic"):
        provider = "anthropic"
    elif provider in ("openai", "gpt"):
        provider = "openai"
    elif provider == "auto":
        provider = "auto"
    else:
        # 不認識就當 openai（但也會 log 出來方便你抓）
        provider = "openai"

    os.environ["LLM_PROVIDER"] = provider

    def _set_if_missing(k: str, v: str) -> None:
        if v is None:
            return
        v = str(v).strip()
        if v and not os.getenv(k):
            os.environ[k] = v

    def _norm_provider(p: str, default: str) -> str:
        p = (p or default).strip().lower()
        if p in ("claude", "anthropic"):
            return "anthropic"
        if p in ("openai", "gpt"):
            return "openai"
        return default

    # auto 模式下，用 primary 來決定 LLM_MODEL_* 應該填哪一家的模型
    if provider == "auto":
        primary = _norm_provider(os.getenv("LLM_PRIMARY"), "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "openai")
        fallback = _norm_provider(os.getenv("LLM_FALLBACK"), "openai" if primary == "anthropic" else "anthropic")
        os.environ["LLM_PRIMARY"] = primary
        os.environ["LLM_FALLBACK"] = fallback
        provider_for_models = primary
    else:
        provider_for_models = provider

    if provider_for_models == "anthropic":
        default_model = os.getenv("ANTHROPIC_MODEL_DEFAULT", "").strip()
        _set_if_missing("LLM_MODEL_DEFAULT", default_model)
        _set_if_missing("LLM_MODEL_SIMPLE", os.getenv("ANTHROPIC_MODEL_SIMPLE", default_model))
        _set_if_missing("LLM_MODEL_COMPLEX", os.getenv("ANTHROPIC_MODEL_COMPLEX", default_model))
        _set_if_missing("LLM_MODEL_BUSINESS", os.getenv("ANTHROPIC_MODEL_BUSINESS", default_model))
        _set_if_missing("LLM_MODEL_PERSONAL", os.getenv("ANTHROPIC_MODEL_PERSONAL", default_model))
    else:
        default_model = os.getenv("OPENAI_MODEL_DEFAULT", "").strip()
        _set_if_missing("LLM_MODEL_DEFAULT", default_model)
        _set_if_missing("LLM_MODEL_SIMPLE", os.getenv("OPENAI_MODEL_SIMPLE", default_model))
        _set_if_missing("LLM_MODEL_COMPLEX", os.getenv("OPENAI_MODEL_COMPLEX", default_model))
        _set_if_missing("LLM_MODEL_BUSINESS", os.getenv("OPENAI_MODEL_BUSINESS", default_model))
        _set_if_missing("LLM_MODEL_PERSONAL", os.getenv("OPENAI_MODEL_PERSONAL", default_model))

    # 啟動時印一次路由總表（docker compose up 會看到）
    logger.info(
        "🤖 LLM 路由: provider=%s primary=%s fallback=%s | default=%s | simple=%s | complex=%s | business=%s | personal=%s",
        os.getenv("LLM_PROVIDER"),
        os.getenv("LLM_PRIMARY", "-"),
        os.getenv("LLM_FALLBACK", "-"),
        os.getenv("LLM_MODEL_DEFAULT"),
        os.getenv("LLM_MODEL_SIMPLE"),
        os.getenv("LLM_MODEL_COMPLEX"),
        os.getenv("LLM_MODEL_BUSINESS"),
        os.getenv("LLM_MODEL_PERSONAL"),
    )
_bootstrap_llm_env()

# ═══════════════════════════════════════════════════════════════
# 配置導入
# ═══════════════════════════════════════════════════════════════

from config import (
    EMBEDDING_MODEL, LLM_CONFIGS, RETRIEVER_CONFIGS,
    PROMPTS, RERANKER_CONFIG, CACHE_CONFIG, SOURCE_TRACKING,
    KEYWORD_PATTERNS, CHINESE_STOPWORDS, COMPLEXITY_THRESHOLDS,
    COMPARISON_KEYWORDS, ANALYSIS_KEYWORDS,
    VECTOR_DB_DIR, BUSINESS_CSV_FILE, MARKDOWN_DIR,
    get_llm_config, get_retriever_config,
)

# ═══════════════════════════════════════════════════════════════
# 資料結構
# ═══════════════════════════════════════════════════════════════

class DocumentType(Enum):
    TECHNICAL = "technical"
    BUSINESS = "business"
    PERSONAL = "personal"
    MIXED = "mixed"

@dataclass
class SearchResult:
    """搜尋結果"""
    content: str
    source: str
    doc_type: str
    score: float = 0.0
    metadata: Dict = field(default_factory=dict)

@dataclass
class QueryResult:
    """查詢結果"""
    answer: str
    sources: List[str]
    source_type: str
    images: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    cost_estimate: Dict = field(default_factory=dict)
    from_cache: bool = False

# ═══════════════════════════════════════════════════════════════
# 產品型號識別（針對三信產品優化）
# ═══════════════════════════════════════════════════════════════

# SMC 產品型號
SMC_PATTERNS = [
    r'(?:^|\s)(MXJ\d+[A-Z]*[-\d]*)',
    r'(?:^|\s)(MXH\d+[A-Z]*[-\d]*)',
    r'(?:^|\s)(MXP\d+[A-Z]*[-\d]*)',
    r'(?:^|\s)(LES[A-Z]*\d*[-\d]*)',
    r'(?:^|\s)(LEHZ[A-Z]*\d*[-\d]*)',
    r'(?:^|\s)(LEHF\d+[A-Z]*[-\d]*)',
    r'(?:^|\s)(ACG[A-Z]*\d*[-\d]*)',
    r'(?:^|\s)(ARG[A-Z]*\d*[-\d]*)',
]

# VALQUA (華爾卡) 產品型號
VALQUA_PATTERNS = [
    r'(?:バルカー\s*)?No\.\s*(\d{4}[A-Z]*)',
    r'(?:バルカー\s*)?No\.\s*([A-Z]+\d+)',
    r'(?:VALQUA|華爾卡)\s*No\.\s*(\d+)',
    r'No\.\s*(\d{4,})',
]

# 玖基/協鋼 油封
SEAL_PATTERNS = [
    r'(?:^|\s)(G[Ff][Oo][-\s]?\d+[A-Z]*)',
    r'(?:^|\s)(Gf[il][-\s]?\d*[A-Z]*)',
]

def extract_product_models(content: str) -> Dict[str, List[str]]:
    """從內容中提取產品型號，按品牌分類"""
    results = {'smc': [], 'valqua': [], 'seal': [], 'other': []}
    
    for pattern in SMC_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        results['smc'].extend(matches)
    
    for pattern in VALQUA_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        results['valqua'].extend([f"No.{m}" if not m.startswith('No.') else m for m in matches])
    
    for pattern in SEAL_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        results['seal'].extend(matches)
    
    # 去重
    for key in results:
        results[key] = list(set(results[key]))
    
    return results

def expand_technical_query(query: str) -> str:
    """擴展技術查詢，增加同義詞和品牌關鍵字"""
    expanded = query
    products = extract_product_models(query)
    
    # SMC 產品擴展
    if products.get('smc'):
        expanded += " SMC 氣缸 電動致動器 空壓"
    
    # VALQUA 產品擴展
    if products.get('valqua'):
        expanded += " VALQUA 華爾卡 墊片 バルカー gasket"
    
    # 油封產品擴展
    if products.get('seal'):
        expanded += " 玖基 協鋼 油封 seal"
    
    # 關鍵字同義詞
    synonyms = {
        '規格': '仕様 spec specification',
        '安裝': '取付 install mounting 設置',
        '尺寸': '寸法 dimension size',
        '墊片': 'gasket ガスケット',
        '材質': '材料 material',
        '耐熱': '耐熱性 heat resistant',
    }
    
    for key, syns in synonyms.items():
        if key in query:
            expanded += f" {syns}"
    
    return expanded

def identify_product_brand(model: str) -> Tuple[str, str]:
    """識別產品品牌和類別"""
    model_upper = model.upper()
    
    if model_upper.startswith(('MXJ', 'MXH', 'MXP')):
        return 'SMC', '氣缸'
    if model_upper.startswith(('LES', 'LEH')):
        return 'SMC', '電動致動器'
    if model_upper.startswith(('ACG', 'ARG', 'AWG')):
        return 'SMC', '濾清器/調壓閥'
    if 'NO.' in model_upper:
        return 'VALQUA', '墊片/填料'
    if model_upper.startswith('GF'):
        return '玖基', '油封'
    
    return 'Unknown', 'Unknown'

# ═══════════════════════════════════════════════════════════════
# 查詢分類器
# ═══════════════════════════════════════════════════════════════

class QueryClassifier:
    """查詢類型分類器"""
    
    BUSINESS_KEYWORDS = [
        '客戶', '業務', '拜訪', '送貨', '訂單', '營業所',
        '活動', '日報', '統計', '業績', '業務員',
    ]
    
    TECHNICAL_KEYWORDS = [
        '規格', '型號', '產品', '安裝', '維修', '故障',
        '氣缸', '油壓', '墊片', '電磁閥', 'SMC', 'YUKEN',
        'VALQUA', '華爾卡', 'No.', '玖基', '協鋼',
    ]
    
    @classmethod
    def classify_query(cls, query: str) -> DocumentType:
        """分類查詢類型"""
        query_lower = query.lower()
        
        biz_score = sum(1 for kw in cls.BUSINESS_KEYWORDS if kw in query)
        tech_score = sum(1 for kw in cls.TECHNICAL_KEYWORDS if kw.lower() in query_lower)
        
        # 產品型號檢測
        products = extract_product_models(query)
        if any(products.values()):
            tech_score += 3
        
        if biz_score > tech_score:
            return DocumentType.BUSINESS
        elif tech_score > 0:
            return DocumentType.TECHNICAL
        else:
            return DocumentType.MIXED

# ═══════════════════════════════════════════════════════════════
# 複雜度評估
# ═══════════════════════════════════════════════════════════════

def estimate_complexity(query: str, doc_count: int = 0) -> str:
    """評估查詢複雜度，決定使用哪個 LLM"""
    is_complex = False
    
    # 問題長度
    if len(query) > COMPLEXITY_THRESHOLDS.get("query_length", 100):
        is_complex = True
    
    # 多產品比較
    products = extract_product_models(query)
    total_products = sum(len(v) for v in products.values())
    if total_products >= COMPLEXITY_THRESHOLDS.get("model_count", 2):
        is_complex = True
    
    # 比較類問題
    if any(kw in query for kw in COMPARISON_KEYWORDS):
        is_complex = True
    
    # 分析類問題
    if any(kw in query for kw in ANALYSIS_KEYWORDS):
        is_complex = True
    
    # 文檔數量多
    if doc_count > COMPLEXITY_THRESHOLDS.get("doc_count", 5):
        is_complex = True
    
    return "complex" if is_complex else "simple"

# ═══════════════════════════════════════════════════════════════
# 關鍵字索引（精確匹配層）
# ═══════════════════════════════════════════════════════════════

class KeywordIndex:
    """倒排關鍵字索引，用於精確匹配"""
    
    def __init__(self, index_path: str = None):
        self.index: Dict[str, List[Tuple[str, float]]] = {}
        self.doc_keywords: Dict[str, List[str]] = {}
        self.index_path = index_path
        self._lock = Lock()
        
        if index_path and os.path.exists(index_path):
            self.load()
    
    def add_document(self, doc_id: str, text: str, weight: float = 1.0):
        """添加文件到索引"""
        keywords = self._extract_keywords(text)
        
        with self._lock:
            self.doc_keywords[doc_id] = keywords
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower not in self.index:
                    self.index[kw_lower] = []
                
                existing = [i for i, (d, _) in enumerate(self.index[kw_lower]) if d == doc_id]
                if existing:
                    self.index[kw_lower][existing[0]] = (doc_id, weight)
                else:
                    self.index[kw_lower].append((doc_id, weight))
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取關鍵字"""
        keywords = set()
        
        # 使用配置的正則模式
        for pattern in KEYWORD_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            keywords.update(m.upper() if len(m) <= 10 else m for m in matches)
        
        # 中文詞彙
        chinese = re.findall(r'[\u4e00-\u9fa5]{2,6}', text)
        keywords.update(w for w in chinese if w not in CHINESE_STOPWORDS)
        
        # 產品型號
        products = extract_product_models(text)
        for brand_products in products.values():
            keywords.update(brand_products)
        
        return list(keywords)
    
    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """搜尋關鍵字"""
        query_keywords = self._extract_keywords(query)
        query_words = set(query.lower().split())
        all_terms = set(kw.lower() for kw in query_keywords) | query_words
        
        doc_scores: Dict[str, float] = {}
        
        for term in all_terms:
            # 精確匹配（權重 2）
            if term in self.index:
                for doc_id, weight in self.index[term]:
                    doc_scores[doc_id] = doc_scores.get(doc_id, 0) + 2 * weight
            
            # 部分匹配（權重 1）
            for indexed_kw, doc_list in self.index.items():
                if len(term) >= 3 and (term in indexed_kw or indexed_kw in term):
                    for doc_id, weight in doc_list:
                        doc_scores[doc_id] = doc_scores.get(doc_id, 0) + weight
        
        results = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]
    
    def save(self):
        """儲存索引"""
        if self.index_path:
            try:
                os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
                with self._lock:
                    data = {
                        "index": {k: list(v) for k, v in self.index.items()},
                        "doc_keywords": self.doc_keywords,
                    }
                    with open(self.index_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"儲存關鍵字索引失敗: {e}")
    
    def load(self):
        """載入索引"""
        if self.index_path and os.path.exists(self.index_path):
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.index = {k: [tuple(x) for x in v] for k, v in data.get("index", {}).items()}
                    self.doc_keywords = data.get("doc_keywords", {})
            except Exception as e:
                logger.warning(f"載入關鍵字索引失敗: {e}")

# ═══════════════════════════════════════════════════════════════
# 查詢快取
# ═══════════════════════════════════════════════════════════════

class QueryCache:
    """查詢快取（支援 TTL 和持久化）"""
    
    def __init__(self, config=CACHE_CONFIG):
        self.config = config
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = Lock()
        
        if config.backend == "file" and config.file_path:
            os.makedirs(os.path.dirname(config.file_path), exist_ok=True)
            self._load_file_cache()
    
    def _make_key(self, query: str, mode: str, user_id: str = "") -> str:
        return hashlib.md5(f"{query}:{mode}:{user_id}".encode()).hexdigest()
    
    def get(self, query: str, mode: str, user_id: str = "") -> Optional[QueryResult]:
        if not self.config.enabled:
            return None
        
        key = self._make_key(query, mode, user_id)
        
        with self._lock:
            if key in self.cache:
                result, timestamp = self.cache[key]
                if datetime.now().timestamp() - timestamp < self.config.ttl:
                    result.from_cache = True
                    return result
                else:
                    del self.cache[key]
        
        return None
    
    def set(self, query: str, mode: str, result: QueryResult, user_id: str = ""):
        if not self.config.enabled:
            return
        
        key = self._make_key(query, mode, user_id)
        
        with self._lock:
            if len(self.cache) >= self.config.max_size:
                oldest = min(self.cache.items(), key=lambda x: x[1][1])
                del self.cache[oldest[0]]
            
            self.cache[key] = (result, datetime.now().timestamp())
        
        if self.config.backend == "file":
            self._save_file_cache()
    
    def _load_file_cache(self):
        if os.path.exists(self.config.file_path):
            try:
                with open(self.config.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, item in data.items():
                        if isinstance(item, list) and len(item) == 2:
                            result_dict, ts = item
                            self.cache[key] = (QueryResult(**result_dict), ts)
            except Exception as e:
                logger.warning(f"載入快取失敗: {e}")
    
    def _save_file_cache(self):
        try:
            data = {}
            for key, (result, ts) in self.cache.items():
                data[key] = [asdict(result), ts]
            with open(self.config.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"儲存快取失敗: {e}")
    
    def clear(self):
        with self._lock:
            self.cache.clear()
        if self.config.backend == "file" and os.path.exists(self.config.file_path):
            try:
                os.remove(self.config.file_path)
            except:
                pass

# ═══════════════════════════════════════════════════════════════
# Reranker（結果重排）
# ═══════════════════════════════════════════════════════════════

class Reranker:
    """結果重排器（Cohere / 本地模型）"""
    
    def __init__(self):
        self._reranker = None
        self._type = None
        self._init_reranker()
    
    def _init_reranker(self):
        if not RERANKER_CONFIG.enabled:
            logger.info("Reranker 未啟用")
            return
        
        if RERANKER_CONFIG.type == "cohere":
            try:
                from langchain_cohere import CohereRerank
                api_key = os.getenv(RERANKER_CONFIG.cohere_api_key_env)
                if api_key:
                    self._reranker = CohereRerank(
                        model=RERANKER_CONFIG.cohere_model,
                        top_n=RERANKER_CONFIG.top_n
                    )
                    self._type = "cohere"
                    logger.info("✅ Cohere Reranker 已啟用")
                else:
                    logger.warning("Cohere API Key 未設定")
            except ImportError:
                logger.warning("需要安裝 langchain-cohere: pip install langchain-cohere")
        
        elif RERANKER_CONFIG.type == "local":
            try:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(RERANKER_CONFIG.local_model)
                self._type = "local"
                logger.info(f"✅ 本地 Reranker 已啟用: {RERANKER_CONFIG.local_model}")
            except ImportError:
                logger.warning("需要安裝 sentence-transformers")
    
    def rerank(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        """重排結果"""
        if not results:
            return results
        
        if not self._reranker:
            return results[:RERANKER_CONFIG.top_n]
        
        try:
            if self._type == "cohere":
                from langchain_core.documents import Document
                docs = [Document(page_content=r.content, metadata=r.metadata) for r in results]
                reranked_docs = self._reranker.compress_documents(docs, query)
                
                reranked = []
                for doc in reranked_docs[:RERANKER_CONFIG.top_n]:
                    for r in results:
                        if r.content == doc.page_content:
                            reranked.append(r)
                            break
                return reranked
            
            else:  # local
                pairs = [(query, r.content) for r in results]
                scores = self._reranker.predict(pairs)
                
                scored = list(zip(results, scores))
                scored.sort(key=lambda x: x[1], reverse=True)
                
                return [r for r, _ in scored[:RERANKER_CONFIG.top_n]]
        
        except Exception as e:
            logger.warning(f"Rerank 失敗: {e}")
            return results[:RERANKER_CONFIG.top_n]

# ═══════════════════════════════════════════════════════════════
# 主要 RAG 引擎
# ═══════════════════════════════════════════════════════════════

class CategorizedQASystem:
    """三新 AI 問答系統（整合版）"""
    
    def __init__(self):
        self._lock = Lock()
        self._initialized = False
        
        # 組件
        self._vectordb = None
        self._bm25 = None
        self._keyword_index = None
        self._llm_cache = {}
        
        # 快取和重排
        self.cache = QueryCache()
        self.reranker = Reranker()
        
        # 個人知識庫
        self._personal_kb_module = None
        self._load_personal_kb_module()
        
        # 業務查詢
        self._business_module = None
        self._load_business_module()
        
        # 統計
        self.doc_count = 0
        self.file_count = 0
        
        # 初始化
        self.initialize()
    
    def _load_personal_kb_module(self):
        """載入個人知識庫模組"""
        try:
            from personal_kb import get_personal_kb, search_personal
            self._personal_kb_module = {
                'get_kb': get_personal_kb,
                'search': search_personal,
            }
            logger.info("✅ 個人知識庫模組已載入")
        except ImportError as e:
            logger.warning(f"個人知識庫模組未載入: {e}")
    
    def _load_business_module(self):
        """載入業務查詢模組"""
        try:
            from business_csv import _direct_business_query_text
            self._business_module = {
                'query': _direct_business_query_text,
            }
            logger.info("✅ 業務查詢模組已載入")
        except ImportError as e:
            logger.warning(f"業務查詢模組未載入: {e}")
    
    def initialize(self):
        """初始化系統"""
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            logger.info("🔧 初始化 RAG 引擎...")
            
            try:
                self._init_vectordb()
                self._init_bm25()
                self._init_keyword_index()
                
                self._initialized = True
                logger.info("✅ RAG 引擎初始化完成")
                
            except Exception as e:
                logger.error(f"❌ RAG 引擎初始化失敗: {e}")
    
    def _init_vectordb(self):
        """初始化向量庫（自動從 markdown 目錄建立，支援增量更新）"""
        try:
            from langchain_chroma import Chroma
            from langchain_openai import OpenAIEmbeddings
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            from langchain_core.documents import Document
            
            embedding = OpenAIEmbeddings(model=EMBEDDING_MODEL)
            
            os.makedirs(VECTOR_DB_DIR, exist_ok=True)
            
            self._vectordb = Chroma(
                persist_directory=VECTOR_DB_DIR,
                embedding_function=embedding,
                collection_name="tech_docs",
            )
            
            self.doc_count = self._vectordb._collection.count()
            
            # 檢查是否需要更新向量庫
            if os.path.exists(MARKDOWN_DIR):
                if self.doc_count == 0:
                    # 向量庫為空，完全重建
                    logger.info(f"📂 向量庫為空，開始從 {MARKDOWN_DIR} 建立...")
                    self._build_vectordb_from_markdown(embedding)
                    self.doc_count = self._vectordb._collection.count()
                else:
                    # 向量庫不為空，檢查是否有新檔案需要加入
                    self._sync_vectordb_with_markdown(embedding)
                    self.doc_count = self._vectordb._collection.count()
            
            self.file_count = self.doc_count
            logger.info(f"📚 向量庫已載入: {self.doc_count} 文檔")
            
        except Exception as e:
            logger.error(f"向量庫初始化失敗: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _sync_vectordb_with_markdown(self, embedding):
        """同步向量庫與 markdown 目錄（增量更新）"""
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        from langchain_core.documents import Document
        
        # 取得向量庫中已有的檔案
        try:
            existing_data = self._vectordb.get()
            existing_sources = set()
            if existing_data and existing_data.get('metadatas'):
                for meta in existing_data['metadatas']:
                    if meta and meta.get('source'):
                        existing_sources.add(meta['source'])
        except Exception as e:
            logger.warning(f"無法讀取現有向量庫: {e}")
            existing_sources = set()
        
        # 取得 markdown 目錄中的檔案
        markdown_files = set()
        for filename in os.listdir(MARKDOWN_DIR):
            if filename.endswith(('.md', '.txt', '.markdown')):
                markdown_files.add(filename)
        
        # 找出需要新增的檔案
        new_files = markdown_files - existing_sources
        
        if not new_files:
            logger.info("📚 向量庫已是最新，無需更新")
            return
        
        logger.info(f"📂 發現 {len(new_files)} 個新檔案需要加入向量庫")
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,      # 增加到 1000，保留完整段落
            chunk_overlap=150,    # 增加重疊
            separators=[
                "\n## ", "\n### ", "\n#### ",
                "\n第 ", "\n一、", "\n二、", "\n三、", "\n四、", "\n五、",
                "\n\n", "\n", "。", ".", " "
            ]
        )
        
        all_docs = []
        
        for filename in new_files:
            filepath = os.path.join(MARKDOWN_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if not content.strip():
                    continue
                
                chunks = text_splitter.split_text(content)
                
                for i, chunk in enumerate(chunks):
                    doc = Document(
                        page_content=chunk,
                        metadata={
                            "source": filename,
                            "chunk_idx": i,
                            "doc_type": "technical"
                        }
                    )
                    all_docs.append(doc)
                
                logger.info(f"  📄 {filename}: {len(chunks)} chunks")
                
            except Exception as e:
                logger.error(f"  ❌ 讀取 {filename} 失敗: {e}")
        
        if all_docs:
            # 分批處理，每批 500 個 chunks
            batch_size = 500
            total = len(all_docs)
            logger.info(f"📤 開始 embedding {total} 個新 chunks...")
            
            for i in range(0, total, batch_size):
                batch = all_docs[i:i + batch_size]
                self._vectordb.add_documents(batch)
            
            logger.info(f"✅ 增量更新完成: 新增 {total} chunks")
    
    def _build_vectordb_from_markdown(self, embedding):
        """從 markdown 目錄建立向量庫"""
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        from langchain_core.documents import Document
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,      # 增加到 1000，保留完整段落
            chunk_overlap=150,    # 增加重疊
            separators=[
                "\n## ", "\n### ", "\n#### ",
                "\n第 ", "\n一、", "\n二、", "\n三、", "\n四、", "\n五、",
                "\n\n", "\n", "。", ".", " "
            ]
        )
        
        all_docs = []
        
        for filename in os.listdir(MARKDOWN_DIR):
            if not filename.endswith(('.md', '.txt', '.markdown')):
                continue
            
            filepath = os.path.join(MARKDOWN_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if not content.strip():
                    continue
                
                chunks = text_splitter.split_text(content)
                
                for i, chunk in enumerate(chunks):
                    doc = Document(
                        page_content=chunk,
                        metadata={
                            "source": filename,
                            "chunk_idx": i,
                            "doc_type": "technical"
                        }
                    )
                    all_docs.append(doc)
                
                logger.info(f"  📄 {filename}: {len(chunks)} chunks")
                
            except Exception as e:
                logger.error(f"  ❌ 讀取 {filename} 失敗: {e}")
        
        if all_docs:
            # 分批處理，每批 500 個 chunks（避免超過 OpenAI token 限制）
            batch_size = 500
            total = len(all_docs)
            logger.info(f"📤 開始 embedding {total} 個 chunks（分 {(total + batch_size - 1) // batch_size} 批）...")
            
            for i in range(0, total, batch_size):
                batch = all_docs[i:i + batch_size]
                batch_num = i // batch_size + 1
                logger.info(f"  📦 處理第 {batch_num} 批: {len(batch)} chunks...")
                self._vectordb.add_documents(batch)
            
            logger.info(f"✅ 向量庫建立完成: {total} chunks")
    
    def _init_bm25(self):
        """初始化 BM25 檢索器"""
        try:
            from langchain_community.retrievers import BM25Retriever
            
            if self._vectordb:
                docs = self._vectordb.get()
                if docs and docs.get('documents'):
                    from langchain_core.documents import Document
                    bm25_docs = [
                        Document(page_content=d, metadata=m or {})
                        for d, m in zip(
                            docs['documents'], 
                            docs.get('metadatas', [{}] * len(docs['documents']))
                        )
                    ]
                    self._bm25 = BM25Retriever.from_documents(bm25_docs)
                    self._bm25.k = 10
                    logger.info(f"📚 BM25 檢索器已建立: {len(bm25_docs)} 文檔")
        except ImportError:
            logger.warning("BM25 未啟用（需要 rank_bm25）")
        except Exception as e:
            logger.warning(f"BM25 初始化失敗: {e}")
    
    def _init_keyword_index(self):
        """初始化關鍵字索引"""
        index_path = os.path.join(VECTOR_DB_DIR, "keyword_index.json")
        self._keyword_index = KeywordIndex(index_path)
        
        # 如果索引為空，從向量庫建立
        if not self._keyword_index.index and self._vectordb:
            try:
                docs = self._vectordb.get()
                if docs and docs.get('documents'):
                    for i, (doc_id, content) in enumerate(zip(
                        docs.get('ids', []),
                        docs['documents']
                    )):
                        self._keyword_index.add_document(doc_id, content)
                    self._keyword_index.save()
                    logger.info(f"📚 關鍵字索引已建立: {len(docs['documents'])} 文檔")
            except Exception as e:
                logger.warning(f"建立關鍵字索引失敗: {e}")
    @lru_cache(maxsize=12)
    def _get_llm(self, model: str, temperature: float = 0.1, max_tokens: Optional[int] = None):
        """取得 LLM（快取）

        需求：
        - 支援 LLM_PROVIDER=openai / anthropic / auto
        - auto 時：先走 primary，失敗再走 fallback
        - 每次選 LLM 都會在 docker compose log 印『走哪一條』與 model
        """

        def _infer_slot(m: str) -> str:
            # 盡量把當前 model 對應到哪個用途，讓 fallback 也能用同一用途的 model
            mapping = [
                ("COMPLEX", os.getenv("LLM_MODEL_COMPLEX")),
                ("SIMPLE", os.getenv("LLM_MODEL_SIMPLE")),
                ("BUSINESS", os.getenv("LLM_MODEL_BUSINESS")),
                ("PERSONAL", os.getenv("LLM_MODEL_PERSONAL")),
                ("DEFAULT", os.getenv("LLM_MODEL_DEFAULT")),
            ]
            for slot, mv in mapping:
                if mv and m == mv:
                    return slot
            return "DEFAULT"

        def _pick_model_for(provider_name: str, slot: str, primary_model: str) -> str:
            # primary 用傳進來的 model；fallback 依 slot 取對應家的 model
            if provider_name == "anthropic":
                return (
                    os.getenv(f"ANTHROPIC_MODEL_{slot}")
                    or os.getenv("ANTHROPIC_MODEL_DEFAULT")
                    or primary_model
                ).strip()
            return (
                os.getenv(f"OPENAI_MODEL_{slot}")
                or os.getenv("OPENAI_MODEL_DEFAULT")
                or primary_model
            ).strip()

        def _build(provider_name: str, model_name: str):
            # 檢測是否為 o 系列推理模型（o1, o3, gpt-5 等）
            model_lower = model_name.lower()
            is_reasoning_model = any(x in model_lower for x in ['o1', 'o3', 'gpt-5', 'o4'])
            
            if provider_name == "anthropic":
                try:
                    from langchain_anthropic import ChatAnthropic
                except Exception as e:
                    raise RuntimeError("找不到 langchain_anthropic，請在 requirements 安裝 langchain-anthropic") from e

                logger.info("🧠 LLM 選擇: provider=anthropic model=%s temperature=%s", model_name, temperature)
                kwargs = {"model": model_name, "temperature": temperature}
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                return ChatAnthropic(**kwargs)

            # default openai
            try:
                from langchain_openai import ChatOpenAI
            except Exception as e:
                raise RuntimeError("找不到 langchain_openai，請在 requirements 安裝 langchain-openai") from e

            logger.info("🧠 LLM 選擇: provider=openai model=%s temperature=%s reasoning=%s", model_name, temperature, is_reasoning_model)
            
            if is_reasoning_model:
                # o 系列模型不支援 temperature 和 max_tokens
                # 使用 model_kwargs 傳遞 max_completion_tokens
                kwargs = {"model": model_name}
                if max_tokens is not None:
                    kwargs["model_kwargs"] = {"max_completion_tokens": max_tokens}
            else:
                kwargs = {"model": model_name, "temperature": temperature}
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
            
            return ChatOpenAI(**kwargs)

        provider = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
        # 允許你 .env 寫 claude
        if provider == "claude":
            provider = "anthropic"

        slot = _infer_slot(model)

        if provider == "auto":
            primary = (os.getenv("LLM_PRIMARY") or "anthropic").strip().lower()
            fallback = (os.getenv("LLM_FALLBACK") or "openai").strip().lower()
            if primary == "claude":
                primary = "anthropic"
            if fallback == "claude":
                fallback = "anthropic"

            primary_model = _pick_model_for(primary, slot, model)
            fallback_model = _pick_model_for(fallback, slot, model)

            logger.info(
                "🧭 LLM AUTO: slot=%s primary=%s(%s) fallback=%s(%s)",
                slot, primary, primary_model, fallback, fallback_model
            )

            try:
                llm = _build(primary, primary_model)
                logger.info("✅ LLM AUTO 命中: primary=%s model=%s", primary, primary_model)
                return llm
            except Exception as e:
                logger.warning("⚠️ LLM AUTO primary 失敗，改走 fallback。primary=%s err=%s", primary, repr(e))
                llm = _build(fallback, fallback_model)
                logger.info("✅ LLM AUTO 命中: fallback=%s model=%s", fallback, fallback_model)
                return llm

        # 非 auto：直接依 provider 建立
        if provider in ("anthropic", "openai"):
            model_name = _pick_model_for(provider, slot, model) if provider != "openai" else model
            # 注意：openai 的 model 直接用傳進來的（已由 config / LLM_MODEL_* 決定）
            return _build(provider, model_name)

        # 不認識就當 openai（但也會印出來）
        logger.warning("Unknown LLM_PROVIDER=%s, fallback to openai", provider)
        return _build("openai", model)
    
    def _search(
        self,
        query: str,
        doc_type: str = "technical",
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        增強版三層檢索：查詢增強 + 關鍵字 + BM25 + 向量
        
        新功能：
        - 使用 AI 查詢增強器進行多語言擴展
        - 對多個查詢變體進行搜索
        - 合併去重後排序
        """
        results: List[SearchResult] = []
        seen_contents = set()
        
        # 使用查詢增強器（如果可用）
        search_queries = [query]
        enhanced = None
        
        if doc_type == "technical" and _HAS_QUERY_ENHANCER:
            try:
                # 使用 LLM 增強（可配置關閉）
                use_llm = os.getenv("QUERY_ENHANCE_LLM", "true").lower() == "true"
                enhanced = enhance_query(query, use_llm=use_llm)
                
                # 獲取所有查詢變體（限制數量避免太慢）
                all_queries = enhanced.get_all_queries()
                search_queries = all_queries[:5]  # 最多 5 個變體
                
                logger.info(f"🔍 查詢增強: {len(search_queries)} 個變體")
                
            except Exception as e:
                logger.warning(f"查詢增強失敗，使用原始查詢: {e}")
                search_queries = [expand_technical_query(query)]
        else:
            # 降級到舊的擴展方式
            if doc_type == "technical":
                search_queries = [expand_technical_query(query)]
        
        # 對每個查詢變體進行搜索
        for search_query in search_queries:
            # 1. 關鍵字精確匹配（只對原始查詢和產品型號）
            if self._keyword_index and self._keyword_index.index:
                kw_results = self._keyword_index.search(search_query, top_k=top_k)
                for doc_id, score in kw_results:
                    try:
                        doc_data = self._vectordb._collection.get(ids=[doc_id])
                        if doc_data['documents']:
                            content = doc_data['documents'][0]
                            content_hash = hash(content[:200])
                            if content_hash not in seen_contents:
                                # 產品型號精確匹配加分
                                bonus = 1.0
                                if enhanced and enhanced.extracted_models:
                                    for model in enhanced.extracted_models:
                                        if model.upper() in content.upper():
                                            bonus = 2.0
                                            break
                                
                                results.append(SearchResult(
                                    content=content,
                                    source=doc_data['metadatas'][0].get('source', '') if doc_data['metadatas'] else '',
                                    doc_type=doc_type,
                                    score=score * 2 * bonus,
                                    metadata={"match_type": "keyword", "doc_id": doc_id}
                                ))
                                seen_contents.add(content_hash)
                    except:
                        pass
            
            # 2. BM25 搜尋
            if self._bm25:
                try:
                    bm25_docs = self._bm25.invoke(search_query)
                    for doc in bm25_docs[:top_k]:
                        content_hash = hash(doc.page_content[:200])
                        if content_hash not in seen_contents:
                            results.append(SearchResult(
                                content=doc.page_content,
                                source=doc.metadata.get("source", ""),
                                doc_type=doc_type,
                                score=1.5,
                                metadata={"match_type": "bm25", "query_variant": search_query[:50]}
                            ))
                            seen_contents.add(content_hash)
                except Exception as e:
                    logger.warning(f"BM25 搜尋失敗: {e}")
            
            # 3. 向量搜尋
            if self._vectordb:
                try:
                    config = get_retriever_config(doc_type)
                    vector_docs = self._vectordb.similarity_search_with_score(
                        search_query, k=config.k
                    )
                    for doc, score in vector_docs:
                        content_hash = hash(doc.page_content[:200])
                        if content_hash not in seen_contents:
                            results.append(SearchResult(
                                content=doc.page_content,
                                source=doc.metadata.get("source", ""),
                                doc_type=doc_type,
                                score=1.0 / (1.0 + score),
                                metadata={"match_type": "vector", **doc.metadata}
                            ))
                            seen_contents.add(content_hash)
                except Exception as e:
                    logger.warning(f"向量搜尋失敗: {e}")
        
        # 4. Rerank（使用原始查詢）
        if results:
            results = self.reranker.rerank(query, results)
        
        logger.info(f"📊 搜索結果: {len(results)} 筆（去重後）")
        
        return results[:top_k]
    
    def _generate_answer(
        self,
        query: str,
        context: List[SearchResult],
        doc_type: str = "technical",
    ) -> Tuple[str, Dict]:
        """生成回答"""
        # 評估複雜度，選擇 LLM
        complexity = estimate_complexity(query, len(context))
        llm_config = get_llm_config(doc_type, complexity)
        llm = self._get_llm(llm_config.model, llm_config.temperature)
        
        # 準備上下文（清理 HTML 標籤和圖片路徑）
        def clean_content(content: str) -> str:
            """清理文檔內容，移除干擾 LLM 的元素"""
            import re
            # 移除 img 標籤
            content = re.sub(r'<img[^>]*>', '', content)
            # 移除 style 屬性
            content = re.sub(r'\s*style="[^"]*"', '', content)
            # 移除空的 HTML 標籤
            content = re.sub(r'<(\w+)[^>]*>\s*</\1>', '', content)
            # 移除 blockquote 標籤但保留內容
            content = re.sub(r'</?blockquote>', '', content)
            # 移除 table 相關標籤但嘗試保留結構
            content = re.sub(r'</?table[^>]*>', '\n', content)
            content = re.sub(r'</?thead[^>]*>', '', content)
            content = re.sub(r'</?tbody[^>]*>', '', content)
            content = re.sub(r'</?colgroup[^>]*>', '', content)
            content = re.sub(r'<col[^>]*/?>', '', content)
            content = re.sub(r'<tr[^>]*>', '\n', content)
            content = re.sub(r'</tr>', '', content)
            content = re.sub(r'<t[hd][^>]*>', ' | ', content)
            content = re.sub(r'</t[hd]>', '', content)
            # 移除其他常見 HTML 標籤
            content = re.sub(r'</?p>', '\n', content)
            content = re.sub(r'</?div[^>]*>', '\n', content)
            content = re.sub(r'</?span[^>]*>', '', content)
            # 移除連續的 ### 標記
            content = re.sub(r'#{4,}', '', content)
            # 移除圖片路徑
            content = re.sub(r'/home/aiuser/[^\s]+\.(png|jpg|jpeg|gif)', '[圖片]', content)
            # 清理多餘空行
            content = re.sub(r'\n{3,}', '\n\n', content)
            content = re.sub(r'[ \t]+', ' ', content)
            return content.strip()
        
        context_text = "\n\n---\n\n".join([
            f"【來源: {os.path.basename(r.source) if r.source else '未知'}】\n{clean_content(r.content)}"
            for r in context
        ])
        
        # 選擇 Prompt
        prompt_template = PROMPTS.get(doc_type, PROMPTS["technical"])
        prompt = prompt_template.format(context=context_text, input=query)
        
        # 生成回答（帶 fallback）
        used_model = llm_config.model
        try:
            response = llm.invoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            error_msg = str(e)
            # 檢查是否是 API 限額或配額錯誤
            if "usage limits" in error_msg or "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                logger.warning(f"⚠️ LLM 調用失敗（限額），嘗試 fallback: {e}")
                # 嘗試 fallback 到另一個提供商
                try:
                    provider = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
                    if provider == "auto":
                        fallback_provider = (os.getenv("LLM_FALLBACK") or "openai").strip().lower()
                    else:
                        fallback_provider = "openai" if provider in ("anthropic", "claude") else "anthropic"
                    
                    # 選擇 fallback 模型
                    if fallback_provider == "openai":
                        fallback_model = os.getenv("OPENAI_MODEL_COMPLEX", "gpt-4o")
                    else:
                        fallback_model = os.getenv("ANTHROPIC_MODEL_COMPLEX", "claude-sonnet-4-20250514")
                    
                    logger.info(f"🔄 Fallback 到 {fallback_provider}: {fallback_model}")
                    fallback_llm = self._get_llm(fallback_model, llm_config.temperature)
                    response = fallback_llm.invoke(prompt)
                    answer = response.content if hasattr(response, 'content') else str(response)
                    used_model = fallback_model
                    logger.info(f"✅ Fallback 成功: {fallback_provider}")
                except Exception as fallback_e:
                    logger.error(f"❌ Fallback 也失敗: {fallback_e}")
                    answer = f"生成回答時發生錯誤：主要 LLM 限額，備用 LLM 也失敗。請稍後重試。"
            else:
                logger.error(f"LLM 生成失敗: {e}")
                answer = f"生成回答時發生錯誤：{e}"
        
        # 添加來源
        if SOURCE_TRACKING.enabled and SOURCE_TRACKING.show_in_response:
            sources = list(set(
                os.path.basename(r.source) for r in context if r.source
            ))[:SOURCE_TRACKING.max_sources]
            if sources:
                answer += "\n\n---\n📚 **參考來源**：" + "、".join(sources)
        
        # 成本估算
        from config import TOKEN_PRICES
        input_tokens = len(prompt) // 2
        output_tokens = len(answer) // 2
        prices = TOKEN_PRICES.get(llm_config.model, {"input": 0.15, "output": 0.6})
        
        # 🆕 Debug：回傳本次實際使用的 provider / model（方便確認 Claude vs OpenAI）
        used_provider = os.getenv("LLM_PROVIDER", "openai").strip().lower() or "openai"

        cost = {
            "model": llm_config.model,
            "used_provider": used_provider,
            "used_model": llm_config.model,
            "complexity": complexity,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": round(
                (input_tokens / 1_000_000) * prices.get("input", 0.15) +
                (output_tokens / 1_000_000) * prices.get("output", 0.6),
                6
            ),
        }
        
        return answer, cost
    
    def ask(
        self,
        query: str,
        mode: str = "smart",
        user_id: str = "default",
    ) -> Tuple[str, str, Dict]:
        """
        主要問答接口
        
        Args:
            query: 查詢內容
            mode: smart, technical, business, personal
            user_id: 用戶 ID
        
        Returns:
            (answer, source_type, info_dict)
        """
        if not query or not query.strip():
            return "請輸入有效的問題。", "error", {}
        
        query = query.strip()
        
        # 檢查快取
        cached = self.cache.get(query, mode, user_id)
        if cached:
            return cached.answer, cached.source_type, {
                "images": cached.images,
                "sources": cached.sources,
                "cost_estimate": cached.cost_estimate,
                "from_cache": True,
            }
        
        # Smart 模式：先檢查個人知識庫
        if mode == "smart" and user_id and user_id != "default":
            personal_result = self._ask_personal(query, user_id)
            if personal_result and "未找到" not in personal_result[0] and "尚無文件" not in personal_result[0]:
                # 快取結果
                result = QueryResult(
                    answer=personal_result[0],
                    sources=personal_result[2].get("sources", []),
                    source_type="personal",
                    images=personal_result[2].get("images", []),
                )
                self.cache.set(query, mode, result, user_id)
                return personal_result
        
        # 判斷查詢類型
        if mode == "smart":
            doc_type = QueryClassifier.classify_query(query)
        elif mode == "personal":
            return self._ask_personal(query, user_id)
        else:
            doc_type = DocumentType(mode) if mode in ["technical", "business"] else DocumentType.TECHNICAL
        
        # 業務查詢
        if doc_type == DocumentType.BUSINESS:
            return self._ask_business(query)
        
        # 技術查詢：三層檢索
        search_results = self._search(query, doc_type.value)
        
        if not search_results:
            return "未找到相關資料。請嘗試不同的關鍵字。", doc_type.value, {}
        
        # 生成回答
        answer, cost = self._generate_answer(query, search_results, doc_type.value)
        
        info = {
            "sources": [r.source for r in search_results if r.source],
            "cost_estimate": cost,
            "from_cache": False,
        }
        
        # 快取結果
        result = QueryResult(
            answer=answer,
            sources=info["sources"],
            source_type=doc_type.value,
            cost_estimate=cost,
        )
        self.cache.set(query, mode, result, user_id)
        
        return answer, doc_type.value, info
    
    def _ask_business(self, query: str) -> Tuple[str, str, Dict]:
        """
        業務查詢（AI 驅動 + 傳統回退）
        
        模式選擇：
        - BUSINESS_QUERY_MODE=ai  → 使用 AI 引擎（預設）
        - BUSINESS_QUERY_MODE=legacy → 使用傳統規則
        """
        use_ai = os.getenv("BUSINESS_QUERY_MODE", "ai").lower() == "ai"
        
        # 嘗試 AI 模式
        if use_ai and _HAS_BUSINESS_AI:
            try:
                engine = get_business_ai_engine()
                result = engine.query(query)
                
                if result.get("success"):
                    return (
                        result.get("answer", "查詢完成"),
                        "business",
                        {
                            "sources": ["business_ai"],
                            "insights": result.get("insights", []),
                            "recommendations": result.get("recommendations", []),
                            "visualizations": result.get("visualizations", []),
                            "data_summary": result.get("data_summary", {}),
                        }
                    )
                else:
                    # AI 返回失敗，回退到傳統
                    logger.warning("AI 業務查詢返回失敗，嘗試傳統方式")
            except Exception as e:
                logger.error(f"AI 業務查詢異常: {e}，回退到傳統方式")
        
        # 傳統模式（回退）
        return self._ask_business_legacy(query)
    
    def _ask_business_legacy(self, query: str) -> Tuple[str, str, Dict]:
        """業務查詢 - 傳統規則版本"""
        if not self._business_module:
            return "業務查詢模組未載入。", "error", {}
        
        try:
            answer = self._business_module['query'](query)
            if answer:
                return answer, "business", {"sources": ["business_csv"]}
            else:
                return "未找到符合條件的業務記錄。", "business", {}
        except Exception as e:
            logger.error(f"業務查詢失敗: {e}")
            return f"業務查詢失敗：{e}", "error", {}
    
    def _ask_personal(self, query: str, user_id: str) -> Tuple[str, str, Dict]:
        """個人知識庫查詢"""
        if not self._personal_kb_module:
            return "個人知識庫功能未啟用。", "error", {}
        
        try:
            kb = self._personal_kb_module['get_kb'](user_id)
            
            # 檢查是否有文件
            stats = kb.metadata.get("stats", {})
            if stats.get("total_documents", 0) == 0:
                return "您的個人知識庫尚無文件。請先上傳文件。", "personal", {}
            
            # 搜尋
            results = self._personal_kb_module['search'](user_id, query, top_k=5)
            
            if not results:
                return "在個人知識庫中未找到相關內容。", "personal", {}
            
            # 組裝結果
            all_images = []
            context_parts = []
            
            for r in results:
                context_parts.append(f"【{r.filename}】\n{r.content}")
                
                for img in getattr(r, 'images', [])[:2]:
                    all_images.append({
                        "doc_id": r.doc_id,
                        "filename": r.filename,
                        "image_name": img.get("name"),
                        "url": f"/kb/personal/{user_id}/images/{r.doc_id}/{img.get('name')}",
                    })

            # 🧠 圖片回傳策略：只有「需要圖」才回傳，避免像查分機表卻被塞圖
            def _should_return_images(q: str) -> bool:
                q = (q or "").lower()
                keywords = [
                    "圖", "圖片", "截圖", "畫面", "介面", "畫面長什麼樣", "示意", "範例", "步驟", "設定", "怎麼做",
                    "screenshot", "image", "diagram", "ui", "gui",
                ]
                return any(k.lower() in q for k in keywords)

            return_images = bool(all_images) and _should_return_images(query)
            
            # 生成回答
            context = "\n\n---\n\n".join(context_parts)
            # 🆕 Personal KB 目前沿用既有預設模型；並回傳 used_provider/used_model 供前端顯示
            personal_model = os.getenv("LLM_MODEL_PERSONAL", "gpt-4o-mini").strip() or "gpt-4o-mini"
            used_provider = os.getenv("LLM_PROVIDER", "openai").strip().lower() or "openai"

            llm = self._get_llm(personal_model, 0.1)
            
            prompt = PROMPTS.get("personal", PROMPTS["technical"]).format(
                context=context, input=query
            )
            response = llm.invoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
            
            if return_images:
                answer += f"\n\n📷 找到 {len(all_images)} 張相關圖片。"
            
            return answer, "personal", {
                "sources": [r.filename for r in results],
                "images": all_images if return_images else [],
                "used_provider": used_provider,
                "used_model": personal_model,
            }
            
        except Exception as e:
            logger.error(f"個人知識庫查詢失敗: {e}")
            return f"查詢失敗：{e}", "error", {}
    
    def reload(self) -> bool:
        """重新載入系統"""
        with self._lock:
            self._initialized = False
            self._vectordb = None
            self._bm25 = None
            self._keyword_index = None
            self._get_llm.cache_clear()
        
        self.initialize()
        self.cache.clear()
        logger.info("✅ 系統已重新載入")
        return True
    
    def get_stats(self) -> Dict:
        """取得系統統計"""
        return {
            "initialized": self._initialized,
            "vectordb_loaded": self._vectordb is not None,
            "vectordb_count": self.doc_count,
            "bm25_loaded": self._bm25 is not None,
            "keyword_index_loaded": self._keyword_index is not None and bool(self._keyword_index.index),
            "reranker_enabled": RERANKER_CONFIG.enabled,
            "cache_enabled": CACHE_CONFIG.enabled,
            "cache_size": len(self.cache.cache),
            "personal_kb_available": self._personal_kb_module is not None,
            "business_query_available": self._business_module is not None,
        }

# ═══════════════════════════════════════════════════════════════
# 全域實例和便捷函數
# ═══════════════════════════════════════════════════════════════

_qa_system: Optional[CategorizedQASystem] = None
_qa_system_lock = Lock()

def get_qa_system() -> CategorizedQASystem:
    """取得問答系統實例（單例）"""
    global _qa_system
    
    if _qa_system is None:
        with _qa_system_lock:
            if _qa_system is None:
                _qa_system = CategorizedQASystem()
    
    return _qa_system

def reload_qa_system() -> bool:
    """重新載入問答系統"""
    return get_qa_system().reload()

# 向後兼容
def get_engine():
    return get_qa_system()

def reload_engine():
    return reload_qa_system()