# utils.py - 工具函數模組
"""
通用工具函數、分類器、成本估算器
"""

import os
import re
import hashlib
import unicodedata
from enum import Enum
from datetime import datetime
from typing import Optional, List, Dict
from threading import Lock

# ─────────────────────────────────────────────────────────────
# 常數定義
# ─────────────────────────────────────────────────────────────

class DocumentType(Enum):
    """文件類型枚舉"""
    TECHNICAL = "technical"
    BUSINESS = "business"
    MIXED = "mixed"


# 營業所同義詞對照
BRANCH_SYNONYMS = {
    "台南營業所": ["台南所", "台南營所", "台南營業課", "台南", "Tainan"],
    "高雄營業所": ["高雄所", "高雄營所", "高雄", "Kaohsiung"],
    "台北營業所": ["台北所", "台北", "Taipei"],
    "台中營業所": ["台中所", "台中", "Taichung"],
}

CLASS_SYNONYMS = ["業務拜訪", "拜訪", "送貨", "交貨", "其他", "會議", "聯絡", "支援"]

_MONTH_REGEXES = [
    re.compile(r'(?P<year>20\d{2})[./-]?年?(?P<month>1[0-2]|0?[1-9])月?'),
    re.compile(r'(?<!\d)(?P<month>1[0-2]|0?[1-9])月(?!\d)'),
]

# ─────────────────────────────────────────────────────────────
# 文字處理工具
# ─────────────────────────────────────────────────────────────

def _nfkc(s: str) -> str:
    """Unicode NFKC 正規化"""
    if not s:
        return s or ""
    t = unicodedata.normalize("NFKC", s).strip()
    t = t.replace("臺", "台")
    t = t.replace("—", "-").replace("–", "-").replace("−", "-")
    t = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", t)
    return t


def _restore_product_codes(s: str) -> str:
    """恢復產品型號格式"""
    s = re.sub(r'ProductCode_([A-Z0-9-]+)', r'No.\1', s)
    s = re.sub(r'ValquaProductCode_([A-Z0-9-]+)', r'バルカー No.\1', s)
    return s

# ─────────────────────────────────────────────────────────────
# Hash 計算
# ─────────────────────────────────────────────────────────────

def hash_dir(path: str) -> str:
    """計算目錄的 hash 值"""
    if not os.path.exists(path):
        return ""
    
    h = hashlib.md5()
    for root, dirs, files in sorted(os.walk(path)):
        dirs.sort()
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            try:
                h.update(fn.encode())
                h.update(str(os.path.getmtime(fp)).encode())
            except Exception:
                pass
    return h.hexdigest()


def hash_csv_file(csv_file: str) -> str:
    """計算 CSV 檔案的 hash 值"""
    if not csv_file or not os.path.exists(csv_file):
        return ""
    
    h = hashlib.md5()
    try:
        h.update(os.path.basename(csv_file).encode())
        h.update(str(os.path.getmtime(csv_file)).encode())
        h.update(str(os.path.getsize(csv_file)).encode())
    except Exception:
        pass
    return h.hexdigest()

# ─────────────────────────────────────────────────────────────
# 查詢分類器
# ─────────────────────────────────────────────────────────────

