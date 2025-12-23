# tech_doc_optimizer.py - 技術文檔 RAG 優化模組
"""
針對三信機械技術文檔的專門優化：
1. 智慧型號提取
2. 產品規格結構化
3. 多層次檢索策略
4. 文檔預處理與清洗
"""

import os
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from langchain_core.documents import Document

# ─────────────────────────────────────────────────────────────
# 產品型號模式定義
# ─────────────────────────────────────────────────────────────

# SMC 產品型號模式
SMC_PATTERNS = [
    r'(?:^|\s)(MXJ\d+[A-Z]*[-\d]*)',           # MXJ 系列
    r'(?:^|\s)(MXH\d+[A-Z]*[-\d]*)',           # MXH 系列
    r'(?:^|\s)(MXP\d+[A-Z]*[-\d]*)',           # MXP 系列
    r'(?:^|\s)(LES[A-Z]*\d*[-\d]*)',           # LES 系列
    r'(?:^|\s)(LEHZ[A-Z]*\d*[-\d]*)',          # LEHZ 系列
    r'(?:^|\s)(LEHF\d+[A-Z]*[-\d]*)',          # LEHF 系列
    r'(?:^|\s)(ACG[A-Z]*\d*[-\d]*)',           # ACG 系列
    r'(?:^|\s)(ARG[A-Z]*\d*[-\d]*)',           # ARG 系列
    r'(?:^|\s)(AWG[A-Z]*\d*[-\d]*)',           # AWG 系列
]

# VALQUA (華爾卡) 產品型號模式
VALQUA_PATTERNS = [
    r'(?:バルカー\s*)?No\.\s*(\d{4}[A-Z]*)',   # No.6500, No.7010 等
    r'(?:バルカー\s*)?No\.\s*([A-Z]+\d+)',     # No.GF300, No.SF300 等
    r'(?:バルカー\s*)?No\.\s*(N\d{4})',         # No.N7030 等
    r'(?:バルカー\s*)?No\.\s*(\d+[A-Z]*\d*)',  # 通用型號
]

# 玖基/協鋼產品型號
SEAL_PATTERNS = [
    r'(?:^|\s)(G[Ff][Oo][-\s]?\d+[A-Z]*)',     # GFO 系列
    r'(?:^|\s)(Gf[il][-\s]?\d*[A-Z]*)',        # Gfil 系列
    r'(?:^|\s)(Uf[il][-\s]?\d*[A-Z]*)',        # Ufil 系列
]

# ─────────────────────────────────────────────────────────────
# 資料結構
# ─────────────────────────────────────────────────────────────

@dataclass
class ProductInfo:
    """產品資訊結構"""
    model: str                    # 型號
    brand: str                    # 品牌
    category: str                 # 類別
    specs: Dict[str, str]         # 規格
    description: str              # 描述
    source_file: str              # 來源檔案

@dataclass
class TechChunk:
    """技術文檔 chunk 結構"""
    content: str
    chunk_type: str               # 'spec_table', 'description', 'installation', 'dimension'
    products: List[str]           # 相關產品型號
    metadata: Dict

# ─────────────────────────────────────────────────────────────
# 文檔清洗
# ─────────────────────────────────────────────────────────────

def clean_markdown_content(content: str) -> str:
    """清洗 Markdown 內容，移除雜訊"""
    
    # 移除圖片標籤（保留圖片路徑用於參考）
    content = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/>', r'[圖片: \1]', content)
    
    # 移除空的 blockquote
    content = re.sub(r'>\s*\n', '\n', content)
    
    # 移除過多的空行
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    # 標準化空白字元
    content = re.sub(r'[ \t]+', ' ', content)
    
    # 移除頁碼等雜訊
    content = re.sub(r'^\d+\s*$', '', content, flags=re.MULTILINE)
    
    return content.strip()


def extract_tables(content: str) -> List[Dict]:
    """提取 HTML 表格並轉為結構化資料"""
    tables = []
    
    # 匹配 HTML 表格
    table_pattern = r'<table[^>]*>(.*?)</table>'
    matches = re.findall(table_pattern, content, re.DOTALL | re.IGNORECASE)
    
    for i, table_html in enumerate(matches):
        # 提取表頭
        headers = re.findall(r'<th[^>]*>(.*?)</th>', table_html, re.DOTALL | re.IGNORECASE)
        headers = [re.sub(r'<[^>]+>', '', h).strip() for h in headers]
        
        # 提取表格行
        rows = []
        row_pattern = r'<tr[^>]*>(.*?)</tr>'
        row_matches = re.findall(row_pattern, table_html, re.DOTALL | re.IGNORECASE)
        
        for row_html in row_matches:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if cells:
                rows.append(cells)
        
        if headers or rows:
            tables.append({
                'index': i,
                'headers': headers,
                'rows': rows
            })
    
    return tables

