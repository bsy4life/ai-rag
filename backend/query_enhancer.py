# query_enhancer.py - AI 驅動的查詢增強器
"""
功能：
1. 多語言術語翻譯（中↔日↔英）
2. 同義詞擴展
3. 產品型號識別與精確匹配
4. 意圖理解與查詢改寫
5. 生成多個搜索查詢提高召回率

使用：
    from query_enhancer import QueryEnhancer
    enhancer = QueryEnhancer()
    enhanced = enhancer.enhance(query)
    # enhanced.queries = ["墊片 ガスケット gasket", "耐熱 高温用", ...]
"""

import os
import re
import json
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 術語詞典（靜態，快速查找）
# ═══════════════════════════════════════════════════════════════

TERM_DICTIONARY = {
    # 產品類型
    "墊片": ["ガスケット", "gasket", "パッキン", "packing", "シートガスケット"],
    "密封墊": ["シール", "seal", "ガスケット", "gasket"],
    "軟質墊片": ["ソフトガスケット", "soft gasket", "ジョイントシート"],
    "金屬墊片": ["メタルガスケット", "metal gasket", "金属ガスケット"],
    "渦卷墊片": ["うず巻形ガスケット", "spiral wound gasket", "スパイラルガスケット"],
    "油封": ["オイルシール", "oil seal", "シール"],
    "O環": ["Oリング", "O-ring", "オーリング"],
    "填料": ["パッキン", "packing", "グランドパッキン"],
    "氣缸": ["シリンダ", "cylinder", "エアシリンダ", "air cylinder"],
    "電磁閥": ["ソレノイドバルブ", "solenoid valve", "電磁弁"],
    "調壓閥": ["レギュレータ", "regulator", "減圧弁", "pressure regulator"],
    "過濾器": ["フィルタ", "filter", "濾過器"],
    "接頭": ["継手", "fitting", "connector", "カップリング"],
    "消音器": ["サイレンサ", "silencer", "muffler"],
    "真空吸盤": ["真空パッド", "vacuum pad", "吸着パッド", "サクションカップ"],
    "真空產生器": ["真空エジェクタ", "vacuum ejector", "バキュームジェネレータ"],
    "壓力開關": ["圧力スイッチ", "pressure switch"],
    "流量開關": ["フロースイッチ", "flow switch"],
    "電動致動器": ["電動アクチュエータ", "electric actuator"],
    
    # VALQUA 產品系列
    "6500": ["ジョイントシートガスケット", "joint sheet", "No.6500"],
    "7010": ["バルフロンシート", "PTFE sheet", "ふっ素樹脂シート"],
    "7020": ["バルフロンシート", "PTFE gasket", "ふっ素樹脂ガスケット"],
    
    # 材質
    "不鏽鋼": ["ステンレス", "stainless steel", "SUS"],
    "鋁": ["アルミ", "aluminum", "aluminium"],
    "黃銅": ["真鍮", "brass"],
    "氟素樹脂": ["ふっ素樹脂", "PTFE", "テフロン", "fluororesin", "フッ素"],
    "橡膠": ["ゴム", "rubber"],
    "NBR": ["ニトリルゴム", "nitrile rubber", "丁腈橡膠"],
    "EPDM": ["エチレンプロピレンゴム", "ethylene propylene"],
    "矽膠": ["シリコーン", "silicone"],
    "石墨": ["グラファイト", "graphite", "膨張黒鉛"],
    
    # 特性
    "耐熱": ["耐熱性", "高温用", "heat resistant", "high temperature", "高温"],
    "耐壓": ["耐圧", "pressure resistant", "高圧用", "高圧"],
    "耐腐蝕": ["耐食", "耐蝕", "corrosion resistant", "防蝕", "耐薬品"],
    "耐油": ["耐油性", "oil resistant"],
    "真空": ["バキューム", "vacuum", "真空用"],
    "防爆": ["防爆形", "explosion proof", "耐圧防爆"],
    "食品級": ["食品用", "food grade", "食品衛生法適合"],
    "無塵": ["クリーン", "clean", "クリーンルーム用", "低発塵"],
    
    # 動作/操作
    "安裝": ["取付", "取り付け", "installation", "mounting", "設置", "組付"],
    "拆卸": ["取り外し", "removal", "分解"],
    "調整": ["調節", "adjustment", "セッティング"],
    "維修": ["修理", "メンテナンス", "maintenance", "保守"],
    "故障": ["トラブル", "trouble", "故障", "異常"],
    "漏氣": ["エアリーク", "air leak", "漏れ"],
    "漏油": ["オイルリーク", "oil leak", "油漏れ"],
    "選型": ["選定", "selection", "型式選定"],
    
    # 規格/尺寸
    "規格": ["仕様", "specification", "spec", "スペック"],
    "尺寸": ["寸法", "dimension", "サイズ", "size"],
    "口徑": ["口径", "bore size", "呼び径"],
    "行程": ["ストローク", "stroke"],
    "壓力": ["圧力", "pressure"],
    "溫度": ["温度", "temperature"],
    "流量": ["流量", "flow rate"],
}

