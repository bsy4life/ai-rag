# rag_optimizer.py - RAG 優化輔助模組
"""
提供：
1. 分層 LLM 選擇
2. Reranker 支援
3. 來源追蹤
4. 複雜度評估
"""

import os
import re
from typing import List, Dict, Optional, Tuple
from langchain_core.documents import Document

# ─────────────────────────────────────────────────────────────
# 分層 LLM
# ─────────────────────────────────────────────────────────────

def get_llm_for_query(query_type: str, query: str, docs: List[Document] = None):
    """
    根據查詢類型和複雜度選擇適當的 LLM
    
    Args:
        query_type: "technical", "business", "mixed"
        query: 查詢內容
        docs: 檢索到的文檔（用於評估複雜度）
    
    Returns:
        ChatOpenAI 實例
    """
    from langchain_openai import ChatOpenAI
    
    try:
        from config_optimized import LLM_CONFIG
    except ImportError:
        # 預設配置
        LLM_CONFIG = {
            "technical_complex": {"model": "gpt-4o", "temperature": 0.1},
            "technical_simple": {"model": "gpt-4o-mini", "temperature": 0.1},
            "business": {"model": "gpt-4o-mini", "temperature": 0},
            "default": {"model": "gpt-4o-mini", "temperature": 0.1},
        }
    
    # 業務查詢一律用便宜模型
    if query_type == "business":
        config = LLM_CONFIG.get("business", LLM_CONFIG["default"])
        return ChatOpenAI(**config)
    
    # 技術查詢根據複雜度選擇
    if query_type == "technical":
        complexity = estimate_query_complexity(query, docs)
        if complexity == "complex":
            config = LLM_CONFIG.get("technical_complex", LLM_CONFIG["default"])
        else:
            config = LLM_CONFIG.get("technical_simple", LLM_CONFIG["default"])
        return ChatOpenAI(**config)
    
    # 預設
    return ChatOpenAI(**LLM_CONFIG["default"])


def estimate_query_complexity(query: str, docs: List[Document] = None) -> str:
    """
    評估查詢複雜度
    
    Returns:
        "simple" 或 "complex"
    """
    # 複雜度指標
    is_complex = False
    
    # 1. 問題長度
    if len(query) > 100:
        is_complex = True
    
    # 2. 多個產品/型號
    model_patterns = [
        r'[A-Z]{2,}\d+',           # SMC123
        r'No\.\s*\d+',             # No.6500
        r'\d+[A-Z]+\d*',           # 7010A
    ]
    model_count = sum(len(re.findall(p, query)) for p in model_patterns)
    if model_count >= 2:
        is_complex = True
    
    # 3. 比較類問題
    comparison_keywords = ['比較', '差異', '不同', '哪個', 'vs', '對比', '優缺點']
    if any(kw in query for kw in comparison_keywords):
        is_complex = True
    
    # 4. 文檔數量多
    if docs and len(docs) > 5:
        is_complex = True
    
    # 5. 需要計算或分析
    analysis_keywords = ['計算', '估算', '分析', '統計', '趨勢', '預測']
    if any(kw in query for kw in analysis_keywords):
        is_complex = True
    
    return "complex" if is_complex else "simple"


# ─────────────────────────────────────────────────────────────
# Reranker
# ─────────────────────────────────────────────────────────────

_reranker = None

def get_reranker():
    """取得 Reranker 實例（單例）"""
    global _reranker
    
    if _reranker is not None:
        return _reranker
    
    try:
        from config_optimized import RERANKER_CONFIG
    except ImportError:
        return None
    
    if not RERANKER_CONFIG.get("enabled", False):
        return None
    
    reranker_type = RERANKER_CONFIG.get("type", "local")
    
    if reranker_type == "cohere":
        try:
            from langchain_cohere import CohereRerank
            api_key = os.getenv(RERANKER_CONFIG["cohere"]["api_key_env"])
            if api_key:
                _reranker = CohereRerank(
                    model=RERANKER_CONFIG["cohere"]["model"],
                    top_n=RERANKER_CONFIG.get("top_n", 5)
                )
                print("✅ Cohere Reranker 已啟用")
        except ImportError:
            print("⚠️ 需要安裝 langchain-cohere: pip install langchain-cohere")
    
    elif reranker_type == "local":
        try:
            from sentence_transformers import CrossEncoder
            model_name = RERANKER_CONFIG["local"]["model"]
            _reranker = CrossEncoder(model_name)
            print(f"✅ 本地 Reranker 已啟用: {model_name}")
        except ImportError:
            print("⚠️ 需要安裝 sentence-transformers: pip install sentence-transformers")
    
    return _reranker