# ─────────────────────────────────────────────────────────────
# 產品型號提取
# ─────────────────────────────────────────────────────────────

def extract_product_models(content: str) -> Dict[str, List[str]]:
    """從內容中提取所有產品型號，按品牌分類"""
    
    results = {
        'smc': [],
        'valqua': [],
        'seal': [],
        'other': []
    }
    
    # SMC 產品
    for pattern in SMC_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        results['smc'].extend(matches)
    
    # VALQUA 產品
    for pattern in VALQUA_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        results['valqua'].extend([f"No.{m}" for m in matches])
    
    # 油封/墊片產品
    for pattern in SEAL_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        results['seal'].extend(matches)
    
    # 去重
    for key in results:
        results[key] = list(set(results[key]))
    
    return results


def identify_product_series(model: str) -> Tuple[str, str]:
    """識別產品系列和品牌"""
    
    model_upper = model.upper()
    
    # SMC 系列
    if model_upper.startswith('MXJ'):
        return 'SMC', '滑動氣缸'
    if model_upper.startswith('MXH'):
        return 'SMC', '精密滑動氣缸'
    if model_upper.startswith('MXP'):
        return 'SMC', '迴轉氣缸'
    if model_upper.startswith('LES'):
        return 'SMC', '電動滑軌缸'
    if model_upper.startswith('LEH'):
        return 'SMC', '電動致動器'
    if model_upper.startswith(('ACG', 'ARG', 'AWG')):
        return 'SMC', '濾清器/調壓閥'
    
    # VALQUA
    if 'NO.' in model_upper or model_upper.startswith('N'):
        return 'VALQUA', '墊片/填料'
    
    # 玖基/協鋼
    if model_upper.startswith('GF'):
        return '玖基', '油封'
    if model_upper.startswith('UF'):
        return '協鋼', '密封件'
    
    return 'Unknown', 'Unknown'

# ─────────────────────────────────────────────────────────────
# 智慧 Chunking
# ─────────────────────────────────────────────────────────────

def smart_chunk_technical_doc(content: str, source: str, max_chunk_size: int = 1000) -> List[Document]:
    """
    智慧分割技術文檔
    
    策略：
    1. 優先按產品型號分割
    2. 保持規格表完整
    3. 保留上下文關聯
    """
    
    documents = []
    
    # 清洗內容
    cleaned = clean_markdown_content(content)
    
    # 提取產品型號
    products = extract_product_models(cleaned)
    all_products = []
    for brand_products in products.values():
        all_products.extend(brand_products)
    
    # 按章節分割
    sections = re.split(r'\n(?=#{1,4}\s)', cleaned)
    
    for section in sections:
        if not section.strip():
            continue
        
        # 判斷 chunk 類型
        chunk_type = classify_chunk_type(section)
        
        # 提取該區塊的產品型號
        section_products = extract_product_models(section)
        section_all_products = []
        for bp in section_products.values():
            section_all_products.extend(bp)
        
        # 如果區塊太大，進一步分割
        if len(section) > max_chunk_size:
            sub_chunks = split_large_section(section, max_chunk_size)
            for sub in sub_chunks:
                doc = Document(
                    page_content=sub,
                    metadata={
                        'source': source,
                        'chunk_type': chunk_type,
                        'products': ','.join(section_all_products) if section_all_products else '',
                        'doc_type': 'technical',
                        'all_products': ','.join(all_products) if all_products else '',
                    }
                )
                documents.append(doc)
        else:
            doc = Document(
                page_content=section,
                metadata={
                    'source': source,
                    'chunk_type': chunk_type,
                    'products': ','.join(section_all_products) if section_all_products else '',
                    'doc_type': 'technical',
                    'all_products': ','.join(all_products) if all_products else '',
                }
            )
            documents.append(doc)
    
    return documents


def classify_chunk_type(content: str) -> str:
    """分類 chunk 類型"""
    
    content_lower = content.lower()
    
    # 規格表
    if '<table' in content_lower or '規格' in content or '仕様' in content:
        return 'spec_table'
    
    # 尺寸圖
    if '寸法' in content or '尺寸' in content or 'dimension' in content_lower:
        return 'dimension'
    
    # 安裝說明
    if '安裝' in content or '取付' in content or '設置' in content or 'install' in content_lower:
        return 'installation'
    
    # 注意事項
    if '注意' in content or '警告' in content or '禁止' in content:
        return 'caution'
    
    # 產品特點
    if '特長' in content or '特點' in content or '特徴' in content:
        return 'features'
    
    return 'general'


