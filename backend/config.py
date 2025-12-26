# config.py - SanShin AI 完整配置（生產級）
"""
統一配置中心
- 所有設定集中管理
- 支援環境變數覆蓋
- 包含預設值和驗證
"""

import os
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

# ═══════════════════════════════════════════════════════════════
# 環境
# ═══════════════════════════════════════════════════════════════

ENV = os.getenv("ENV", "production")  # development, staging, production
DEBUG = os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")

# ═══════════════════════════════════════════════════════════════
# 目錄結構（全部整合到 /app/data/ 下）
# ═══════════════════════════════════════════════════════════════

BASE_DIR = os.getenv("BASE_DIR", "/app")
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))

# 知識庫目錄
MARKDOWN_DIR = os.getenv("MARKDOWN_DIR", os.path.join(DATA_DIR, "markdown"))      # 技術文檔
BUSINESS_DATA_DIR = os.getenv("BUSINESS_DATA_DIR", os.path.join(DATA_DIR, "business"))  # 業務資料
PERSONAL_KB_DIR = os.getenv("PERSONAL_KB_DIR", os.path.join(DATA_DIR, "personal_kb"))   # 個人知識庫
PDF_DIR = os.getenv("PDF_DIR", os.path.join(DATA_DIR, "pdfs"))                    # PDF 原檔

# 向量庫（統一用這個）
VECTOR_DB_DIR = os.getenv("VECTOR_DB_DIR", os.path.join(DATA_DIR, "vectordb_sanshin"))

# 系統目錄
CACHE_DIR = os.getenv("CACHE_DIR", os.path.join(DATA_DIR, "cache"))
TEMP_DIR = os.getenv("TEMP_DIR", os.path.join(DATA_DIR, "temp"))
LOG_DIR = os.getenv("LOG_DIR", os.path.join(DATA_DIR, "logs"))

# 業務 CSV
BUSINESS_CSV_FILE = os.path.join(BUSINESS_DATA_DIR, "clean_business.csv")

# 技術文檔（別名，兼容舊程式碼）
TECHNICAL_DATA_DIR = MARKDOWN_DIR

# 確保目錄存在
for d in [DATA_DIR, MARKDOWN_DIR, BUSINESS_DATA_DIR, PERSONAL_KB_DIR, PDF_DIR,
          VECTOR_DB_DIR, CACHE_DIR, TEMP_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# OpenAI / LLM 設定
# ═══════════════════════════════════════════════════════════════

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()


# Embedding 模型
class EmbeddingModel(Enum):
    LARGE = "text-embedding-3-large"    # 最高品質，$0.13/1M tokens
    SMALL = "text-embedding-3-small"    # 便宜，$0.02/1M tokens
    ADA = "text-embedding-ada-002"      # 舊版

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", EmbeddingModel.SMALL.value)
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))

# LLM 模型配置
@dataclass
class LLMConfig:
    model: str
    temperature: float = 0.1
    max_tokens: int = 4000
    
    def to_dict(self) -> Dict:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


# LLM Provider（openai | anthropic | auto）
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LLM_PRIMARY = os.getenv("LLM_PRIMARY", "").strip().lower()
LLM_FALLBACK = os.getenv("LLM_FALLBACK", "").strip().lower()

def _provider_for_model_selection() -> str:
    """決定目前應使用哪一家的模型名稱。
    - LLM_PROVIDER=auto：以 LLM_PRIMARY 為準（未設則預設 anthropic）
    - 其他：以 LLM_PROVIDER 為準
    """
    if LLM_PROVIDER == "auto":
        return (LLM_PRIMARY or "anthropic").strip().lower()
    return LLM_PROVIDER

def resolve_llm_model(kind: str, default_openai: str, default_anthropic: str) -> str:
    """依 provider 選擇模型名稱，避免「選 Claude 卻吃到 GPT 模型」的錯用。

    kind: COMPLEX | SIMPLE | BUSINESS | PERSONAL | DEFAULT
    Env 優先序：
      1) <PROVIDER>_MODEL_<KIND>   (OPENAI_MODEL_* / ANTHROPIC_MODEL_*)
      2) LLM_MODEL_<KIND>         (舊版相容)
      3) provider 對應的 default
    """
    kind = kind.strip().upper()
    provider = _provider_for_model_selection()
    env_by_provider = None

    if provider in ("anthropic", "claude"):
        env_by_provider = os.getenv(f"ANTHROPIC_MODEL_{kind}")
        legacy = os.getenv(f"LLM_MODEL_{kind}")
        return (env_by_provider or legacy or default_anthropic).strip()
    # default openai
    env_by_provider = os.getenv(f"OPENAI_MODEL_{kind}")
    legacy = os.getenv(f"LLM_MODEL_{kind}")
    return (env_by_provider or legacy or default_openai).strip()

