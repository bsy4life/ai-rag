# business_ai_engine.py - 純 AI 驅動的業務智能查詢引擎
"""
功能：
1. AI 意圖解析 - 不再硬編碼規則，由 LLM 理解查詢意圖
2. 動態代碼生成 - AI 生成 Pandas 查詢代碼
3. BI 分析層 - 趨勢分析、異常偵測、智能建議
4. 自然語言回覆 - 將數據轉為人類易讀的洞察

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
業務日報 CSV 數據結構：

欄位說明：
- Date: 日期 (格式: YYYY/MM/DD)
- Worker: 業務員姓名
- Customer: 客戶名稱
- Class: 活動類型 (如: 業務拜訪, 送貨, 報價, 電話聯繫, 會議, 維修服務)
- Content: 活動內容描述
- Depart: 營業所 (如: 台南營業所, 台中營業所, 高雄營業所, 台北營業所)
- Manager: 主管姓名
- Level: 等級
- Doc_Status: 文件狀態
- TimeCreated: 建立時間
- Doc_Time: 文件時間

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
        """發送聊天請求（帶 fallback）"""
        try:
            if self.provider == "anthropic":
                return self._chat_anthropic(prompt, system, temperature)
            else:
                return self._chat_openai(prompt, system, temperature)
        except Exception as e:
            error_msg = str(e)
            # 檢查是否是限額錯誤
            if "usage limits" in error_msg or "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                logger.warning(f"⚠️ {self.provider} 限額，嘗試 fallback: {e}")
                return self._fallback_chat(prompt, system, temperature)
            else:
                raise
    
    def _fallback_chat(self, prompt: str, system: str = None, temperature: float = 0.1) -> str:
        """Fallback 到另一個提供商"""
        if self.provider == "anthropic" and self.openai_key:
            # Fallback 到 OpenAI
            try:
                from openai import OpenAI
                fallback_client = OpenAI(api_key=self.openai_key)
                fallback_model = os.getenv("OPENAI_MODEL_BUSINESS", "gpt-4o")
                
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})
                
                logger.info(f"🔄 Fallback 到 OpenAI: {fallback_model}")
                response = fallback_client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=4000,
                )
                logger.info("✅ Fallback 成功")
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"❌ Fallback 到 OpenAI 也失敗: {e}")
                raise
        elif self.provider == "openai" and self.anthropic_key:
            # Fallback 到 Anthropic
            try:
                from anthropic import Anthropic
                fallback_client = Anthropic(api_key=self.anthropic_key)
                fallback_model = os.getenv("ANTHROPIC_MODEL_BUSINESS", "claude-sonnet-4-20250514")
                
                kwargs = {
                    "model": fallback_model,
                    "max_tokens": 4000,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if system:
                    kwargs["system"] = system
                
                logger.info(f"🔄 Fallback 到 Anthropic: {fallback_model}")
                response = fallback_client.messages.create(**kwargs)
                logger.info("✅ Fallback 成功")
                return response.content[0].text
            except Exception as e:
                logger.error(f"❌ Fallback 到 Anthropic 也失敗: {e}")
                raise
        else:
            raise RuntimeError("無可用的 fallback 提供商")
    
    def _chat_openai(self, prompt: str, system: str = None, temperature: float = 0.1) -> str:
        """OpenAI 聊天（支援 o 系列推理模型）"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        # 檢測是否為 o 系列模型（o1, o3, gpt-5 等）
        # 這些模型不支援 max_tokens，要用 max_completion_tokens
        # 也不支援 temperature 參數
        model_lower = self.model.lower()
        is_reasoning_model = any(x in model_lower for x in ['o1', 'o3', 'gpt-5', 'o4'])
        
        if is_reasoning_model:
            # o 系列模型的參數
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=4000,
                # o 系列不支援 temperature
            )
        else:
            # 標準模型的參數
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


# ═══════════════════════════════════════════════════════════════
# 業務 AI 引擎
# ═══════════════════════════════════════════════════════════════