class QueryClassifier:
    """
    查詢內容智慧分類器
    
    支援兩種模式：
    1. 關鍵字模式（快速、免費）
    2. LLM 模式（準確、需 API）
    """
    
    # 技術關鍵字（權重較高的放前面）
    TECHNICAL_KEYWORDS = [
        # 高權重
        ('No.', 3), ('型號', 3), ('規格', 3), ('安裝', 2), ('維修', 2),
        # 中權重
        ('材質', 1), ('操作', 1), ('保養', 1), ('故障', 1), ('排除', 1),
        ('技術', 1), ('參數', 1), ('尺寸', 1), ('壓力', 1), ('溫度', 1),
        ('流量', 1), ('扭力', 1), ('硬度', 1), ('耐熱', 1), ('耐油', 1),
        # 產品相關
        ('油封', 1), ('墊片', 1), ('襯墊', 1), ('接頭', 1), ('管路', 1),
        ('閥門', 1), ('泵浦', 1), ('馬達', 1), ('氣缸', 1), ('電磁閥', 1),
        # 動作詞
        ('如何', 1), ('怎麼', 1), ('步驟', 1), ('方法', 1), ('程序', 1),
        # 品牌
        ('VALQUA', 2), ('SMC', 2), ('YUKEN', 2), ('玖基', 2), ('協鋼', 2),
        ('ガスケット', 2), ('バルカー', 2),
    ]
    
    # 業務關鍵字
    BUSINESS_KEYWORDS = [
        # 高權重
        ('客戶', 3), ('拜訪', 3), ('營業所', 3), ('日報', 3), ('業務', 2),
        # 時間相關
        ('最近', 2), ('本月', 2), ('上月', 2), ('年', 1), ('月', 1), ('週', 1),
        # 活動相關
        ('訂單', 2), ('會議', 1), ('報告', 1), ('銷售', 1), ('活動', 2),
        ('取貨', 1), ('交貨', 1), ('討論', 1), ('開發', 1), ('聯絡', 1),
        # 組織相關
        ('公司', 1), ('廠商', 1), ('供應商', 1), ('代工', 1),
        ('台南', 2), ('台中', 2), ('台北', 2), ('高雄', 2),
    ]
    
    # 快取 LLM 客戶端
    _llm_client = None
    
    @classmethod
    def _get_llm(cls):
        """取得 LLM 客戶端"""
        if cls._llm_client is None:
            try:
                from langchain_openai import ChatOpenAI
                cls._llm_client = ChatOpenAI(
                    model="gpt-4o-mini",  # 用便宜的模型做分類
                    temperature=0,
                    max_tokens=20
                )
            except Exception:
                cls._llm_client = None
        return cls._llm_client
    
    @classmethod
    def classify_query(cls, query: str, use_llm: bool = False) -> DocumentType:
        """
        分類查詢類型
        
        Args:
            query: 查詢字串
            use_llm: 是否使用 LLM 分類（更準確但需 API）
        
        Returns:
            DocumentType (TECHNICAL, BUSINESS, MIXED)
        """
        if not query:
            return DocumentType.MIXED
        
        # 先用關鍵字快速判斷明確案例
        quick_result = cls._quick_classify(query)
        if quick_result and not use_llm:
            return quick_result
        
        # 使用 LLM 分類（可選）
        if use_llm:
            llm_result = cls._llm_classify(query)
            if llm_result:
                return llm_result
        
        # 關鍵字計分
        return cls._keyword_classify(query)
    
    @classmethod
    def _quick_classify(cls, query: str) -> Optional[DocumentType]:
        """快速規則分類（處理明確案例）"""
        # 明確的業務查詢模式
        if re.search(r'(?:列出|查詢|顯示).*(?:客戶|活動|紀錄|日報)', query):
            return DocumentType.BUSINESS
        if re.search(r'\d{4}年\d{1,2}月|最近\d+[天週月]', query):
            return DocumentType.BUSINESS
        if re.search(r'(?:台南|台中|台北|高雄)(?:營業所|所)', query):
            return DocumentType.BUSINESS
        
        # ⭐ 重要：產品型號優先判定為技術查詢
        # SMC 產品型號
        if re.search(r'(?:MXJ|MXH|MXP|LES|LEH[ZF]?|ACG|ARG|AWG)\d*', query, re.IGNORECASE):
            return DocumentType.TECHNICAL
        # VALQUA 產品型號
        if re.search(r'No\.\s*\d+|バルカー|VALQUA|華爾卡', query, re.IGNORECASE):
            return DocumentType.TECHNICAL
        # 玖基/協鋼產品型號
        if re.search(r'(?:GF|SF|MF|UF)\d+', query, re.IGNORECASE):
            return DocumentType.TECHNICAL
        
        # 明確的技術查詢模式
        if re.search(r'No\.\s*\d+|型號\s*\w+', query):
            return DocumentType.TECHNICAL
        if re.search(r'(?:如何|怎麼).*(?:安裝|維修|更換|操作)', query):
            return DocumentType.TECHNICAL
        if re.search(r'規格|尺寸|材質|壓力|溫度|耐熱', query):
            return DocumentType.TECHNICAL
        
        return None
    
    @classmethod
    def _keyword_classify(cls, query: str) -> DocumentType:
        """關鍵字計分分類"""
        query_lower = query.lower()
        
        tech_score = 0
        for kw, weight in cls.TECHNICAL_KEYWORDS:
            if kw.lower() in query_lower:
                tech_score += weight
        
        biz_score = 0
        for kw, weight in cls.BUSINESS_KEYWORDS:
            if kw.lower() in query_lower:
                biz_score += weight
        
        # 決定分類
        diff = abs(tech_score - biz_score)
        if diff <= 2:  # 差距小於等於 2，視為混合
            return DocumentType.MIXED
        elif tech_score > biz_score:
            return DocumentType.TECHNICAL
        else:
            return DocumentType.BUSINESS
    
    @classmethod
    def _llm_classify(cls, query: str) -> Optional[DocumentType]:
        """使用 LLM 分類（更準確）"""
        llm = cls._get_llm()
        if not llm:
            return None
        
        try:
            prompt = f"""分析以下查詢的意圖，判斷應該查詢哪種資料庫。

查詢：{query}

回答（只輸出一個詞）：
- TECHNICAL：技術相關（產品規格、安裝、維修、型號等）
- BUSINESS：業務相關（客戶、拜訪、訂單、活動記錄等）
- MIXED：兩者都需要

意圖："""
            
            response = llm.invoke(prompt)
            result = response.content.strip().upper()
            
            if "TECHNICAL" in result:
                return DocumentType.TECHNICAL
            elif "BUSINESS" in result:
                return DocumentType.BUSINESS
            else:
                return DocumentType.MIXED
        except Exception:
            return None