# 分層 LLM 策略
LLM_CONFIGS = {
    # 複雜技術問題 - 用最強模型
    "technical_complex": LLMConfig(
        model=resolve_llm_model("COMPLEX", "gpt-4o", "claude-3-5-sonnet-20240620"),
        temperature=0.1,
        max_tokens=4000,
    ),
    # 簡單技術問題 - 用便宜模型
    "technical_simple": LLMConfig(
        model=resolve_llm_model("SIMPLE", "gpt-4o-mini", "claude-3-5-haiku-20241022"),
        temperature=0.1,
        max_tokens=2000,
    ),
    # 業務查詢 - 用便宜模型（主要是格式化輸出）
    "business": LLMConfig(
        model=resolve_llm_model("BUSINESS", "gpt-4o-mini", "claude-3-5-haiku-20241022"),
        temperature=0,
        max_tokens=2000,
    ),
    # 個人知識庫
    "personal": LLMConfig(
        model=resolve_llm_model("PERSONAL", "gpt-4o-mini", "claude-3-5-haiku-20241022"),
        temperature=0.1,
        max_tokens=2000,
    ),
    # 預設
    "default": LLMConfig(
        model=resolve_llm_model("DEFAULT", "gpt-4o-mini", "claude-3-5-haiku-20241022"),
        temperature=0.1,
        max_tokens=2000,
    ),
}

# 向後兼容
LLM_MODEL = LLM_CONFIGS["default"].model

# ═══════════════════════════════════════════════════════════════
# Retriever 設定
# ═══════════════════════════════════════════════════════════════

@dataclass
class RetrieverConfig:
    search_type: str = "mmr"
    k: int = 8
    fetch_k: int = 30
    lambda_mult: float = 0.6
    score_threshold: Optional[float] = None

RETRIEVER_CONFIGS = {
    "technical": RetrieverConfig(
        search_type="mmr",
        k=12,          # 增加到 12，提供更多上下文
        fetch_k=40,    # 增加候選數
        lambda_mult=0.6,
    ),
    "business": RetrieverConfig(
        search_type="similarity",
        k=15,
    ),
    "personal": RetrieverConfig(
        search_type="mmr",
        k=8,           # 增加到 8
        fetch_k=25,
        lambda_mult=0.7,
    ),
}

# ═══════════════════════════════════════════════════════════════
# Chunk 設定
# ═══════════════════════════════════════════════════════════════

@dataclass
class ChunkConfig:
    chunk_size: int = 600
    chunk_overlap: int = 100
    separators: List[str] = field(default_factory=lambda: [
        "\n## ", "\n### ", "\n#### ",
        "\n\n**", "\n\n", "\n", "。", "；", " ", ""
    ])

CHUNK_CONFIGS = {
    "technical": ChunkConfig(
        chunk_size=1000,      # 增加到 1000，保留完整段落
        chunk_overlap=150,    # 增加重疊
        separators=[
            "\n## ", "\n### ", "\n#### ",
            "\n第 ", "\n一、", "\n二、", "\n三、", "\n四、", "\n五、",  # 條文分隔
            "\n\n**產品規格", "\n\n**規格",
            "\n\n", "\n", "。", "；", " ", ""
        ],
    ),
    "business": ChunkConfig(
        chunk_size=400,
        chunk_overlap=50,
        separators=[
            "\n**日期**:", "\n**業務人員**:",
            "\n\n", "\n", "。", " ", ""
        ],
    ),
    "personal": ChunkConfig(
        chunk_size=800,       # 增加到 800
        chunk_overlap=120,
        separators=[
            "\n## ", "\n### ",
            "\n第 ", "\n一、", "\n二、", "\n三、",  # 條文分隔
            "\n\n", "\n", "。", " ", ""
        ],
    ),
}

# ═══════════════════════════════════════════════════════════════
# Reranker 設定
# ═══════════════════════════════════════════════════════════════

@dataclass
class RerankerConfig:
    enabled: bool = False
    type: str = "local"  # "cohere" or "local"
    top_n: int = 5
    
    # Cohere
    cohere_model: str = "rerank-multilingual-v3.0"
    cohere_api_key_env: str = "COHERE_API_KEY"
    
    # Local
    local_model: str = "BAAI/bge-reranker-v2-m3"

RERANKER_CONFIG = RerankerConfig(
    enabled=os.getenv("RERANKER_ENABLED", "0").lower() in ("1", "true", "yes"),
    type=os.getenv("RERANKER_TYPE", "local"),
    top_n=int(os.getenv("RERANKER_TOP_N", "5")),
)

# ═══════════════════════════════════════════════════════════════
# 快取設定
# ═══════════════════════════════════════════════════════════════

@dataclass
class CacheConfig:
    enabled: bool = True
    backend: str = "memory"  # "memory", "file", "redis"
    ttl: int = 3600 * 24  # 24 hours
    max_size: int = 1000
    
    # Redis
    redis_url: str = ""
    
    # File
    file_path: str = ""