def rerank_documents(query: str, docs: List[Document], top_n: int = 5) -> List[Document]:
    """
    使用 Reranker 重新排序文檔
    
    Args:
        query: 查詢
        docs: 原始文檔列表
        top_n: 保留前 N 個
    
    Returns:
        重排後的文檔列表
    """
    if not docs:
        return docs
    
    reranker = get_reranker()
    if reranker is None:
        return docs[:top_n]
    
    try:
        from config_optimized import RERANKER_CONFIG
        reranker_type = RERANKER_CONFIG.get("type", "local")
    except ImportError:
        reranker_type = "local"
    
    if reranker_type == "cohere":
        # Cohere Reranker 返回 Document 列表
        try:
            return reranker.compress_documents(docs, query)[:top_n]
        except Exception as e:
            print(f"⚠️ Cohere Rerank 失敗: {e}")
            return docs[:top_n]
    
    else:
        # 本地 CrossEncoder
        try:
            pairs = [(query, doc.page_content) for doc in docs]
            scores = reranker.predict(pairs)
            
            # 排序
            doc_scores = list(zip(docs, scores))
            doc_scores.sort(key=lambda x: x[1], reverse=True)
            
            return [doc for doc, _ in doc_scores[:top_n]]
        except Exception as e:
            print(f"⚠️ 本地 Rerank 失敗: {e}")
            return docs[:top_n]


# ─────────────────────────────────────────────────────────────
# 來源追蹤
# ─────────────────────────────────────────────────────────────

def extract_sources(docs: List[Document], max_sources: int = 3) -> List[str]:
    """
    從文檔中提取來源資訊
    
    Args:
        docs: 文檔列表
        max_sources: 最多返回幾個來源
    
    Returns:
        來源列表
    """
    sources = []
    seen = set()
    
    for doc in docs:
        source = doc.metadata.get('source', '')
        if source and source not in seen:
            # 簡化路徑
            source_name = os.path.basename(source)
            sources.append(source_name)
            seen.add(source)
        
        if len(sources) >= max_sources:
            break
    
    return sources


def append_sources_to_answer(answer: str, sources: List[str]) -> str:
    """
    在回答末尾附加來源資訊
    
    Args:
        answer: 原始回答
        sources: 來源列表
    
    Returns:
        附加來源後的回答
    """
    if not sources:
        return answer
    
    source_text = "\n\n---\n📚 **參考來源**：" + "、".join(sources)
    return answer + source_text


# ─────────────────────────────────────────────────────────────
# 優化後的檢索流程
# ─────────────────────────────────────────────────────────────

def optimized_retrieve_and_generate(
    query: str,
    retriever,
    chain,
    query_type: str = "technical",
    use_rerank: bool = True,
    track_sources: bool = True
) -> Tuple[str, List[str]]:
    """
    優化後的檢索和生成流程
    
    Args:
        query: 查詢
        retriever: 檢索器
        chain: LLM 鏈
        query_type: 查詢類型
        use_rerank: 是否使用 Reranker
        track_sources: 是否追蹤來源
    
    Returns:
        (回答, 來源列表)
    """
    # 1. 檢索
    docs = retriever.invoke(query)
    
    # 2. Rerank（可選）
    if use_rerank:
        docs = rerank_documents(query, docs)
    
    # 3. 提取來源
    sources = []
    if track_sources:
        sources = extract_sources(docs)
    
    # 4. 選擇 LLM
    llm = get_llm_for_query(query_type, query, docs)
    
    # 5. 生成回答
    # 注意：這裡假設 chain 可以接受自定義 LLM
    # 實際使用時可能需要調整
    try:
        result = chain.invoke({"input": query, "context": docs})
        answer = result if isinstance(result, str) else result.get("answer", "")
    except Exception as e:
        answer = f"生成回答時發生錯誤：{e}"
    
    # 6. 附加來源
    if track_sources and sources:
        answer = append_sources_to_answer(answer, sources)
    
    return answer, sources


# ─────────────────────────────────────────────────────────────
# 成本估算
# ─────────────────────────────────────────────────────────────

def estimate_query_cost(query: str, docs: List[Document], model: str = "gpt-4o") -> Dict:
    """
    估算查詢成本
    
    Returns:
        {"input_tokens": int, "output_tokens": int, "estimated_cost": float}
    """
    # 估算 token 數（粗略）
    query_tokens = len(query) // 2  # 中文約 2 字元 = 1 token
    
    context_tokens = 0
    for doc in docs:
        context_tokens += len(doc.page_content) // 2
    
    input_tokens = query_tokens + context_tokens
    output_tokens = 500  # 假設輸出約 500 tokens
    
    # 價格（每 1M tokens）
    prices = {
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    }
    
    price = prices.get(model, prices["gpt-4o"])
    
    input_cost = (input_tokens / 1_000_000) * price["input"]
    output_cost = (output_tokens / 1_000_000) * price["output"]
    
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(input_cost + output_cost, 6),
        "model": model,
    }