# ─────────────────────────────────────────────────────────────
# 業務查詢擴展
# ─────────────────────────────────────────────────────────────

def expand_business_query(q: str) -> str:
    """
    將查詢自動補齊為較易命中的片語
    例如：『8月台南營業所活動』→ 補齊日期格式、部門、活動類型
    """
    q = _nfkc(q)
    year, month = None, None

    # 擷取月份/年份
    for rx in _MONTH_REGEXES:
        m = rx.search(q)
        if m:
            month = int(m.group("month"))
            if "year" in m.groupdict() and m.group("year"):
                year = int(m.group("year"))
            break
    
    if month and not year:
        year = datetime.now().year

    tags = []
    if year and month:
        tags += [f"{year}年{month}月", f"{year}/{month:02d}", f"{year}-{month:02d}"]

    # 擴展營業所同義詞
    for canonical, syns in BRANCH_SYNONYMS.items():
        if any(s in q for s in [canonical] + syns):
            tags += [canonical, f"部門 {canonical}", f"Depart {canonical}"] + syns
            break

    # 活動關鍵詞
    if "活動" in q and not any(x in q for x in CLASS_SYNONYMS):
        tags += CLASS_SYNONYMS

    if tags:
        q = f"{q} " + " ".join(dict.fromkeys(tags))
        if year and month:
            q += f" 搜尋標籤 {year}年{month}月"

    return q

# ─────────────────────────────────────────────────────────────
# 成本估算器
# ─────────────────────────────────────────────────────────────

class SimpleCostEstimator:
    """簡易 Token 成本估算器"""
    
    # 價格 (USD per 1M tokens)
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    }
    
    def __init__(self, model: str = "gpt-4o"):
        self.model = model
        self._encoder = None
    
    def _get_encoder(self):
        if self._encoder is None:
            try:
                import tiktoken
                self._encoder = tiktoken.encoding_for_model(self.model)
            except Exception:
                self._encoder = None
        return self._encoder
    
    def count_tokens(self, text: str) -> int:
        """計算文字的 token 數"""
        encoder = self._get_encoder()
        if encoder and text:
            return len(encoder.encode(text))
        return len(text) // 4  # 估算
    
    def estimate_cost(self, input_text: str = "", output_text: str = "", 
                      context_docs: list = None) -> Dict:
        """估算查詢成本"""
        context_text = ""
        if context_docs:
            context_text = "\n".join(
                getattr(d, "page_content", str(d)) for d in context_docs
            )
        
        input_tokens = self.count_tokens(input_text + context_text)
        output_tokens = self.count_tokens(output_text)
        
        prices = self.PRICING.get(self.model, self.PRICING["gpt-4o"])
        input_cost = (input_tokens / 1_000_000) * prices["input"]
        output_cost = (output_tokens / 1_000_000) * prices["output"]
        
        return {
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(input_cost + output_cost, 6),
        }

# ─────────────────────────────────────────────────────────────
# Context 管理器
# ─────────────────────────────────────────────────────────────

class ContextManager:
    """管理查詢上下文"""
    
    def __init__(self, max_context_length: int = 8000):
        self.max_context_length = max_context_length
        self._encoder = None
    
    def _get_encoder(self):
        if self._encoder is None:
            try:
                import tiktoken
                self._encoder = tiktoken.get_encoding("cl100k_base")
            except Exception:
                self._encoder = None
        return self._encoder
    
    def count_tokens(self, text: str) -> int:
        encoder = self._get_encoder()
        if encoder and text:
            return len(encoder.encode(text))
        return len(text) // 4
    
    def truncate_context(self, docs: list, max_tokens: int = None) -> list:
        """截斷上下文到指定 token 數"""
        max_tokens = max_tokens or self.max_context_length
        result = []
        total_tokens = 0
        
        for doc in docs:
            content = getattr(doc, "page_content", str(doc))
            doc_tokens = self.count_tokens(content)
            
            if total_tokens + doc_tokens <= max_tokens:
                result.append(doc)
                total_tokens += doc_tokens
            else:
                break
        
        return result
    
    def format_context(self, docs: list) -> str:
        """格式化上下文為字串"""
        parts = []
        for i, doc in enumerate(docs, 1):
            content = getattr(doc, "page_content", str(doc))
            source = getattr(doc, "metadata", {}).get("source", "unknown")
            parts.append(f"[文件 {i}] 來源: {source}\n{content}")
        return "\n\n---\n\n".join(parts)


# 建立全域實例
cost_estimator = SimpleCostEstimator("gpt-4o")
