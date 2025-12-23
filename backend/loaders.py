# loaders.py - 文件載入器模組
"""
各種文件格式的載入器：Markdown、CSV、業務報告、圖片
"""

import os
import re
from typing import List, Dict, Optional
from pathlib import Path

from langchain_community.document_loaders.base import BaseLoader
from langchain_core.documents import Document

from utils import DocumentType, _nfkc

# ─────────────────────────────────────────────────────────────
# 依賴檢查
# ─────────────────────────────────────────────────────────────

try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

# ─────────────────────────────────────────────────────────────
# CSV 業務資料處理器
# ─────────────────────────────────────────────────────────────

class CSVBusinessProcessor:
    """從 CSV 檔案載入業務資料"""
    
    @staticmethod
    def load_business_csv(csv_file: str) -> List[Document]:
        """載入 CSV 業務資料為 Document 列表"""
        if not _HAS_PANDAS:
            return []
        
        if not os.path.exists(csv_file):
            return []
        
        try:
            df = pd.read_csv(csv_file, encoding='utf-8')
            
            # 🔧 改進：過濾空行和無效資料
            original_len = len(df)
            df = df.dropna(how='all')  # 移除全空行
            df = df[df['Date'].notna()]  # 確保有日期
            df = df[df['Date'].astype(str).str.strip() != '']  # 日期不為空字串
            
            if original_len != len(df):
                print(f"   🧹 過濾無效資料：{original_len:,} → {len(df):,} 筆")
            
            required_columns = ['Date', 'Worker', 'Customer', 'Content']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                print(f"❌ CSV 缺少必要欄位：{missing_columns}")
                return []
            
            df = df.dropna(subset=required_columns)
            documents = []
            
            for idx, row in df.iterrows():
                content = CSVBusinessProcessor._build_content_from_row(row, idx + 1)
                
                if not content.strip():
                    continue
                
                metadata = {
                    'doc_type': DocumentType.BUSINESS.value,
                    'source': 'business_csv',
                    'record_id': idx + 1,
                    'date': str(row.get('Date', '')),
                    'worker': str(row.get('Worker', '')),
                    'customer': str(row.get('Customer', '')),
                    'class': str(row.get('Class', '')),
                    'depart': str(row.get('Depart', '')),
                    'manager': str(row.get('Manager', '')),
                }
                
                doc = Document(page_content=content, metadata=metadata)
                documents.append(doc)
                
                if (idx + 1) % 10000 == 0:
                    print(f"   📊 已處理 {idx + 1:,} / {len(df):,} 筆記錄...")
            
            return documents
            
        except Exception as e:
            print(f"CSV 載入失敗：{e}")
            return []
    
    @staticmethod
    def _build_content_from_row(row, record_num: int) -> str:
        """從 DataFrame 行建構文檔內容"""
        parts = [f"**記錄編號**: {record_num}"]
        
        field_map = {
            'Date': '日期',
            'Worker': '業務人員',
            'Customer': '客戶',
            'Class': '活動類型',
            'Content': '活動內容',
            'Depart': '部門',
            'Manager': '主管',
        }
        
        for en_name, zh_name in field_map.items():
            val = row.get(en_name, '')
            if pd.notna(val) and str(val).strip():
                parts.append(f"**{zh_name}**: {str(val).strip()}")
        
        return "\n".join(parts)

# ─────────────────────────────────────────────────────────────
# 業務報告處理器
# ─────────────────────────────────────────────────────────────

class BusinessReportProcessor:
    """處理業務日報格式的文件"""
    
    FIELD_MAPPING = {
        'Doc_Time:': '日期',
        'TimeCreated:': '建立時間',
        'Customer:': '客戶',
        'Worker:': '業務人員',
        'Content:': '活動內容',
        'Manager:': '主管',
        'Depart:': '部門',
        'Doc_St:': '狀態',
        'Class:': '活動類型',
    }
    
    @staticmethod
    def parse_report(text: str) -> List[Dict]:
        """解析業務日報文本"""
        records = []
        
        # 嘗試用 Doc_Time: 分割
        if 'Doc_Time:' in text:
            parts = re.split(r'(?=Doc_Time:)', text)
            parts = [p.strip() for p in parts if p.strip() and 'Doc_Time:' in p]
            
            for part in parts:
                record = BusinessReportProcessor._parse_single_record(part)
                if record and record.get('customer'):
                    records.append(record)
        
        return records
    
    @staticmethod
    def _parse_single_record(text: str) -> Dict:
        """解析單筆業務記錄"""
        record = {}
        
        for en_key, zh_key in BusinessReportProcessor.FIELD_MAPPING.items():
            pattern = rf'{re.escape(en_key)}\s*(.+?)(?=\n[A-Za-z_]+:|$)'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                value = match.group(1).strip()
                value = re.sub(r'\s+', ' ', value)
                
                field_name = en_key.replace(':', '').lower()
                if field_name == 'doc_time':
                    field_name = 'date'
                elif field_name == 'worker':
                    field_name = 'worker'
                elif field_name == 'customer':
                    field_name = 'customer'
                
                record[field_name] = value
        
        return record

