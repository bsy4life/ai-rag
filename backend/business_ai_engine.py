# business_ai_engine.py - 純 AI 驅動的業務智能查詢引擎
"""
功能：
1. AI 意圖解析 - 不再硬編碼規則，由 LLM 理解查詢意圖
2. 動態代碼生成 - AI 生成 Pandas 查詢代碼
3. BI 分析層 - 趨勢分析、異常偵測、智能建議
4. 自然語言回覆 - 將數據轉為人類易讀的洞察
5. 支援從 PostgreSQL 資料庫讀取（不再依賴 CSV）

使用方式：
    from business_ai_engine import BusinessAIEngine
    
    engine = BusinessAIEngine()
    result = engine.query("台南營業所最近一個月的業績如何？有什麼值得注意的趨勢？")
    print(result['answer'])
"""

import os
import re
import json
import logging
import traceback
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 依賴檢查
# ═══════════════════════════════════════════════════════════════

try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False
    logger.warning("pandas 未安裝，業務 AI 引擎將無法運作")

# ═══════════════════════════════════════════════════════════════
# 資料庫連接（PostgreSQL）
# ═══════════════════════════════════════════════════════════════

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False
    logger.warning("psycopg2 未安裝，無法從資料庫讀取")


def get_db_connection():
    """取得資料庫連接"""
    if not _HAS_PSYCOPG2:
        return None
    
    try:
        conn = psycopg2.connect(
            host=os.getenv('PG_HOST', '192.168.0.227'),
            port=os.getenv('PG_PORT', '5432'),
            database=os.getenv('PG_NAME', 'ai_db'),
            user=os.getenv('PG_USER', 'ai_user'),
            password=os.getenv('PG_PASSWORD', 'sanshin2025'),
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        logger.error(f"資料庫連接失敗: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# 數據結構
# ═══════════════════════════════════════════════════════════════

class QueryIntent(Enum):
    """查詢意圖類型"""
    AGGREGATE = "aggregate"      # 聚合統計（總數、平均等）
    LIST = "list"                # 列出明細
    TREND = "trend"              # 趨勢分析
    COMPARE = "compare"          # 比較分析
    ANOMALY = "anomaly"          # 異常偵測
    FORECAST = "forecast"        # 預測
    RANKING = "ranking"          # 排名
    SEARCH = "search"            # 搜尋特定記錄


@dataclass
class ParsedIntent:
    """解析後的查詢意圖"""
    intent: QueryIntent
    time_range: Optional[Dict] = None      # {"start": date, "end": date}
    filters: Dict = field(default_factory=dict)  # {"branch": "台南營業所", "worker": "張三"}
    metrics: List[str] = field(default_factory=list)  # ["拜訪次數", "客戶數"]
    group_by: List[str] = field(default_factory=list)  # ["Worker", "Customer"]
    sort_by: Optional[str] = None
    limit: Optional[int] = None
    raw_query: str = ""


@dataclass
class AnalysisResult:
    """分析結果"""
    answer: str                           # 自然語言回答
    data_summary: Dict                    # 數據摘要
    insights: List[str]                   # BI 洞察
    recommendations: List[str]            # 建議行動
    visualizations: List[Dict] = field(default_factory=list)  # 圖表建議
    raw_data: Optional[Any] = None        # 原始數據（可選）
    code_executed: str = ""               # 執行的代碼
    metadata: Dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# Schema 定義（讓 AI 理解數據結構）
# ═══════════════════════════════════════════════════════════════

BUSINESS_DATA_SCHEMA = """
業務日報數據結構（來源：PostgreSQL business.reports）：

欄位說明：
- Date: 日期 (格式: YYYY-MM-DD)
- Worker: 業務員姓名
- Customer: 客戶名稱
- Class: 活動類型 (如: 業務拜訪, 送貨, 報價, 電話聯繫, 會議, 維修服務)
- Content: 活動內容描述
- Depart: 營業所/部門 (如: 台南營業所, 台中營業所, 高雄營業所, 台北營業所)
- Level: 等級 (A/B/C)
- Doc_Status: 文件狀態

執行環境已提供的變數（不需要 import）：
- df: 業務數據 DataFrame
- pd: pandas 模組
- datetime: datetime 類別  
- timedelta: timedelta 類別
- re: 正則表達式模組

常見查詢模式：
1. 時間範圍過濾: df[df['_Date'] >= start_date]
2. 營業所過濾: df[df['Depart'].str.contains('台南')]
3. 業務員過濾: df[df['Worker'] == '張三']
4. 客戶過濾: df[df['Customer'].str.contains('東台')]
5. 活動類型過濾: df[df['Class'].str.contains('業務拜訪')]

重要提醒：
- 日期欄位 '_Date' 是 datetime 類型，已經在數據預處理時建立
- 使用 .str.contains() 進行模糊匹配
- 使用 pd.Timestamp 處理日期比較
- 不要使用 import 語句！
"""


# ═══════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════

INTENT_PARSING_PROMPT = """你是一個業務數據分析助手。請分析用戶的查詢意圖，並提取關鍵信息。

用戶查詢：{query}

當前日期：{today}

請以 JSON 格式回答，包含以下欄位：
{{
    "intent": "aggregate|list|trend|compare|anomaly|ranking|search",
    "time_range": {{
        "type": "relative|absolute|none",
        "value": "最近30天|2024年1月|2024/01/01-2024/01/31",
        "start": "YYYY-MM-DD 或 null",
        "end": "YYYY-MM-DD 或 null"
    }},
    "filters": {{
        "branch": "營業所名稱或null",
        "worker": "業務員名稱或null",
        "customer": "客戶名稱或null",
        "activity_type": "活動類型或null"
    }},
    "metrics": ["要計算的指標，如拜訪次數、客戶數等"],
    "group_by": ["分組欄位，如Worker、Customer、Depart等"],
    "analysis_focus": "用戶關注的分析重點描述"
}}

只回答 JSON，不要有其他文字。"""


CODE_GENERATION_PROMPT = """你是一個 Python/Pandas 專家。請根據用戶意圖生成查詢代碼。

{schema}

用戶查詢：{query}
解析後的意圖：{intent_json}
當前日期：{today}

請生成 Python 代碼，使用變數 `df` 作為輸入 DataFrame。

【重要限制】
1. 不要使用 import 語句！以下變數已可用：df, pd, datetime, timedelta, re
2. 必須按照以下順序編寫代碼：
   - 第一步：建立過濾條件 mask
   - 第二步：過濾數據得到 filtered = df[mask]
   - 第三步：基於 filtered 進行統計分析，存入 result
   - 第四步：建立 summary 字典
3. 所有對 filtered 的引用必須在 filtered = df[mask] 之後

【代碼模板 - 必須遵循此結構】
```python
# 第一步：建立過濾條件
mask = pd.Series([True] * len(df))

# 時間過濾（根據需要調整日期）
mask = mask & (df['_Date'] >= pd.Timestamp('2024-10-01'))
mask = mask & (df['_Date'] <= pd.Timestamp('2024-10-31'))

# 其他過濾（客戶、業務員等）
mask = mask & (df['Customer'].str.contains('台塑', na=False))

# 第二步：執行過濾
filtered = df[mask]

# 第三步：統計分析（必須在 filtered 定義之後）
result = filtered[['Date', 'Worker', 'Customer', 'Class', 'Content']].copy()

# 或者做分組統計
# result = filtered.groupby('Worker').agg({{
#     'Customer': 'nunique',
#     'Date': 'count'
# }})

# 第四步：建立摘要
summary = {{
    'total_records': len(filtered),
    'unique_workers': filtered['Worker'].nunique() if len(filtered) > 0 else 0,
    'unique_customers': filtered['Customer'].nunique() if len(filtered) > 0 else 0
}}
```

只輸出可執行的 Python 代碼，不要有 markdown 標記，不要有 import 語句。
確保 filtered 變數在被引用前已經定義！"""


ANALYSIS_PROMPT = """你是一個專業的業務分析顧問。請根據查詢結果提供深入的 BI 分析。

原始查詢：{query}
數據摘要：{summary}
詳細結果：{result_preview}

請提供：
1. **直接回答**：用自然語言回答用戶的問題（2-3 句話）
2. **關鍵洞察**：從數據中發現的 3-5 個重要發現
3. **趨勢分析**：如果數據涉及時間，分析變化趨勢
4. **異常偵測**：標出任何異常或值得注意的數據點
5. **建議行動**：基於分析結果，提出 2-3 個具體的行動建議

請以 JSON 格式回答：
{{
    "direct_answer": "直接回答用戶問題...",
    "insights": ["洞察1", "洞察2", "洞察3"],
    "trends": ["趨勢描述1", "趨勢描述2"],
    "anomalies": ["異常1", "異常2"],
    "recommendations": ["建議1", "建議2", "建議3"],
    "visualization_suggestions": [
        {{"type": "bar", "title": "圖表標題", "x": "欄位", "y": "欄位"}},
        {{"type": "line", "title": "趨勢圖", "x": "Date", "y": "count"}}
    ]
}}

只回答 JSON，不要有其他文字。"""


# ═══════════════════════════════════════════════════════════════
# LLM 客戶端
# ═══════════════════════════════════════════════════════════════

class LLMClient:
    """LLM 客戶端（支援 OpenAI 和 Anthropic）"""
    
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        
        # 處理 auto 模式：根據 LLM_PRIMARY 決定優先使用哪個
        if self.provider == "auto":
            primary = os.getenv("LLM_PRIMARY", "anthropic").strip().lower()
            if primary in ("anthropic", "claude"):
                self.provider = "anthropic"
            else:
                self.provider = "openai"
            logger.info(f"🔄 Auto 模式，選擇 primary: {self.provider}")
        
        # 業務分析專用模型
        self.model = os.getenv("LLM_MODEL_BUSINESS", "gpt-4o")
        
        self._client = None
        self._init_client()
    
    def _init_client(self):
        """初始化客戶端"""
        if self.provider in ("anthropic", "claude") and self.anthropic_key:
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.anthropic_key)
                self.provider = "anthropic"
                self.model = os.getenv("ANTHROPIC_MODEL_BUSINESS", "claude-sonnet-4-20250514")
                logger.info(f"✅ 業務 AI 引擎使用 Anthropic: {self.model}")
            except ImportError:
                logger.warning("anthropic 套件未安裝，降級到 OpenAI")
                self._init_openai()
        else:
            self._init_openai()
    
    def _init_openai(self):
        """初始化 OpenAI"""
        if self.openai_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.openai_key)
                self.provider = "openai"
                self.model = os.getenv("OPENAI_MODEL_BUSINESS", "gpt-4o")
                logger.info(f"✅ 業務 AI 引擎使用 OpenAI: {self.model}")
            except ImportError:
                raise RuntimeError("需要安裝 openai 或 anthropic 套件")
    
    def chat(self, prompt: str, system: str = None, temperature: float = 0.1) -> str:
        """發送聊天請求"""
        try:
            if self.provider == "anthropic":
                return self._chat_anthropic(prompt, system, temperature)
            else:
                return self._chat_openai(prompt, system, temperature)
        except Exception as e:
            error_msg = str(e)
            if "usage limits" in error_msg or "quota" in error_msg.lower():
                logger.warning(f"⚠️ {self.provider} 限額，嘗試 fallback: {e}")
                return self._fallback_chat(prompt, system, temperature)
            else:
                raise
    
    def _chat_openai(self, prompt: str, system: str = None, temperature: float = 0.1) -> str:
        """OpenAI 聊天"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=4000,
        )
        return response.choices[0].message.content
    
    def _chat_anthropic(self, prompt: str, system: str = None, temperature: float = 0.1) -> str:
        """Anthropic 聊天"""
        kwargs = {
            "model": self.model,
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        
        response = self._client.messages.create(**kwargs)
        return response.content[0].text
    
    def _fallback_chat(self, prompt: str, system: str = None, temperature: float = 0.1) -> str:
        """Fallback 到另一個提供商"""
        if self.provider == "anthropic" and self.openai_key:
            from openai import OpenAI
            fallback_client = OpenAI(api_key=self.openai_key)
            fallback_model = os.getenv("OPENAI_MODEL_BUSINESS", "gpt-4o")
            
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            response = fallback_client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=4000,
            )
            return response.choices[0].message.content
        raise RuntimeError("無可用的 LLM 提供商")


# ═══════════════════════════════════════════════════════════════
# 業務 AI 引擎
# ═══════════════════════════════════════════════════════════════

class BusinessAIEngine:
    """純 AI 驅動的業務智能查詢引擎"""
    
    def __init__(self, csv_path: str = None, use_database: bool = True):
        """
        初始化引擎
        
        Args:
            csv_path: 業務 CSV 檔案路徑（可選，會自動偵測）
            use_database: 是否優先從資料庫讀取（預設 True）
        """
        if not _HAS_PANDAS:
            raise RuntimeError("需要安裝 pandas: pip install pandas")
        
        self.use_database = use_database and _HAS_PSYCOPG2
        self.csv_path = csv_path or self._detect_csv_path()
        self.llm = LLMClient()
        self.df = None
        self.data_source = None  # 'database' 或 'csv'
        self._load_data()
    
    def _detect_csv_path(self) -> Optional[str]:
        """自動偵測 CSV 路徑"""
        candidates = [
            os.environ.get("BUSINESS_CSV_FILE"),
            "/app/data/business/clean_business.csv",
            "./data/business/clean_business.csv",
            "./business/clean_business.csv",
            "clean_business.csv",
        ]
        for p in candidates:
            if p and os.path.exists(p):
                return p
        return None
    
    def _load_data(self):
        """載入並預處理數據（優先從資料庫）"""
        # 嘗試從資料庫載入
        if self.use_database:
            if self._load_data_from_database():
                return
            logger.warning("資料庫載入失敗，嘗試 CSV fallback")
        
        # Fallback 到 CSV
        self._load_data_from_csv()
    
    def _load_data_from_database(self) -> bool:
        """從 PostgreSQL 資料庫載入業務日報"""
        conn = get_db_connection()
        if not conn:
            return False
        
        try:
            cursor = conn.cursor()
            
            # 查詢業務日報（最近 12 個月）
            cursor.execute('''
                SELECT 
                    r.report_date as "Date",
                    u.name as "Worker",
                    r.customer_name as "Customer",
                    r.activity_class as "Class",
                    r.content as "Content",
                    u.department as "Depart",
                    r.level as "Level",
                    r.status as "Doc_Status",
                    r.created_at as "TimeCreated"
                FROM business.reports r
                JOIN public.users u ON r.user_id = u.id
                WHERE r.report_date >= CURRENT_DATE - INTERVAL '12 months'
                ORDER BY r.report_date DESC
            ''')
            
            rows = cursor.fetchall()
            
            if not rows:
                logger.warning("資料庫中沒有業務日報資料")
                return False
            
            # 轉換為 DataFrame
            self.df = pd.DataFrame([dict(row) for row in rows])
            
            # 預處理日期
            self.df['Date'] = pd.to_datetime(self.df['Date']).dt.strftime('%Y/%m/%d')
            self.df['_Date'] = pd.to_datetime(self.df['Date'], errors='coerce')
            
            # 清理空值
            for col in ['Worker', 'Customer', 'Class', 'Depart', 'Content']:
                if col in self.df.columns:
                    self.df[col] = self.df[col].fillna('').astype(str)
            
            self.data_source = 'database'
            logger.info(f"✅ 從資料庫載入業務數據: {len(self.df)} 筆記錄")
            return True
            
        except Exception as e:
            logger.error(f"從資料庫載入失敗: {e}")
            return False
        finally:
            conn.close()
    
    def _load_data_from_csv(self):
        """從 CSV 載入數據（fallback）"""
        if not self.csv_path or not os.path.exists(self.csv_path):
            logger.warning(f"業務 CSV 不存在: {self.csv_path}")
            return
        
        try:
            self.df = pd.read_csv(self.csv_path, encoding='utf-8')
            self.df = self.df.dropna(how='all')
            
            # 預處理日期
            self.df['_Date'] = pd.to_datetime(self.df['Date'], errors='coerce')
            
            # 清理空值
            for col in ['Worker', 'Customer', 'Class', 'Depart', 'Content']:
                if col in self.df.columns:
                    self.df[col] = self.df[col].fillna('').astype(str)
            
            self.data_source = 'csv'
            logger.info(f"✅ 從 CSV 載入業務數據: {len(self.df)} 筆記錄")
        except Exception as e:
            logger.error(f"載入業務數據失敗: {e}")
            self.df = None
    
    def reload_data(self):
        """重新載入數據"""
        self._load_data()
    
    def _parse_intent(self, query: str) -> Dict:
        """使用 AI 解析查詢意圖"""
        prompt = INTENT_PARSING_PROMPT.format(
            query=query,
            today=datetime.now().strftime("%Y-%m-%d")
        )
        
        try:
            response = self.llm.chat(prompt, temperature=0.0)
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)
            
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning(f"意圖解析 JSON 錯誤: {e}")
            return {"intent": "search", "filters": {}, "metrics": []}
        except Exception as e:
            logger.error(f"意圖解析失敗: {e}")
            return {"intent": "search", "filters": {}, "metrics": []}
    
    def _generate_code(self, query: str, intent: Dict) -> str:
        """使用 AI 生成查詢代碼"""
        prompt = CODE_GENERATION_PROMPT.format(
            schema=BUSINESS_DATA_SCHEMA,
            query=query,
            intent_json=json.dumps(intent, ensure_ascii=False, indent=2),
            today=datetime.now().strftime("%Y-%m-%d")
        )
        
        try:
            response = self.llm.chat(prompt, temperature=0.0)
            code = response.strip()
            
            # 清理 markdown
            if code.startswith("```"):
                code = re.sub(r'^```\w*\n?', '', code)
                code = re.sub(r'\n?```$', '', code)
            
            # 移除 import
            code = re.sub(r'^import\s+.*$', '', code, flags=re.MULTILINE)
            code = re.sub(r'^from\s+.*import\s+.*$', '', code, flags=re.MULTILINE)
            
            return code.strip()
        except Exception as e:
            logger.error(f"代碼生成失敗: {e}")
            return ""
    
    def _execute_code(self, code: str) -> Tuple[Any, Dict, Optional[str]]:
        """執行生成的代碼"""
        if self.df is None or self.df.empty:
            return None, {}, "數據未載入"
        
        local_vars = {
            'df': self.df.copy(),
            'pd': pd,
            'datetime': datetime,
            'timedelta': timedelta,
            're': re,
        }
        
        # Provide safe built-in functions for code execution
        safe_builtins = {
            'len': len,
            'int': int,
            'str': str,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'tuple': tuple,
            'set': set,
            'sum': sum,
            'min': min,
            'max': max,
            'abs': abs,
            'round': round,
            'sorted': sorted,
            'enumerate': enumerate,
            'zip': zip,
            'range': range,
            'True': True,
            'False': False,
            'None': None,
        }
        
        try:
            exec(code, {"__builtins__": safe_builtins}, local_vars)
            
            result = local_vars.get('result')
            summary = local_vars.get('summary', {})
            
            if result is None:
                result = local_vars.get('filtered')
            
            return result, summary, None
            
        except Exception as e:
            logger.error(f"代碼執行錯誤: {e}\n代碼:\n{code}")
            return None, {}, str(e)
    
    def _fallback_query(self, query: str, intent: Dict) -> Tuple[Any, Dict, Optional[str]]:
        """簡單的 fallback 查詢"""
        if self.df is None or self.df.empty:
            return None, {}, "數據未載入"
        
        try:
            df = self.df.copy()
            mask = pd.Series([True] * len(df))
            
            filters = intent.get('filters', {})
            
            if filters.get('branch'):
                mask = mask & df['Depart'].str.contains(filters['branch'], na=False)
            
            if filters.get('worker'):
                mask = mask & df['Worker'].str.contains(filters['worker'], na=False)
            
            if filters.get('customer'):
                mask = mask & df['Customer'].str.contains(filters['customer'], na=False)
            
            time_range = intent.get('time_range', {})
            if time_range.get('start'):
                start = pd.Timestamp(time_range['start'])
                mask = mask & (df['_Date'] >= start)
            if time_range.get('end'):
                end = pd.Timestamp(time_range['end'])
                mask = mask & (df['_Date'] <= end)
            
            filtered = df[mask]
            
            summary = {
                'total_records': len(filtered),
                'unique_workers': filtered['Worker'].nunique() if len(filtered) > 0 else 0,
                'unique_customers': filtered['Customer'].nunique() if len(filtered) > 0 else 0,
            }
            
            result = filtered[['Date', 'Worker', 'Customer', 'Class', 'Content']].head(100)
            
            return result, summary, None
            
        except Exception as e:
            return None, {}, str(e)
    
    def _analyze_result(self, query: str, result: Any, summary: Dict) -> Dict:
        """使用 AI 分析結果"""
        if isinstance(result, pd.DataFrame):
            result_preview = result.head(30).to_string() if len(result) > 0 else "（無數據）"
        else:
            result_preview = str(result)[:2000]
        
        prompt = ANALYSIS_PROMPT.format(
            query=query,
            summary=json.dumps(summary, ensure_ascii=False, default=str),
            result_preview=result_preview
        )
        
        try:
            response = self.llm.chat(prompt, temperature=0.3)
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)
            
            return json.loads(response)
        except:
            return {
                "direct_answer": "查詢完成，請查看下方數據。",
                "insights": [],
                "trends": [],
                "anomalies": [],
                "recommendations": [],
            }
    
    def _format_output(self, query: str, result: Any, summary: Dict, analysis: Dict, code: str) -> AnalysisResult:
        """格式化最終輸出"""
        answer_parts = []
        
        # 直接回答
        if analysis.get("direct_answer"):
            answer_parts.append(f"📊 {analysis['direct_answer']}")
        
        # 數據摘要
        answer_parts.append(f"\n\n**數據摘要**")
        answer_parts.append(f"- 總記錄數：{summary.get('total_records', 0)}")
        answer_parts.append(f"- 業務員數：{summary.get('unique_workers', 0)}")
        answer_parts.append(f"- 客戶數：{summary.get('unique_customers', 0)}")
        answer_parts.append(f"- 資料來源：{self.data_source or 'unknown'}")
        
        # 洞察
        if analysis.get("insights"):
            answer_parts.append("\n\n💡 **關鍵洞察**")
            for insight in analysis["insights"]:
                answer_parts.append(f"- {insight}")
        
        # 趨勢
        if analysis.get("trends"):
            answer_parts.append("\n\n📈 **趨勢分析**")
            for trend in analysis["trends"]:
                answer_parts.append(f"- {trend}")
        
        # 建議
        if analysis.get("recommendations"):
            answer_parts.append("\n\n✅ **建議行動**")
            for rec in analysis["recommendations"]:
                answer_parts.append(f"- {rec}")
        
        # 數據表格
        if isinstance(result, pd.DataFrame) and len(result) > 0 and len(result) <= 50:
            answer_parts.append("\n\n📋 **詳細數據**")
            answer_parts.append(self._df_to_markdown(result.head(30)))
        
        answer_parts.append("\n\n📋 參考資料來源：business")
        
        return AnalysisResult(
            answer="\n".join(answer_parts),
            data_summary=summary,
            insights=analysis.get("insights", []),
            recommendations=analysis.get("recommendations", []),
            visualizations=analysis.get("visualization_suggestions", []),
            raw_data=result if isinstance(result, (dict, list)) else None,
            code_executed=code,
            metadata={
                "query": query,
                "llm_model": self.llm.model,
                "data_source": self.data_source,
                "timestamp": datetime.now().isoformat(),
            }
        )
    
    def _df_to_markdown(self, df: pd.DataFrame, max_rows: int = 30) -> str:
        """將 DataFrame 轉為 Markdown 表格"""
        if df.empty:
            return ""
        
        df_show = df.head(max_rows)
        cols = list(df_show.columns)
        
        header = "| " + " | ".join(str(c) for c in cols) + " |"
        sep = "|" + "|".join(["---"] * len(cols)) + "|"
        
        rows = []
        for _, r in df_show.iterrows():
            row_vals = []
            for c in cols:
                val = str(r.get(c, ""))[:60]
                val = val.replace("|", "｜").replace("\n", " ")
                row_vals.append(val)
            rows.append("| " + " | ".join(row_vals) + " |")
        
        return header + "\n" + sep + "\n" + "\n".join(rows)
    
    def query(self, query: str) -> Dict:
        """
        主查詢入口
        
        Args:
            query: 自然語言查詢
        
        Returns:
            {
                "answer": "自然語言回答",
                "success": True/False,
                "data_summary": {...},
                "data_source": "database" | "csv",
                ...
            }
        """
        if not query or not query.strip():
            return {"answer": "請輸入有效的查詢。", "success": False}
        
        if self.df is None or self.df.empty:
            return {"answer": "業務數據未載入。請確認資料庫連接或 CSV 檔案。", "success": False}
        
        try:
            # Step 1: AI 解析意圖
            logger.info(f"🔍 解析查詢意圖: {query[:50]}...")
            intent = self._parse_intent(query)
            
            # Step 2: AI 生成代碼
            logger.info("🔧 生成查詢代碼...")
            code = self._generate_code(query, intent)
            
            if not code:
                return {"answer": "無法生成查詢代碼。", "success": False}
            
            # Step 3: 執行代碼
            logger.info("⚡ 執行查詢...")
            result, summary, error = self._execute_code(code)
            
            if error:
                logger.warning(f"代碼執行失敗，嘗試 fallback: {error}")
                result, summary, fallback_error = self._fallback_query(query, intent)
                
                if fallback_error or result is None:
                    return {"answer": f"查詢執行錯誤：{error[:500]}", "success": False}
            
            if result is None or (isinstance(result, pd.DataFrame) and len(result) == 0):
                return {
                    "answer": "查詢完成，但未找到符合條件的數據。",
                    "success": True,
                    "data_summary": summary,
                    "data_source": self.data_source,
                }
            
            # Step 4: AI 分析結果
            logger.info("📊 分析結果...")
            analysis = self._analyze_result(query, result, summary)
            
            # Step 5: 格式化輸出
            output = self._format_output(query, result, summary, analysis, code)
            
            return {
                "answer": output.answer,
                "success": True,
                "data_summary": output.data_summary,
                "data_source": self.data_source,
                "insights": output.insights,
                "recommendations": output.recommendations,
                "visualizations": output.visualizations,
                "metadata": output.metadata,
            }
            
        except Exception as e:
            logger.error(f"查詢失敗: {e}\n{traceback.format_exc()}")
            return {"answer": f"查詢過程發生錯誤：{str(e)}", "success": False}
    
    def get_schema_info(self) -> Dict:
        """獲取數據 schema 信息"""
        if self.df is None:
            return {"loaded": False}
        
        return {
            "loaded": True,
            "data_source": self.data_source,
            "total_records": len(self.df),
            "columns": list(self.df.columns),
            "date_range": {
                "min": self.df['_Date'].min().isoformat() if not self.df['_Date'].isna().all() else None,
                "max": self.df['_Date'].max().isoformat() if not self.df['_Date'].isna().all() else None,
            },
            "unique_values": {
                "workers": self.df['Worker'].nunique() if 'Worker' in self.df.columns else 0,
                "customers": self.df['Customer'].nunique() if 'Customer' in self.df.columns else 0,
                "branches": self.df['Depart'].unique().tolist() if 'Depart' in self.df.columns else [],
            },
        }
    
    def get_quick_stats(self) -> Dict:
        """獲取快速統計"""
        if self.df is None:
            return {}
        
        today = datetime.now().date()
        last_30_days = today - timedelta(days=30)
        
        recent = self.df[self.df['_Date'].dt.date >= last_30_days] if '_Date' in self.df.columns else self.df
        
        return {
            "data_source": self.data_source,
            "total_records": len(self.df),
            "recent_30_days": len(recent),
            "active_workers": recent['Worker'].nunique() if 'Worker' in recent.columns else 0,
            "active_customers": recent['Customer'].nunique() if 'Customer' in recent.columns else 0,
            "top_activities": recent['Class'].value_counts().head(5).to_dict() if 'Class' in recent.columns else {},
            "by_branch": recent.groupby('Depart').size().to_dict() if 'Depart' in recent.columns else {},
        }


# ═══════════════════════════════════════════════════════════════
# 便捷函數（向後兼容）
# ═══════════════════════════════════════════════════════════════

_engine: Optional[BusinessAIEngine] = None

def get_business_ai_engine() -> BusinessAIEngine:
    """獲取業務 AI 引擎單例"""
    global _engine
    if _engine is None:
        _engine = BusinessAIEngine()
    return _engine

def ai_business_query(query: str) -> str:
    """
    AI 業務查詢（簡化接口，向後兼容）
    """
    engine = get_business_ai_engine()
    result = engine.query(query)
    return result.get("answer", "查詢失敗")


# ═══════════════════════════════════════════════════════════════
# CLI 測試
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    engine = BusinessAIEngine()
    
    print("\n" + "="*60)
    print("🤖 業務 AI 查詢引擎 - 互動模式")
    print("="*60)
    print(f"數據狀態: {engine.get_schema_info()}")
    print("\n輸入 'quit' 退出\n")
    
    while True:
        try:
            query = input("📝 您的問題: ").strip()
            if query.lower() in ('quit', 'exit', 'q'):
                break
            if not query:
                continue
            
            print("\n⏳ 處理中...\n")
            result = engine.query(query)
            print(result["answer"])
            print("\n" + "-"*60 + "\n")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"錯誤: {e}")
    
    print("\n👋 再見！")