# 品牌別名
BRAND_ALIASES = {
    "SMC": ["smc", "エスエムシー"],
    "VALQUA": ["valqua", "バルカー", "華爾卡", "valker"],
    "玖基": ["jiuji", "久基", "GF"],
    "協鋼": ["xiegang", "協鋼油封"],
    "油研": ["YUKEN", "yuken", "ユケン"],
    "CKD": ["ckd", "シーケーディ"],
    "FESTO": ["festo", "フェスト"],
    "NOK": ["nok", "エヌオーケー"],
}

# 產品型號正則
MODEL_PATTERNS = {
    "smc": [
        r'\b(?:MXJ|MXH|MXP|MXQ|MXS|MXW|MXF)[\d]+[A-Z]?[-\d\w]*\b',  # 氣缸
        r'\b(?:LES|LEH|LEJ|LEY|LEF|LEL)[\dA-Z][-\w]*\b',  # 電動致動器
        r'\b(?:SY|SV|SQ|VQ|VQZ|VF|VFS)[\d]+[-\w]*\b',  # 電磁閥
        r'\b(?:ACG|ARG|AWG|AFM|AFF|AF)[\d]*[-\w]*\b',  # 空壓處理
        r'\b(?:ZSE|ZSP|ZSM|ISE|ISA)[\d]+[A-Z]*[-\w]*\b',  # 壓力開關
        r'\b(?:KQ|KQG|KQB|KQH|KJ|KJH)[\d]*[-\w]*\b',  # 接頭
        r'\b(?:CDQ|CQ|CDJ|CJ|C[A-Z]{1,2})[\d]+[-\w]*\b',  # 更多氣缸
    ],
    "valqua": [
        r'\b(?:No\.?\s*)?[67]\d{3}[A-Z]?\b',  # 6500, 7020 等
        r'\b(?:No\.?\s*)?\d{4}[-\w]*\b',  # 一般產品號
        r'\b(?:HRS|VG|VS)[-\d\w]*\b',  # 特殊系列
    ],
    "seal": [
        r'\bGF[-\s]?\d+[-\w]*\b',  # 玖基油封
        r'\b(?:TC|TB|SC|SA|TA)\s*\d+[xX×]\d+[xX×]\d+\b',  # 油封尺寸規格
    ],
}


# ═══════════════════════════════════════════════════════════════
# 數據類
# ═══════════════════════════════════════════════════════════════

@dataclass
class EnhancedQuery:
    """增強後的查詢結果"""
    original: str                           # 原始查詢
    intent: str = ""                        # 理解的意圖
    primary_query: str = ""                 # 主要搜索查詢
    expanded_queries: List[str] = field(default_factory=list)  # 展開的多個查詢
    extracted_models: List[str] = field(default_factory=list)  # 提取的產品型號
    detected_brand: str = ""                # 偵測到的品牌
    language_variants: Dict[str, str] = field(default_factory=dict)  # 多語言變體
    keywords: List[str] = field(default_factory=list)  # 提取的關鍵字
    
    def get_all_queries(self) -> List[str]:
        """獲取所有查詢（用於多次搜索）"""
        queries = [self.primary_query] if self.primary_query else [self.original]
        queries.extend(self.expanded_queries)
        # 加入產品型號作為獨立查詢（精確匹配）
        queries.extend(self.extracted_models)
        return list(dict.fromkeys(queries))  # 去重保序


# ═══════════════════════════════════════════════════════════════
# LLM 客戶端
# ═══════════════════════════════════════════════════════════════