CACHE_CONFIG = CacheConfig(
    enabled=os.getenv("CACHE_ENABLED", "1").lower() in ("1", "true", "yes"),
    backend=os.getenv("CACHE_BACKEND", "file"),
    ttl=int(os.getenv("CACHE_TTL", str(3600 * 24))),
    max_size=int(os.getenv("CACHE_MAX_SIZE", "1000")),
    file_path=os.path.join(CACHE_DIR, "query_cache.json"),
)

# ═══════════════════════════════════════════════════════════════
# 業務查詢設定
# ═══════════════════════════════════════════════════════════════

@dataclass
class BusinessQueryConfig:
    use_csv_only: bool = True  # True = 直接查 CSV，False = 用向量庫
    max_results: int = 50
    date_format: str = "%Y/%m/%d"
    default_months: int = 12

BUSINESS_QUERY_CONFIG = BusinessQueryConfig(
    use_csv_only=os.getenv("BUSINESS_CSV_ONLY", "1").lower() in ("1", "true", "yes"),
    max_results=int(os.getenv("BUSINESS_MAX_RESULTS", "50")),
)

# ═══════════════════════════════════════════════════════════════
# 來源追蹤設定
# ═══════════════════════════════════════════════════════════════

@dataclass
class SourceTrackingConfig:
    enabled: bool = True
    show_in_response: bool = True
    max_sources: int = 3

SOURCE_TRACKING = SourceTrackingConfig(
    enabled=os.getenv("SOURCE_TRACKING_ENABLED", "1").lower() in ("1", "true", "yes"),
)

# ═══════════════════════════════════════════════════════════════
# 個人知識庫設定
# ═══════════════════════════════════════════════════════════════

@dataclass
class PersonalKBConfig:
    enabled: bool = True
    max_file_size_mb: int = 50
    allowed_extensions: List[str] = field(default_factory=lambda: [
        ".docx", ".pdf", ".txt", ".md", ".xlsx", ".csv"
    ])
    auto_extract_images: bool = True
    max_images_per_doc: int = 50

PERSONAL_KB_CONFIG = PersonalKBConfig(
    enabled=os.getenv("PERSONAL_KB_ENABLED", "1").lower() in ("1", "true", "yes"),
)

# ═══════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════

PROMPTS = {
    "technical": """你是三新的技術支援專家，專精於工業元件產品諮詢。

## 你代理的品牌
- **SMC**：氣壓元件（氣缸、電磁閥、真空吸盤、FRL、壓力開關）
- **YUKEN 油研**：油壓泵浦、油壓閥
- **VALQUA 華爾卡（バルカー）**：墊片（ガスケット）、填料（パッキン）
  - 常見系列：No.6500（ジョイントシート）、No.7010/7020（ふっ素樹脂）、うず巻形等
- **玖基、協鋼**：油封（オイルシール）、密封件

## 回答策略
1. **積極提取資訊**：即使文檔只有部分相關內容，也要盡可能提取有用資訊
2. **多語言理解**：文檔可能是日文，請翻譯重點給用戶
3. **產品推薦**：根據用戶需求（耐熱、耐壓、材質等）推薦適合的產品系列
4. **規格表格化**：用 Markdown 表格呈現規格對比
5. **誠實但有建設性**：如果找不到精確資料，提供相關產品建議或後續步驟

## 回答格式
1. 直接回答用戶問題
2. 提供相關產品資訊（型號、特性、應用）
3. 如有規格數據，用表格呈現
4. 標註資料來源

## 參考文檔
{context}

## 客戶問題
{input}

## 回答
請根據上述文檔內容回答。如果文檔中有相關產品資訊（即使不完全匹配），也要提供給用戶參考。""",

    "business": """你是三新的業務分析助理。

## 輸出格式
**查詢結果**
- 筆數、時間範圍

**詳細記錄**（表格，最多 20 筆）
| 日期 | 業務 | 客戶 | 類型 | 內容摘要 |

**統計分析**
- 客戶分佈、活動類型

<業務記錄>
{context}
</業務記錄>

查詢：{input}

分析報告：""",

    "personal": """你是用戶的個人知識助理。

## 任務
根據用戶的個人文件回答問題。

## 回答規則
1. **直接引用**：盡可能直接引用文件中的原文內容
2. **完整資訊**：提供文件中所有相關的細節（天數、條件、流程等）
3. 如有相關圖片，提及「請參考下方圖片」
4. 如找不到，明確說明

## 參考文件
{context}

## 問題
{input}

## 回答（請直接引用文件內容，提供完整資訊）""",

    "mixed": """你是三新的智慧助理。

根據以下資料回答問題：

## 資料
{context}

## 問題
{input}

## 綜合回答"""
}