def split_large_section(section: str, max_size: int) -> List[str]:
    """分割過大的區塊"""
    
    chunks = []
    
    # 優先按段落分割
    paragraphs = section.split('\n\n')
    
    current_chunk = ""
    for para in paragraphs:
        if len(current_chunk) + len(para) < max_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

# ─────────────────────────────────────────────────────────────
# 查詢優化
# ─────────────────────────────────────────────────────────────

def expand_technical_query(query: str) -> str:
    """
    擴展技術查詢
    
    - 補充品牌名稱
    - 補充同義詞
    - 補充相關型號
    """
    
    expanded = query
    
    # 型號擴展
    products = extract_product_models(query)
    
    for model in products.get('smc', []):
        brand, category = identify_product_series(model)
        expanded += f" {brand} {category}"
    
    for model in products.get('valqua', []):
        expanded += f" VALQUA 華爾卡 墊片 バルカー"
    
    # 關鍵字同義詞
    synonyms = {
        '規格': '仕様 spec specification',
        '尺寸': '寸法 dimension size',
        '安裝': '取付 設置 install mounting',
        '材質': '材料 material',
        '壓力': '圧力 pressure',
        '溫度': '温度 temperature',
        '耐熱': '耐熱性 heat resistant',
        '墊片': 'gasket ガスケット',
        '油封': 'seal シール',
    }
    
    for key, syns in synonyms.items():
        if key in query:
            expanded += f" {syns}"
    
    return expanded


def build_product_filter(query: str) -> Optional[Dict]:
    """
    建立產品型號過濾條件
    
    用於 ChromaDB where 條件
    """
    
    products = extract_product_models(query)
    all_products = []
    for bp in products.values():
        all_products.extend(bp)
    
    if not all_products:
        return None
    
    # 建立 OR 條件
    if len(all_products) == 1:
        return {"products": {"$contains": all_products[0]}}
    
    return {
        "$or": [{"products": {"$contains": p}} for p in all_products]
    }

# ─────────────────────────────────────────────────────────────
# 結果後處理
# ─────────────────────────────────────────────────────────────

def rerank_technical_results(query: str, docs: List[Document]) -> List[Document]:
    """
    重新排序技術文檔檢索結果
    
    策略：
    1. 型號完全匹配優先
    2. 規格表優先
    3. chunk_type 匹配優先
    """
    
    # 提取查詢中的產品型號
    query_products = extract_product_models(query)
    query_all = []
    for bp in query_products.values():
        query_all.extend(bp)
    
    # 判斷查詢類型
    query_type = None
    if '規格' in query or '仕様' in query:
        query_type = 'spec_table'
    elif '安裝' in query or '取付' in query:
        query_type = 'installation'
    elif '尺寸' in query or '寸法' in query:
        query_type = 'dimension'
    
    def score_doc(doc: Document) -> float:
        score = 0.0
        
        # 產品型號匹配
        doc_products = doc.metadata.get('products', '')
        for qp in query_all:
            if qp.lower() in doc_products.lower():
                score += 10.0
        
        # chunk_type 匹配
        if query_type and doc.metadata.get('chunk_type') == query_type:
            score += 5.0
        
        # 規格表額外加分
        if doc.metadata.get('chunk_type') == 'spec_table':
            score += 2.0
        
        return score
    
    # 排序
    scored_docs = [(doc, score_doc(doc)) for doc in docs]
    scored_docs.sort(key=lambda x: x[1], reverse=True)
    
    return [doc for doc, _ in scored_docs]

# ─────────────────────────────────────────────────────────────
# 測試函數
# ─────────────────────────────────────────────────────────────

def test_extraction():
    """測試型號提取"""
    
    test_cases = [
        "MXJ4 氣缸規格是什麼",
        "バルカー No.6500 墊片的耐熱溫度",
        "LEHF32 電動致動器安裝方式",
        "GF300 和 GFO 的差別",
        "No.7010 ふっ素樹脂シートガスケット",
    ]
    
    for query in test_cases:
        products = extract_product_models(query)
        print(f"查詢: {query}")
        print(f"  提取結果: {products}")
        print()


if __name__ == "__main__":
    test_extraction()