# ─────────────────────────────────────────────────────────────
# 圖片處理器
# ─────────────────────────────────────────────────────────────

class SimpleImageProcessor:
    """處理 Markdown 中的圖片引用"""
    
    def __init__(self, media_base_dir: str):
        self.media_base_dir = media_base_dir
    
    def process_images(self, text: str, source_file: str) -> tuple:
        """處理圖片引用，返回 (處理後文本, 圖片列表)"""
        images = []
        
        # 匹配 Markdown 圖片語法
        pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        
        def replace_image(match):
            alt_text = match.group(1)
            img_path = match.group(2)
            
            # 處理相對路徑
            if not img_path.startswith(('http://', 'https://', '/')):
                source_dir = os.path.dirname(source_file)
                full_path = os.path.normpath(os.path.join(source_dir, img_path))
                
                if os.path.exists(full_path):
                    images.append({
                        'path': full_path,
                        'alt': alt_text,
                        'original': img_path
                    })
            
            return f"[圖片: {alt_text or '無描述'}]"
        
        processed_text = re.sub(pattern, replace_image, text)
        return processed_text, images

# ─────────────────────────────────────────────────────────────
# 增強型 Markdown 載入器
# ─────────────────────────────────────────────────────────────

class EnhancedMarkdownLoader(BaseLoader):
    """增強型 Markdown 載入器，支援產品規格、圖片、表格"""
    
    # 完整的產品型號模式
    PRODUCT_PATTERNS = [
        # SMC 產品
        r'(?:^|\s)(MXJ\d+[A-Z]*)',              # MXJ 系列
        r'(?:^|\s)(MXH\d+[A-Z]*)',              # MXH 系列
        r'(?:^|\s)(MXP\d+[A-Z]*)',              # MXP 系列
        r'(?:^|\s)(LES[A-Z]*\d+)',              # LES 系列
        r'(?:^|\s)(LEHZ[A-Z]*\d*)',             # LEHZ 系列
        r'(?:^|\s)(LEHF\d+[A-Z]*)',             # LEHF 系列
        r'(?:^|\s)(ACG[A-Z]*\d*)',              # ACG 系列
        r'(?:^|\s)(ARG[A-Z]*\d*)',              # ARG 系列
        r'(?:^|\s)(AWG[A-Z]*\d*)',              # AWG 系列
        # VALQUA 產品
        r'(?:バルカー\s*)?No\.\s*(\d{4}[A-Z]*)',  # No.6500, No.7010
        r'(?:バルカー\s*)?No\.\s*([A-Z]+\d+)',    # No.GF300, No.SF300
        r'(?:バルカー\s*)?No\.\s*(N\d{4})',       # No.N7030
        # 玖基/協鋼產品
        r'(?:^|\s)(GF\d+[A-Z]*)',               # GF300
        r'(?:^|\s)(GFO[-\s]?\d*)',              # GFO
        r'(?:^|\s)(Gf[il]\d*[A-Z]*)',           # Gfil
        r'(?:^|\s)(Uf[il]\d*[A-Z]*)',           # Ufil
        # 通用型號
        r'(?:型號|製品番号)[:\s]*([A-Z0-9]+-?[A-Z0-9]+)',
    ]
    
    def __init__(self, file_path: str, **kwargs):
        self.file_path = file_path
        self.autodetect_encoding = kwargs.get('autodetect_encoding', True)
        self.media_base_dir = kwargs.get('media_base_dir', '')
    
    def load(self) -> List[Document]:
        """載入並處理 Markdown 文件"""
        text = self._read_file()
        if not text:
            return []
        
        # 檢查是否為業務報告
        if self._is_business_report(text):
            return self._process_as_business(text)
        
        # 處理為技術文檔
        return self._process_as_technical(text)
    
    def _read_file(self) -> str:
        """讀取檔案內容"""
        text = None
        encodings_to_try = ['utf-8', 'utf-8-sig', 'big5', 'gb18030', 'shift_jis']
        
        if self.autodetect_encoding:
            try:
                import chardet
                with open(self.file_path, "rb") as f:
                    raw_data = f.read()
                detected = chardet.detect(raw_data)
                if detected and detected['encoding']:
                    encodings_to_try.insert(0, detected['encoding'])
            except Exception:
                pass
        
        for encoding in encodings_to_try:
            try:
                with open(self.file_path, "r", encoding=encoding) as f:
                    text = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        if text is None:
            try:
                with open(self.file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception:
                return ""
        
        return _nfkc(text) if text else ""
    
    def _is_business_report(self, text: str) -> bool:
        """檢查是否為業務日報格式"""
        indicators = ['Doc_Time:', 'TimeCreated:', 'Customer:', 'Worker:', 
                      'Content:', 'Manager:', 'Depart:', 'Doc_St:']
        count = sum(1 for ind in indicators if ind in text)
        return count >= 3
    
    def _process_as_business(self, text: str) -> List[Document]:
        """處理業務報告"""
        records = BusinessReportProcessor.parse_report(text)
        documents = []
        
        for i, record in enumerate(records):
            content = self._format_business_record(record, i + 1)
            
            metadata = {
                'source': self.file_path,
                'doc_type': DocumentType.BUSINESS.value,
                'record_index': i + 1,
                'date': record.get('date', ''),
                'worker': record.get('worker', ''),
                'customer': record.get('customer', ''),
            }
            
            documents.append(Document(page_content=content, metadata=metadata))
        
        return documents
    
    def _format_business_record(self, record: Dict, index: int) -> str:
        """格式化業務記錄"""
        parts = [f"**記錄 {index}**"]
        
        field_map = {
            'date': '日期',
            'worker': '業務人員',
            'customer': '客戶',
            'class': '活動類型',
            'content': '活動內容',
            'depart': '部門',
        }
        
        for key, label in field_map.items():
            if record.get(key):
                parts.append(f"**{label}**: {record[key]}")
        
        return "\n".join(parts)
    
    def _process_as_technical(self, text: str) -> List[Document]:
        """處理技術文檔"""
        # 提取產品代碼
        product_codes = self._extract_product_codes(text)
        
        # 識別主要品牌
        brand = self._identify_brand(text, product_codes)
        
        # 識別文檔類型
        doc_category = self._identify_doc_category(text)
        
        # 處理圖片
        images_count = len(re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', text))
        
        # 清洗內容
        cleaned_text = self._clean_technical_content(text)
        
        # 處理表格
        cleaned_text = self._process_tables(cleaned_text)
        
        # ChromaDB 只接受 str/int/float/bool，將 list 轉為逗號分隔字串
        metadata = {
            'source': self.file_path,
            'doc_type': DocumentType.TECHNICAL.value,
            'product_codes': ','.join(product_codes) if product_codes else '',
            'brand': brand,
            'doc_category': doc_category,
            'images_count': images_count,
            'file_name': os.path.basename(self.file_path),
        }
        
        return [Document(page_content=cleaned_text, metadata=metadata)]
    
    def _identify_brand(self, text: str, product_codes: List[str]) -> str:
        """識別主要品牌"""
        text_lower = text.lower()
        
        # 優先根據產品代碼判斷
        for code in product_codes:
            code_upper = code.upper()
            if code_upper.startswith(('MXJ', 'MXH', 'MXP', 'LES', 'LEH', 'ACG', 'ARG', 'AWG')):
                return 'SMC'
            if 'NO.' in code_upper or code_upper.startswith('N'):
                return 'VALQUA'
            if code_upper.startswith('GF'):
                return '玖基'
            if code_upper.startswith('UF'):
                return '協鋼'
        
        # 根據內容判斷
        if 'smc' in text_lower or '速睦喜' in text:
            return 'SMC'
        if 'valqua' in text_lower or 'バルカー' in text or '華爾卡' in text:
            return 'VALQUA'
        if '玖基' in text:
            return '玖基'
        if '協鋼' in text:
            return '協鋼'
        
        return 'Unknown'
    
    def _identify_doc_category(self, text: str) -> str:
        """識別文檔類別"""
        if '規格' in text or '仕様' in text or 'specification' in text.lower():
            return 'specification'
        if '取付' in text or '安裝' in text or 'install' in text.lower():
            return 'installation'
        if '寸法' in text or '尺寸' in text or 'dimension' in text.lower():
            return 'dimension'
        if 'カタログ' in text or '型錄' in text or 'catalog' in text.lower():
            return 'catalog'
        return 'general'
    
    def _clean_technical_content(self, text: str) -> str:
        """清洗技術文檔內容"""
        # 移除圖片 HTML 標籤但保留描述
        text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/>', r'[圖: \1]', text)
        
        # 移除空的 blockquote
        text = re.sub(r'>\s*\n', '\n', text)
        
        # 移除過多空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 移除頁碼
        text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)
        
        return text.strip()
    
    def _extract_product_codes(self, text: str) -> List[str]:
        """提取產品代碼"""
        codes = set()
        for pattern in self.PRODUCT_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                if isinstance(m, tuple):
                    codes.update(c for c in m if c)
                else:
                    codes.add(m)
        return list(codes)[:20]
    
    def _process_tables(self, text: str) -> str:
        """處理 HTML 表格轉為 Markdown"""
        # 簡化處理：移除 HTML 標籤
        text = re.sub(r'</?table[^>]*>', '', text)
        text = re.sub(r'</?tr[^>]*>', '\n', text)
        text = re.sub(r'</?t[hd][^>]*>', ' | ', text)
        text = re.sub(r'</?tbody[^>]*>', '', text)
        text = re.sub(r'</?thead[^>]*>', '', text)
        return text