class LLMClient:
    """簡易 LLM 客戶端"""
    
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
        
        # 處理 auto 模式
        if self.provider == "auto":
            primary = os.getenv("LLM_PRIMARY", "anthropic").strip().lower()
            self.provider = "anthropic" if primary in ("anthropic", "claude") else "openai"
        
        self._client = None
        self._init_client()
    
    def _init_client(self):
        if self.provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                self.model = os.getenv("ANTHROPIC_MODEL_SIMPLE", "claude-haiku-4-5-20251001")
                logger.debug(f"QueryEnhancer 使用 Anthropic: {self.model}")
            except ImportError:
                self._init_openai()
        else:
            self._init_openai()
    
    def _init_openai(self):
        if os.getenv("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                self.provider = "openai"
                self.model = os.getenv("OPENAI_MODEL_SIMPLE", "gpt-4o-mini")
                logger.debug(f"QueryEnhancer 使用 OpenAI: {self.model}")
            except ImportError:
                logger.warning("無法初始化 LLM 客戶端")
                self._client = None
    
    def chat(self, prompt: str, system: str = None) -> str:
        if not self._client:
            return ""
        
        try:
            if self.provider == "anthropic":
                kwargs = {
                    "model": self.model,
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if system:
                    kwargs["system"] = system
                response = self._client.messages.create(**kwargs)
                return response.content[0].text
            else:
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=1000,
                    temperature=0.1,
                )
                return response.choices[0].message.content
        except Exception as e:
            error_msg = str(e)
            # 限額錯誤時嘗試 fallback
            if "usage limits" in error_msg or "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                logger.warning(f"⚠️ QueryEnhancer {self.provider} 限額，嘗試 fallback")
                return self._fallback_chat(prompt, system)
            logger.error(f"LLM 調用失敗: {e}")
            return ""
    
    def _fallback_chat(self, prompt: str, system: str = None) -> str:
        """Fallback 到另一個提供商"""
        try:
            if self.provider == "anthropic" and os.getenv("OPENAI_API_KEY"):
                from openai import OpenAI
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                model = os.getenv("OPENAI_MODEL_SIMPLE", "gpt-4o-mini")
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})
                response = client.chat.completions.create(
                    model=model, messages=messages, max_tokens=1000, temperature=0.1,
                )
                logger.info(f"✅ QueryEnhancer fallback 到 OpenAI 成功")
                return response.choices[0].message.content
            elif self.provider == "openai" and os.getenv("ANTHROPIC_API_KEY"):
                from anthropic import Anthropic
                client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                model = os.getenv("ANTHROPIC_MODEL_SIMPLE", "claude-haiku-4-5-20251001")
                kwargs = {"model": model, "max_tokens": 1000, "messages": [{"role": "user", "content": prompt}]}
                if system:
                    kwargs["system"] = system
                response = client.messages.create(**kwargs)
                logger.info(f"✅ QueryEnhancer fallback 到 Anthropic 成功")
                return response.content[0].text
        except Exception as e:
            logger.error(f"❌ QueryEnhancer fallback 也失敗: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════
# 查詢增強器
# ═══════════════════════════════════════════════════════════════

class QueryEnhancer:
    """AI 驅動的查詢增強器"""
    
    def __init__(self, use_llm: bool = True):
        """
        Args:
            use_llm: 是否使用 LLM 進行深度理解（設為 False 則只用規則）
        """
        self.use_llm = use_llm
        self._llm = None
        if use_llm:
            try:
                self._llm = LLMClient()
            except Exception as e:
                logger.warning(f"LLM 初始化失敗，將只使用規則: {e}")
                self.use_llm = False
    
    def enhance(self, query: str) -> EnhancedQuery:
        """
        增強查詢
        
        Args:
            query: 原始用戶查詢
        
        Returns:
            EnhancedQuery 對象
        """
        result = EnhancedQuery(original=query)
        
        # 1. 提取產品型號（精確匹配最重要）
        result.extracted_models = self._extract_models(query)
        result.detected_brand = self._detect_brand(query)
        
        # 2. 規則式擴展（快速，無需 LLM）
        result.keywords = self._extract_keywords(query)
        result.language_variants = self._translate_terms(query)
        
        # 3. 構建主要查詢
        result.primary_query = self._build_primary_query(query, result)
        
        # 4. 使用 LLM 深度理解（可選）
        if self.use_llm and self._llm and self._llm._client:
            llm_enhanced = self._llm_enhance(query)
            if llm_enhanced:
                result.intent = llm_enhanced.get("intent", "")
                result.expanded_queries.extend(llm_enhanced.get("queries", []))
        
        # 5. 生成擴展查詢
        result.expanded_queries.extend(self._generate_expanded_queries(query, result))
        
        # 去重
        result.expanded_queries = list(dict.fromkeys(result.expanded_queries))
        
        logger.info(f"📝 查詢增強: '{query}' → {len(result.get_all_queries())} 個查詢變體")
        
        return result
    
    def _extract_models(self, query: str) -> List[str]:
        """提取產品型號"""
        models = []
        
        for brand, patterns in MODEL_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, query, re.IGNORECASE)
                for m in matches:
                    if isinstance(m, tuple):
                        m = m[0]
                    if m and len(m) >= 2:
                        models.append(m.upper())
        
        return list(set(models))
    
    def _detect_brand(self, query: str) -> str:
        """偵測品牌"""
        query_upper = query.upper()
        
        for brand, aliases in BRAND_ALIASES.items():
            if brand.upper() in query_upper:
                return brand
            for alias in aliases:
                if alias.upper() in query_upper:
                    return brand
        
        # 根據產品型號推斷
        for brand, patterns in MODEL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return brand.upper()
        
        return ""
    
    def _extract_keywords(self, query: str) -> List[str]:
        """提取關鍵字"""
        keywords = []
        
        for term in TERM_DICTIONARY.keys():
            if term in query:
                keywords.append(term)
        
        return keywords
    
    def _translate_terms(self, query: str) -> Dict[str, str]:
        """翻譯術語到多語言"""
        variants = {"original": query}
        
        ja_terms = []
        en_terms = []
        
        for zh_term, translations in TERM_DICTIONARY.items():
            if zh_term in query:
                # 第一個通常是日文，第二個是英文
                if translations:
                    ja_terms.append(translations[0])
                if len(translations) > 1:
                    en_terms.append(translations[1])
        
        if ja_terms:
            variants["japanese"] = " ".join(ja_terms)
        if en_terms:
            variants["english"] = " ".join(en_terms)
        
        return variants
    
    def _build_primary_query(self, query: str, result: EnhancedQuery) -> str:
        """構建主要搜索查詢"""
        parts = [query]
        
        # 加入品牌關鍵字
        if result.detected_brand:
            parts.append(result.detected_brand)
        
        # 加入多語言術語
        for lang, text in result.language_variants.items():
            if lang != "original" and text:
                parts.append(text)
        
        return " ".join(parts)
    
    def _llm_enhance(self, query: str) -> Optional[Dict]:
        """使用 LLM 進行深度查詢增強"""
        
        prompt = f"""分析以下工業產品查詢，理解用戶意圖並生成搜索查詢變體。

用戶查詢：{query}

請回答 JSON 格式：
{{
    "intent": "用戶想要找什麼（簡短描述）",
    "queries": [
        "搜索查詢1（加入日文術語）",
        "搜索查詢2（加入英文術語）",
        "搜索查詢3（同義詞變體）"
    ]
}}

注意：
- 這是工業設備產品目錄搜索
- 常見品牌：SMC（氣壓設備）、VALQUA/華爾卡（墊片）、玖基（油封）
- 要考慮中日英三語術語
- 只回答 JSON，不要有其他文字"""

        system = "你是一個工業產品搜索助手，專門幫助擴展搜索查詢以提高召回率。"
        
        try:
            response = self._llm.chat(prompt, system)
            
            # 清理 markdown
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)
            
            return json.loads(response)
        except Exception as e:
            logger.warning(f"LLM 增強失敗: {e}")
            return None
    
    def _generate_expanded_queries(self, query: str, result: EnhancedQuery) -> List[str]:
        """生成擴展查詢"""
        expanded = []
        
        # 基於關鍵字的擴展
        for keyword in result.keywords:
            if keyword in TERM_DICTIONARY:
                for trans in TERM_DICTIONARY[keyword][:2]:
                    # 替換原查詢中的關鍵字
                    expanded_q = query.replace(keyword, f"{keyword} {trans}")
                    if expanded_q != query:
                        expanded.append(expanded_q)
        
        # 品牌擴展
        if result.detected_brand:
            brand_aliases = BRAND_ALIASES.get(result.detected_brand, [])
            for alias in brand_aliases[:2]:
                expanded.append(f"{query} {alias}")
        
        # 日文版查詢（如果有翻譯）
        if result.language_variants.get("japanese"):
            expanded.append(result.language_variants["japanese"])
        
        return expanded