# ═══════════════════════════════════════════════════════════════
# 關鍵字設定
# ═══════════════════════════════════════════════════════════════

# 關鍵字提取模式
KEYWORD_PATTERNS = [
    r'[A-Z]{2,}\d*[A-Za-z]*',           # IBM, SMC, AS400
    r'[A-Za-z]+[-_][A-Za-z0-9]+',       # i-Access, VF-123
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',  # IP 地址
    r'[A-Za-z]+\.[A-Za-z]{2,4}',        # 檔案名 xxx.exe
    r'No\.\s*\d+',                       # No.6500
    r'[A-Z]{1,3}\d{3,}[A-Z]*',          # GF300, MXJ6
]

# 營業所同義詞
BRANCH_SYNONYMS = {
    "台北": ["臺北", "北部", "總公司", "台北營業所"],
    "台中": ["臺中", "中部", "台中營業所"],
    "台南": ["臺南", "南部", "台南營業所"],
    "高雄": ["高雄", "南部", "高雄營業所"],
}

# 中文停用詞
CHINESE_STOPWORDS = {
    '的', '是', '在', '和', '了', '有', '這', '個', '不', '為',
    '上', '下', '中', '請', '到', '把', '被', '讓', '給', '跟',
    '與', '及', '或', '但', '而', '因', '所', '以', '就', '都',
}

# ═══════════════════════════════════════════════════════════════
# 複雜度評估設定
# ═══════════════════════════════════════════════════════════════

COMPLEXITY_THRESHOLDS = {
    "query_length": 100,      # 超過此長度視為複雜
    "model_count": 2,         # 超過此數量的產品型號視為複雜
    "doc_count": 5,           # 超過此數量的文檔視為複雜
}

COMPARISON_KEYWORDS = ['比較', '差異', '不同', '哪個', 'vs', '對比', '優缺點']
ANALYSIS_KEYWORDS = ['計算', '估算', '分析', '統計', '趨勢', '預測']

# ═══════════════════════════════════════════════════════════════
# 成本估算
# ═══════════════════════════════════════════════════════════════

# 價格（每 1M tokens，USD）
TOKEN_PRICES = {
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "text-embedding-3-large": {"input": 0.13},
    "text-embedding-3-small": {"input": 0.02},
}

# ═══════════════════════════════════════════════════════════════
# 日誌設定
# ═══════════════════════════════════════════════════════════════

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# ═══════════════════════════════════════════════════════════════
# 輔助函數
# ═══════════════════════════════════════════════════════════════

def get_llm_config(query_type: str, complexity: str = "simple") -> LLMConfig:
    """根據查詢類型和複雜度取得 LLM 配置"""
    if query_type == "technical":
        key = f"technical_{complexity}"
    else:
        key = query_type
    
    return LLM_CONFIGS.get(key, LLM_CONFIGS["default"])


def get_retriever_config(query_type: str) -> RetrieverConfig:
    """取得 Retriever 配置"""
    return RETRIEVER_CONFIGS.get(query_type, RETRIEVER_CONFIGS["technical"])


def get_chunk_config(doc_type: str) -> ChunkConfig:
    """取得 Chunk 配置"""
    return CHUNK_CONFIGS.get(doc_type, CHUNK_CONFIGS["technical"])


def validate_config():
    """驗證配置"""
    errors = []
    
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY 未設定")
    

    # ── Provider/Model 防呆：避免選 Claude 卻使用 GPT 模型（或反之）
    selected_provider = _provider_for_model_selection()
    for kind in ("COMPLEX","SIMPLE","BUSINESS","PERSONAL","DEFAULT"):
        mname = resolve_llm_model(kind, "gpt-4o-mini", "claude-3-5-haiku-20241022")
        if selected_provider in ("anthropic","claude") and mname.lower().startswith(("gpt-","o1","o3","text-")):
            errors.append(f"LLM provider=anthropic 但模型 {kind} 看起來是 OpenAI：{mname}（請改用 ANTHROPIC_MODEL_{kind} 或 LLM_MODEL_{kind}）")
        if selected_provider == "openai" and mname.lower().startswith("claude-"):
            errors.append(f"LLM provider=openai 但模型 {kind} 看起來是 Claude：{mname}（請改用 OPENAI_MODEL_{kind} 或 LLM_MODEL_{kind}）")

    if RERANKER_CONFIG.enabled and RERANKER_CONFIG.type == "cohere":
        if not os.getenv(RERANKER_CONFIG.cohere_api_key_env):
            errors.append(f"Reranker 啟用但 {RERANKER_CONFIG.cohere_api_key_env} 未設定")

    if errors:
        print("⚠️ 配置警告:")
        for e in errors:
            print(f"  - {e}")

    return len(errors) == 0


# 啟動時驗證
if __name__ != "__main__":
    validate_config()