class BusinessAIEngine:
    """純 AI 驅動的業務智能查詢引擎"""
    
    def __init__(self, csv_path: str = None):
        """
        初始化引擎
        
        Args:
            csv_path: 業務 CSV 檔案路徑（可選，會自動偵測）
        """
        if not _HAS_PANDAS:
            raise RuntimeError("需要安裝 pandas: pip install pandas")
        
        self.csv_path = csv_path or self._detect_csv_path()
        self.llm = LLMClient()
        self.df = None
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
        """載入並預處理數據"""
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
            
            logger.info(f"✅ 載入業務數據: {len(self.df)} 筆記錄")
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
            # 清理 markdown 標記
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)
            
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning(f"意圖解析 JSON 錯誤: {e}, 原始回應: {response[:500]}")
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
            
            # 清理 markdown 標記
            code = response.strip()
            if code.startswith("```"):
                code = re.sub(r'^```\w*\n?', '', code)
                code = re.sub(r'\n?```$', '', code)
            
            return code
        except Exception as e:
            logger.error(f"代碼生成失敗: {e}")
            return ""
    
    def _preprocess_code(self, code: str) -> str:
        """
        預處理 AI 生成的代碼，修復常見問題
        """
        if not code:
            return code
        
        # 1. 移除 markdown 代碼塊標記
        code = re.sub(r'^```\w*\n?', '', code.strip())
        code = re.sub(r'\n?```$', '', code)
        
        # 2. 移除 import 語句（我們已經提供了所需模組）
        lines = code.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                logger.debug(f"移除 import 語句: {stripped}")
                continue
            cleaned_lines.append(line)
        code = '\n'.join(cleaned_lines)
        
        # 3. 修復括號不匹配問題
        code = self._fix_brackets(code)
        
        return code
    
    def _fix_brackets(self, code: str) -> str:
        """
        修復括號不匹配問題
        """
        # 計算各類括號的數量
        open_parens = code.count('(')
        close_parens = code.count(')')
        open_brackets = code.count('[')
        close_brackets = code.count(']')
        open_braces = code.count('{')
        close_braces = code.count('}')
        
        # 補齊缺少的右括號
        if open_parens > close_parens:
            missing = open_parens - close_parens
            code = code.rstrip() + ')' * missing
            logger.debug(f"補齊 {missing} 個右小括號")
        
        if open_brackets > close_brackets:
            missing = open_brackets - close_brackets
            code = code.rstrip() + ']' * missing
            logger.debug(f"補齊 {missing} 個右中括號")
        
        if open_braces > close_braces:
            missing = open_braces - close_braces
            code = code.rstrip() + '}' * missing
            logger.debug(f"補齊 {missing} 個右大括號")
        
        return code
    
    def _execute_code(self, code: str) -> Tuple[Any, Dict, str]:
        """
        安全執行生成的代碼
        
        Returns:
            (result, summary, error_message)
        """
        if self.df is None or self.df.empty:
            return None, {}, "數據未載入"
        
        # 準備安全的內建函數子集
        safe_builtins = {
            'len': len,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'tuple': tuple,
            'set': set,
            'range': range,
            'enumerate': enumerate,
            'zip': zip,
            'map': map,
            'filter': filter,
            'sorted': sorted,
            'sum': sum,
            'min': min,
            'max': max,
            'abs': abs,
            'round': round,
            'any': any,
            'all': all,
            'isinstance': isinstance,
            'hasattr': hasattr,
            'getattr': getattr,
            'print': print,  # 用於調試
            'True': True,
            'False': False,
            'None': None,
        }
        
        # 準備執行環境
        local_vars = {
            'df': self.df.copy(),
            'pd': pd,
            'datetime': datetime,
            'timedelta': timedelta,
            're': re,  # 正則表達式
        }
        
        # 預處理代碼：清理和修復常見問題
        code = self._preprocess_code(code)
        
        try:
            exec(code, {"__builtins__": safe_builtins}, local_vars)
            
            result = local_vars.get('result', local_vars.get('filtered', None))
            summary = local_vars.get('summary', {})
            
            # 如果沒有 summary，自動生成
            if not summary and result is not None:
                if isinstance(result, pd.DataFrame):
                    summary = {
                        'total_records': len(result),
                        'columns': list(result.columns),
                    }
                elif isinstance(result, pd.Series):
                    summary = {
                        'total_items': len(result),
                        'top_values': result.head(5).to_dict(),
                    }
            
            return result, summary, ""
            
        except Exception as e:
            error_msg = f"代碼執行錯誤: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            return None, {}, error_msg
    
    def _fallback_query(self, query: str, intent: Dict) -> Tuple[Any, Dict, str]:
        """
        當 AI 生成代碼失敗時的 fallback 查詢
        基於 intent 中的關鍵信息進行簡單過濾
        """
        try:
            df = self.df.copy()
            mask = pd.Series([True] * len(df))
            
            filters = intent.get("filters", {})
            time_range = intent.get("time_range", {})
            
            # 時間過濾
            if time_range.get("start"):
                try:
                    start = pd.Timestamp(time_range["start"])
                    mask = mask & (df['_Date'] >= start)
                except:
                    pass
            
            if time_range.get("end"):
                try:
                    end = pd.Timestamp(time_range["end"])
                    mask = mask & (df['_Date'] <= end)
                except:
                    pass
            
            # 根據月份過濾（從 time_range.value 提取）
            time_value = time_range.get("value", "")
            if "月" in str(time_value):
                month_match = re.search(r'(\d+)\s*月', str(time_value))
                if month_match:
                    month = int(month_match.group(1))
                    year = datetime.now().year
                    # 如果提到的月份大於當前月份，可能是去年
                    if month > datetime.now().month:
                        year -= 1
                    mask = mask & (df['_Date'].dt.month == month) & (df['_Date'].dt.year == year)
            
            # 客戶過濾
            if filters.get("customer"):
                customer = filters["customer"]
                mask = mask & (df['Customer'].astype(str).str.contains(customer, na=False, case=False))
            
            # 業務員過濾
            if filters.get("worker"):
                worker = filters["worker"]
                mask = mask & (df['Worker'].astype(str).str.contains(worker, na=False, case=False))
            
            # 營業所過濾
            if filters.get("branch"):
                branch = filters["branch"]
                mask = mask & (df['Depart'].astype(str).str.contains(branch, na=False, case=False))
            
            # 活動類型過濾
            if filters.get("activity_type"):
                activity = filters["activity_type"]
                mask = mask & (df['Class'].astype(str).str.contains(activity, na=False, case=False))
            
            # 從查詢文字中提取關鍵字作為補充過濾
            keywords_to_check = ['拜訪', '送貨', '報價', '維修', '會議']
            for kw in keywords_to_check:
                if kw in query:
                    mask = mask & (df['Class'].astype(str).str.contains(kw, na=False))
                    break
            
            filtered = df[mask]
            
            # 選擇顯示的欄位
            display_cols = ['Date', 'Worker', 'Customer', 'Class', 'Content', 'Depart']
            available_cols = [c for c in display_cols if c in filtered.columns]
            result = filtered[available_cols].copy()
            
            summary = {
                'total_records': len(result),
                'unique_workers': filtered['Worker'].nunique() if len(filtered) > 0 else 0,
                'unique_customers': filtered['Customer'].nunique() if len(filtered) > 0 else 0,
            }
            
            logger.info(f"Fallback 查詢結果: {len(result)} 筆記錄")
            return result, summary, ""
            
        except Exception as e:
            error_msg = f"Fallback 查詢錯誤: {str(e)}"
            logger.error(error_msg)
            return None, {}, error_msg
    
    def _analyze_result(self, query: str, result: Any, summary: Dict) -> Dict:
        """使用 AI 分析結果並生成洞察"""
        # 準備結果預覽
        if isinstance(result, pd.DataFrame):
            result_preview = result.head(20).to_string() if len(result) > 0 else "無數據"
        elif isinstance(result, pd.Series):
            result_preview = result.head(20).to_string()
        elif isinstance(result, dict):
            result_preview = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            result_preview = str(result)[:2000]
        
        prompt = ANALYSIS_PROMPT.format(
            query=query,
            summary=json.dumps(summary, ensure_ascii=False, default=str),
            result_preview=result_preview[:3000]  # 限制長度
        )
        
        try:
            response = self.llm.chat(prompt, temperature=0.2)
            
            # 清理 markdown 標記
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)
            
            return json.loads(response)
        except json.JSONDecodeError:
            # 如果 JSON 解析失敗，返回純文字回答
            return {
                "direct_answer": response[:500] if response else "分析完成",
                "insights": [],
                "recommendations": [],
            }
        except Exception as e:
            logger.error(f"結果分析失敗: {e}")
            return {
                "direct_answer": "分析過程發生錯誤",
                "insights": [],
                "recommendations": [],
            }
    
    def _format_output(self, query: str, result: Any, summary: Dict, 
                       analysis: Dict, code: str) -> AnalysisResult:
        """格式化最終輸出"""
        # 組合自然語言回答
        answer_parts = []
        
        # 直接回答
        if analysis.get("direct_answer"):
            answer_parts.append(analysis["direct_answer"])
        
        # 數據摘要
        if summary:
            answer_parts.append("\n\n📊 **數據摘要**")
            for k, v in summary.items():
                if k not in ('columns',):  # 跳過技術欄位
                    answer_parts.append(f"- {k}: {v}")
        
        # 洞察
        if analysis.get("insights"):
            answer_parts.append("\n\n💡 **關鍵洞察**")
            for i, insight in enumerate(analysis["insights"], 1):
                answer_parts.append(f"{i}. {insight}")
        
        # 趨勢
        if analysis.get("trends"):
            answer_parts.append("\n\n📈 **趨勢分析**")
            for trend in analysis["trends"]:
                answer_parts.append(f"- {trend}")
        
        # 異常
        if analysis.get("anomalies"):
            answer_parts.append("\n\n⚠️ **值得注意**")
            for anomaly in analysis["anomalies"]:
                answer_parts.append(f"- {anomaly}")
        
        # 建議
        if analysis.get("recommendations"):
            answer_parts.append("\n\n✅ **建議行動**")
            for rec in analysis["recommendations"]:
                answer_parts.append(f"- {rec}")
        
        # 數據表格（如果有）
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
                "timestamp": datetime.now().isoformat(),
            }
        )
    
    def _df_to_markdown(self, df: pd.DataFrame, max_rows: int = 30) -> str:
        """將 DataFrame 轉為 Markdown 表格"""
        if df.empty:
            return ""
        
        df_show = df.head(max_rows)
        cols = list(df_show.columns)
        
        # 表頭
        header = "| " + " | ".join(str(c) for c in cols) + " |"
        sep = "|" + "|".join(["---"] * len(cols)) + "|"
        
        # 內容
        rows = []
        for _, r in df_show.iterrows():
            row_vals = []
            for c in cols:
                val = str(r.get(c, ""))[:60]  # 截斷過長
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
                "insights": [...],
                "recommendations": [...],
                "visualizations": [...],
                "metadata": {...}
            }
        """
        if not query or not query.strip():
            return {
                "answer": "請輸入有效的查詢。",
                "success": False,
            }
        
        if self.df is None or self.df.empty:
            return {
                "answer": "業務數據未載入。請確認 CSV 檔案是否存在。",
                "success": False,
            }
        
        try:
            # Step 1: AI 解析意圖
            logger.info(f"🔍 解析查詢意圖: {query[:50]}...")
            intent = self._parse_intent(query)
            logger.debug(f"意圖: {json.dumps(intent, ensure_ascii=False)}")
            
            # Step 2: AI 生成代碼
            logger.info("🔧 生成查詢代碼...")
            code = self._generate_code(query, intent)
            logger.debug(f"生成代碼:\n{code}")
            
            if not code:
                return {
                    "answer": "無法生成查詢代碼。請嘗試換個方式描述您的問題。",
                    "success": False,
                }
            
            # Step 3: 執行代碼
            logger.info("⚡ 執行查詢...")
            result, summary, error = self._execute_code(code)
            
            if error:
                # 代碼執行失敗，嘗試簡單的 fallback 查詢
                logger.warning(f"代碼執行失敗，嘗試 fallback 查詢: {error}")
                result, summary, fallback_error = self._fallback_query(query, intent)
                
                if fallback_error or result is None:
                    return {
                        "answer": f"查詢執行時發生錯誤。\n\n技術細節：{error[:500]}",
                        "success": False,
                        "code": code,
                    }
                logger.info("✅ Fallback 查詢成功")
            
            if result is None or (isinstance(result, (pd.DataFrame, pd.Series)) and len(result) == 0):
                return {
                    "answer": "查詢完成，但未找到符合條件的數據。請嘗試調整查詢條件。",
                    "success": True,
                    "data_summary": summary,
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
                "insights": output.insights,
                "recommendations": output.recommendations,
                "visualizations": output.visualizations,
                "metadata": output.metadata,
            }
            
        except Exception as e:
            logger.error(f"查詢失敗: {e}\n{traceback.format_exc()}")
            return {
                "answer": f"查詢過程發生錯誤：{str(e)}",
                "success": False,
            }
    
    def get_schema_info(self) -> Dict:
        """獲取數據 schema 信息（供前端使用）"""
        if self.df is None:
            return {"loaded": False}
        
        return {
            "loaded": True,
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
            "sample_activity_types": self.df['Class'].value_counts().head(10).to_dict() if 'Class' in self.df.columns else {},
        }
    
    def get_quick_stats(self) -> Dict:
        """獲取快速統計（儀表板用）"""
        if self.df is None:
            return {}
        
        today = datetime.now().date()
        last_30_days = today - timedelta(days=30)
        
        recent = self.df[self.df['_Date'].dt.date >= last_30_days] if '_Date' in self.df.columns else self.df
        
        return {
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
    
    Args:
        query: 自然語言查詢
    
    Returns:
        格式化的回答字串
    """
    engine = get_business_ai_engine()
    result = engine.query(query)
    return result.get("answer", "查詢失敗")


# ═══════════════════════════════════════════════════════════════
# CLI 測試
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
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