# ═══════════════════════════════════════════════════════════════
# 便捷函數
# ═══════════════════════════════════════════════════════════════

_enhancer_instance = None

def get_query_enhancer(use_llm: bool = True) -> QueryEnhancer:
    """獲取查詢增強器單例"""
    global _enhancer_instance
    if _enhancer_instance is None:
        _enhancer_instance = QueryEnhancer(use_llm=use_llm)
    return _enhancer_instance


def enhance_query(query: str, use_llm: bool = True) -> EnhancedQuery:
    """增強查詢的便捷函數"""
    return get_query_enhancer(use_llm).enhance(query)


# ═══════════════════════════════════════════════════════════════
# 測試
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    test_queries = [
        "有沒有耐高溫的墊片？",
        "SMC MXJ6-5 氣缸規格",
        "真空吸盤安裝方法",
        "VALQUA 7020 墊片材質",
        "油封漏油怎麼處理",
        "ZSE30A 壓力開關",
    ]
    
    enhancer = QueryEnhancer(use_llm=False)  # 先用規則測試
    
    for q in test_queries:
        print(f"\n{'='*50}")
        print(f"原始: {q}")
        result = enhancer.enhance(q)
        print(f"意圖: {result.intent}")
        print(f"型號: {result.extracted_models}")
        print(f"品牌: {result.detected_brand}")
        print(f"查詢變體:")
        for i, qv in enumerate(result.get_all_queries()[:5], 1):
            print(f"  {i}. {qv}")
