# core_engine.py - SanShin AI 核心 RAG 引擎（生產級）
"""
完整的 RAG 引擎實作：
1. 三層檢索：精確匹配 + BM25 + 向量
2. 分層 LLM 選擇
3. Reranker 支援
4. 來源追蹤
5. 快取機制
6. 成本估算
"""

import os
import re
import json
import hashlib
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from threading import Lock
from functools import lru_cache

# 配置
from config import (
    EMBEDDING_MODEL, LLM_CONFIGS, RETRIEVER_CONFIGS, CHUNK_CONFIGS,
    PROMPTS, RERANKER_CONFIG, CACHE_CONFIG, SOURCE_TRACKING,
    KEYWORD_PATTERNS, CHINESE_STOPWORDS, COMPLEXITY_THRESHOLDS,
    COMPARISON_KEYWORDS, ANALYSIS_KEYWORDS,
    VECTOR_DB_DIR, DATA_DIR, TECHNICAL_DATA_DIR,
    get_llm_config, get_retriever_config,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 資料結構
# ═══════════════════════════════════════════════════════════════

@dataclass
class SearchResult:
    """搜尋結果"""
    content: str
    source: str
    doc_type: str
    score: float = 0.0
    metadata: Dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class QueryResult:
    """查詢結果"""
    answer: str
    sources: List[str]
    source_type: str  # technical, business, personal, mixed
    images: List[Dict] = None
    metadata: Dict = None
    cost_estimate: Dict = None
    from_cache: bool = False
    
    def __post_init__(self):
        if self.images is None:
            self.images = []
        if self.metadata is None:
            self.metadata = {}

# ═══════════════════════════════════════════════════════════════
# 關鍵字索引
# ═══════════════════════════════════════════════════════════════

class KeywordIndex:
    """倒排關鍵字索引"""
    
    def __init__(self, index_path: str = None):
        self.index: Dict[str, List[Tuple[str, float]]] = {}  # keyword -> [(doc_id, weight), ...]
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
                
                # 檢查是否已存在
                existing = [i for i, (d, _) in enumerate(self.index[kw_lower]) if d == doc_id]
                if existing:
                    self.index[kw_lower][existing[0]] = (doc_id, weight)
                else:
                    self.index[kw_lower].append((doc_id, weight))
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取關鍵字"""
        keywords = set()
        
        # 使用正則模式
        for pattern in KEYWORD_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            keywords.update(m.upper() if len(m) <= 10 else m for m in matches)
        
        # 中文詞彙
        chinese = re.findall(r'[\u4e00-\u9fa5]{2,6}', text)
        keywords.update(w for w in chinese if w not in CHINESE_STOPWORDS)
        
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
        
        # 排序
        results = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]
    
    def save(self):
        """儲存索引"""
        if self.index_path:
            with self._lock:
                data = {
                    "index": {k: list(v) for k, v in self.index.items()},
                    "doc_keywords": self.doc_keywords,
                }
                with open(self.index_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
    
    def load(self):
        """載入索引"""
        if self.index_path and os.path.exists(self.index_path):
            with open(self.index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.index = {k: [tuple(x) for x in v] for k, v in data.get("index", {}).items()}
                self.doc_keywords = data.get("doc_keywords", {})

# ═══════════════════════════════════════════════════════════════
# 查詢快取
# ═══════════════════════════════════════════════════════════════

class QueryCache:
    """查詢快取"""
    
    def __init__(self, config=CACHE_CONFIG):
        self.config = config
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = Lock()
        
        if config.backend == "file" and config.file_path:
            self._load_file_cache()
    
    def _make_key(self, query: str, mode: str) -> str:
        """生成快取鍵"""
        return hashlib.md5(f"{query}:{mode}".encode()).hexdigest()
    
    def get(self, query: str, mode: str) -> Optional[QueryResult]:
        """取得快取"""
        if not self.config.enabled:
            return None
        
        key = self._make_key(query, mode)
        
        with self._lock:
            if key in self.cache:
                result, timestamp = self.cache[key]
                # 檢查是否過期
                if datetime.now().timestamp() - timestamp < self.config.ttl:
                    result.from_cache = True
                    return result
                else:
                    del self.cache[key]
        
        return None
    
    def set(self, query: str, mode: str, result: QueryResult):
        """設定快取"""
        if not self.config.enabled:
            return
        
        key = self._make_key(query, mode)
        
        with self._lock:
            # 檢查大小限制
            if len(self.cache) >= self.config.max_size:
                # 移除最舊的
                oldest = min(self.cache.items(), key=lambda x: x[1][1])
                del self.cache[oldest[0]]
            
            self.cache[key] = (result, datetime.now().timestamp())
        
        # 異步保存到檔案
        if self.config.backend == "file":
            self._save_file_cache()
    
    def _load_file_cache(self):
        """載入檔案快取"""
        if os.path.exists(self.config.file_path):
            try:
                with open(self.config.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, (result_dict, ts) in data.items():
                        self.cache[key] = (QueryResult(**result_dict), ts)
            except:
                pass
    
    def _save_file_cache(self):
        """保存檔案快取"""
        try:
            data = {
                key: (asdict(result), ts)
                for key, (result, ts) in self.cache.items()
            }
            with open(self.config.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except:
            pass
    
    def clear(self):
        """清空快取"""
        with self._lock:
            self.cache.clear()
        if self.config.backend == "file" and os.path.exists(self.config.file_path):
            os.remove(self.config.file_path)

# ═══════════════════════════════════════════════════════════════
# Reranker
# ═══════════════════════════════════════════════════════════════

class Reranker:
    """重排序器"""
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.config = RERANKER_CONFIG
        self.model = None
        
        if self.config.enabled:
            self._load_model()
        
        self._initialized = True
    
    def _load_model(self):
        """載入模型"""
        if self.config.type == "cohere":
            try:
                from langchain_cohere import CohereRerank
                api_key = os.getenv(self.config.cohere_api_key_env)
                if api_key:
                    self.model = CohereRerank(
                        model=self.config.cohere_model,
                        top_n=self.config.top_n
                    )
                    logger.info("✅ Cohere Reranker 已載入")
            except ImportError:
                logger.warning("需要安裝 langchain-cohere")
        
        elif self.config.type == "local":
            try:
                from sentence_transformers import CrossEncoder
                self.model = CrossEncoder(self.config.local_model)
                logger.info(f"✅ 本地 Reranker 已載入: {self.config.local_model}")
            except ImportError:
                logger.warning("需要安裝 sentence-transformers")
    
    def rerank(self, query: str, documents: List[SearchResult]) -> List[SearchResult]:
        """重排序"""
        if not self.config.enabled or not self.model or not documents:
            return documents[:self.config.top_n]
        
        try:
            if self.config.type == "local":
                pairs = [(query, doc.content) for doc in documents]
                scores = self.model.predict(pairs)
                
                for doc, score in zip(documents, scores):
                    doc.score = float(score)
                
                documents.sort(key=lambda x: x.score, reverse=True)
                return documents[:self.config.top_n]
            
            elif self.config.type == "cohere":
                # Cohere 需要 LangChain Document
                from langchain_core.documents import Document
                lc_docs = [Document(page_content=d.content, metadata=d.metadata) for d in documents]
                reranked = self.model.compress_documents(lc_docs, query)
                
                results = []
                for doc in reranked[:self.config.top_n]:
                    results.append(SearchResult(
                        content=doc.page_content,
                        source=doc.metadata.get("source", ""),
                        doc_type=doc.metadata.get("doc_type", "unknown"),
                        metadata=doc.metadata,
                    ))
                return results
        
        except Exception as e:
            logger.warning(f"Rerank 失敗: {e}")
        
        return documents[:self.config.top_n]

# ═══════════════════════════════════════════════════════════════
# 複雜度評估
# ═══════════════════════════════════════════════════════════════

def estimate_complexity(query: str, doc_count: int = 0) -> str:
    """評估查詢複雜度"""
    score = 0
    
    # 問題長度
    if len(query) > COMPLEXITY_THRESHOLDS["query_length"]:
        score += 1
    
    # 產品型號數量
    model_count = sum(len(re.findall(p, query)) for p in KEYWORD_PATTERNS[:3])
    if model_count >= COMPLEXITY_THRESHOLDS["model_count"]:
        score += 1
    
    # 比較類問題
    if any(kw in query for kw in COMPARISON_KEYWORDS):
        score += 1
    
    # 分析類問題
    if any(kw in query for kw in ANALYSIS_KEYWORDS):
        score += 1
    
    # 文檔數量
    if doc_count > COMPLEXITY_THRESHOLDS["doc_count"]:
        score += 1
    
    return "complex" if score >= 2 else "simple"

# ═══════════════════════════════════════════════════════════════
# 成本估算
# ═══════════════════════════════════════════════════════════════

def estimate_cost(input_tokens: int, output_tokens: int, model: str) -> Dict:
    """估算 API 成本"""
    from config import TOKEN_PRICES
    
    prices = TOKEN_PRICES.get(model, TOKEN_PRICES["gpt-4o-mini"])
    
    input_cost = (input_tokens / 1_000_000) * prices.get("input", 0)
    output_cost = (output_tokens / 1_000_000) * prices.get("output", 0)
    
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(input_cost + output_cost, 6),
    }

# ═══════════════════════════════════════════════════════════════
# 核心引擎
# ═══════════════════════════════════════════════════════════════

class RAGEngine:
    """RAG 核心引擎"""
    
    def __init__(self):
        self.keyword_index = KeywordIndex(
            os.path.join(VECTOR_DB_DIR, "keyword_index.json")
        )
        self.cache = QueryCache()
        self.reranker = Reranker()
        
        self._vectordb = None
        self._bm25 = None
        self._llm = None
        self._embedding = None
        
        self._lock = Lock()
        self._initialized = False
    
    def initialize(self):
        """初始化引擎"""
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            logger.info("🚀 初始化 RAG 引擎...")
            
            # 載入 Embedding
            self._load_embedding()
            
            # 載入向量庫
            self._load_vectordb()
            
            # 載入 BM25
            self._load_bm25()
            
            self._initialized = True
            logger.info("✅ RAG 引擎初始化完成")
    
    def _load_embedding(self):
        """載入 Embedding 模型"""
        try:
            from langchain_openai import OpenAIEmbeddings
            self._embedding = OpenAIEmbeddings(model=EMBEDDING_MODEL)
            logger.info(f"✅ Embedding 模型: {EMBEDDING_MODEL}")
        except Exception as e:
            logger.error(f"❌ Embedding 載入失敗: {e}")
    
    def _load_vectordb(self):
        """載入向量庫"""
        try:
            from langchain_chroma import Chroma
            import chromadb
            
            client = chromadb.PersistentClient(path=VECTOR_DB_DIR)
            self._vectordb = Chroma(
                client=client,
                collection_name="technical_docs",
                embedding_function=self._embedding
            )
            
            # 取得文件數量
            try:
                count = self._vectordb._collection.count()
                logger.info(f"✅ 向量庫已載入: {count} 個文件")
            except:
                pass
        except Exception as e:
            logger.error(f"❌ 向量庫載入失敗: {e}")
    
    def _load_bm25(self):
        """載入 BM25 索引"""
        try:
            from langchain_community.retrievers import BM25Retriever
            
            # 從向量庫取得所有文件
            if self._vectordb:
                docs = self._vectordb.get()
                if docs and docs.get("documents"):
                    from langchain_core.documents import Document
                    lc_docs = [
                        Document(
                            page_content=content,
                            metadata={"id": id}
                        )
                        for content, id in zip(docs["documents"], docs["ids"])
                    ]
                    self._bm25 = BM25Retriever.from_documents(lc_docs)
                    self._bm25.k = 10
                    logger.info(f"✅ BM25 索引已建立: {len(lc_docs)} 個文件")
        except Exception as e:
            logger.warning(f"⚠️ BM25 載入失敗: {e}")
    
    def _get_llm(self, config):
        """取得 LLM"""
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(**config.to_dict())
    
    def search(
        self,
        query: str,
        doc_type: str = "technical",
        top_k: int = 10,
        use_rerank: bool = True,
    ) -> List[SearchResult]:
        """
        三層混合搜尋
        
        1. 關鍵字精確匹配
        2. BM25 關鍵字搜尋
        3. 向量語義搜尋
        """
        self.initialize()
        
        results: List[SearchResult] = []
        seen_ids = set()
        
        # 1. 關鍵字精確匹配（最高優先）
        kw_results = self.keyword_index.search(query, top_k=5)
        for doc_id, score in kw_results:
            if doc_id not in seen_ids:
                # 從向量庫取得內容
                try:
                    doc = self._vectordb._collection.get(ids=[doc_id])
                    if doc and doc.get("documents"):
                        results.append(SearchResult(
                            content=doc["documents"][0],
                            source=doc.get("metadatas", [{}])[0].get("source", ""),
                            doc_type=doc_type,
                            score=score * 2,  # 加權
                            metadata={"match_type": "keyword", "doc_id": doc_id}
                        ))
                        seen_ids.add(doc_id)
                except:
                    pass
        
        # 2. BM25 搜尋
        if self._bm25:
            try:
                bm25_docs = self._bm25.invoke(query)
                for doc in bm25_docs[:top_k]:
                    doc_id = doc.metadata.get("id", "")
                    if doc_id and doc_id not in seen_ids:
                        results.append(SearchResult(
                            content=doc.page_content,
                            source=doc.metadata.get("source", ""),
                            doc_type=doc_type,
                            score=1.5,
                            metadata={"match_type": "bm25", "doc_id": doc_id}
                        ))
                        seen_ids.add(doc_id)
            except Exception as e:
                logger.warning(f"BM25 搜尋失敗: {e}")
        
        # 3. 向量搜尋
        if self._vectordb:
            try:
                config = get_retriever_config(doc_type)
                vector_docs = self._vectordb.similarity_search_with_score(
                    query, k=config.k
                )
                for doc, score in vector_docs:
                    doc_id = doc.metadata.get("id", hash(doc.page_content))
                    if doc_id not in seen_ids:
                        results.append(SearchResult(
                            content=doc.page_content,
                            source=doc.metadata.get("source", ""),
                            doc_type=doc_type,
                            score=1.0 / (1.0 + score),  # 轉換距離為分數
                            metadata={"match_type": "vector", **doc.metadata}
                        ))
                        seen_ids.add(doc_id)
            except Exception as e:
                logger.warning(f"向量搜尋失敗: {e}")
        
        # 4. Rerank
        if use_rerank and results:
            results = self.reranker.rerank(query, results)
        else:
            # 按分數排序
            results.sort(key=lambda x: x.score, reverse=True)
            results = results[:top_k]
        
        return results
    
    def generate_answer(
        self,
        query: str,
        context: List[SearchResult],
        doc_type: str = "technical",
    ) -> Tuple[str, Dict]:
        """生成回答"""
        # 評估複雜度
        complexity = estimate_complexity(query, len(context))
        
        # 選擇 LLM
        llm_config = get_llm_config(doc_type, complexity)
        llm = self._get_llm(llm_config)
        
        # 準備上下文
        context_text = "\n\n---\n\n".join([
            f"【來源: {r.source}】\n{r.content}"
            for r in context
        ])
        
        # 選擇 Prompt
        prompt_template = PROMPTS.get(doc_type, PROMPTS["technical"])
        prompt = prompt_template.format(context=context_text, input=query)
        
        # 生成回答
        try:
            response = llm.invoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"LLM 生成失敗: {e}")
            answer = f"生成回答時發生錯誤：{e}"
        
        # 添加來源
        if SOURCE_TRACKING.enabled and SOURCE_TRACKING.show_in_response:
            sources = list(set(r.source for r in context if r.source))[:SOURCE_TRACKING.max_sources]
            if sources:
                answer += "\n\n---\n📚 **參考來源**：" + "、".join(sources)
        
        # 成本估算
        input_tokens = len(prompt) // 2
        output_tokens = len(answer) // 2
        cost = estimate_cost(input_tokens, output_tokens, llm_config.model)
        
        return answer, cost
    
    def query(
        self,
        query: str,
        mode: str = "smart",
        use_cache: bool = True,
    ) -> QueryResult:
        """
        完整查詢流程
        
        Args:
            query: 查詢內容
            mode: 模式 (smart, technical, business, personal)
            use_cache: 是否使用快取
        
        Returns:
            QueryResult
        """
        if not query or not query.strip():
            return QueryResult(
                answer="請輸入有效的問題。",
                sources=[],
                source_type="error",
            )
        
        query = query.strip()
        
        # 檢查快取
        if use_cache:
            cached = self.cache.get(query, mode)
            if cached:
                return cached
        
        # 判斷查詢類型
        if mode == "smart":
            doc_type = self._classify_query(query)
        else:
            doc_type = mode if mode in ["technical", "business", "personal"] else "technical"
        
        # 搜尋
        search_results = self.search(query, doc_type)
        
        if not search_results:
            return QueryResult(
                answer="未找到相關資料。請嘗試不同的關鍵字或查詢方式。",
                sources=[],
                source_type=doc_type,
            )
        
        # 生成回答
        answer, cost = self.generate_answer(query, search_results, doc_type)
        
        # 組裝結果
        result = QueryResult(
            answer=answer,
            sources=[r.source for r in search_results if r.source],
            source_type=doc_type,
            metadata={
                "search_count": len(search_results),
                "complexity": estimate_complexity(query, len(search_results)),
            },
            cost_estimate=cost,
        )
        
        # 存入快取
        if use_cache:
            self.cache.set(query, mode, result)
        
        return result
    
    def _classify_query(self, query: str) -> str:
        """分類查詢類型"""
        # 業務關鍵字
        business_keywords = [
            '客戶', '業務', '拜訪', '送貨', '訂單', '營業所',
            '活動', '日報', '統計', '分析', '業績',
        ]
        
        # 技術關鍵字
        technical_keywords = [
            '規格', '型號', '產品', '安裝', '維修', '故障',
            '氣缸', '油壓', '墊片', '電磁閥', 'SMC', 'YUKEN',
        ]
        
        query_lower = query.lower()
        
        biz_score = sum(1 for kw in business_keywords if kw in query)
        tech_score = sum(1 for kw in technical_keywords if kw in query_lower)
        
        if biz_score > tech_score:
            return "business"
        else:
            return "technical"
    
    def reload(self):
        """重新載入"""
        with self._lock:
            self._initialized = False
            self._vectordb = None
            self._bm25 = None
        
        self.initialize()
        self.cache.clear()
        logger.info("✅ RAG 引擎已重新載入")
    
    def get_stats(self) -> Dict:
        """取得統計資訊"""
        stats = {
            "initialized": self._initialized,
            "vectordb_loaded": self._vectordb is not None,
            "bm25_loaded": self._bm25 is not None,
            "reranker_enabled": RERANKER_CONFIG.enabled,
            "cache_enabled": CACHE_CONFIG.enabled,
            "cache_size": len(self.cache.cache),
        }
        
        if self._vectordb:
            try:
                stats["vectordb_count"] = self._vectordb._collection.count()
            except:
                pass
        
        return stats

# ═══════════════════════════════════════════════════════════════
# 全域實例
# ═══════════════════════════════════════════════════════════════

_engine: Optional[RAGEngine] = None
_engine_lock = Lock()

def get_engine() -> RAGEngine:
    """取得 RAG 引擎實例"""
    global _engine
    
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = RAGEngine()
    
    return _engine

def query(query: str, mode: str = "smart") -> QueryResult:
    """便捷查詢函數"""
    return get_engine().query(query, mode)

def reload_engine():
    """重新載入引擎"""
    get_engine().reload()
