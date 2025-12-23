# business_csv.py - CSV 業務資料直接查詢模組
"""
直接從 CSV 檔案查詢業務資料，不經過向量庫
支援：時間範圍、營業所、業務員、客戶等條件過濾
"""

import os
import re
import datetime as _dt
from typing import Optional, Tuple, Dict, List

# ─────────────────────────────────────────────────────────────
# 依賴檢查
# ─────────────────────────────────────────────────────────────

try:
    import pandas as _pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

# ─────────────────────────────────────────────────────────────
# 常數
# ─────────────────────────────────────────────────────────────

BRANCH_SYNONYMS = {
    "台南營業所": ["台南所", "台南營所", "台南"],
    "台中營業所": ["台中所", "台中營所", "台中"],
    "高雄營業所": ["高雄所", "高雄營所", "高雄"],
    "台北營業所": ["台北所", "台北營所", "台北"],
}

# 常見客戶名稱對照（簡稱 → 可能的全名關鍵字）
# 這個會在查詢時動態擴展
CUSTOMER_KEYWORDS = [
    "精機", "機械", "科技", "工業", "企業", "公司", 
    "股份有限公司", "有限公司", "實業"
]

# ─────────────────────────────────────────────────────────────
# CSV 路徑偵測
# ─────────────────────────────────────────────────────────────

def _guess_business_csv() -> Optional[str]:
    """自動偵測 CSV 檔案位置"""
    candidates = [
        os.environ.get("BUSINESS_CSV_FILE"),
        "/app/data/business/clean_business.csv",
        "./data/business/clean_business.csv",
        "./business/clean_business.csv",
        "/mnt/data/business/clean_business.csv",
        "/mnt/user-data/uploads/clean_business.csv",  # 測試環境
        "clean_business.csv",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None

# ─────────────────────────────────────────────────────────────
# 客戶名稱解析
# ─────────────────────────────────────────────────────────────

def _extract_customer_name(query: str) -> Optional[str]:
    """
    從查詢中提取客戶名稱
    
    支援格式：
    - 「客戶XXX的活動」
    - 「XXX公司」「XXX精機」「XXX科技」
    - 「列出XXX的活動」
    """
    if not query:
        return None
    
    # 模式1：「客戶XXX」
    m = re.search(r'客戶[：:\s]*([^\s,，的]+)', query)
    if m:
        return m.group(1).strip()
    
    # 模式2：「XXX公司/精機/科技/工業...的」
    for suffix in CUSTOMER_KEYWORDS:
        m = re.search(rf'([^\s,，列出查詢]+{suffix})', query)
        if m:
            return m.group(1).strip()
    
    # 模式3：「列出/查詢 XXX 的活動」
    m = re.search(r'(?:列出|查詢|顯示|找出?)\s*([^\s,，的]{2,10})\s*的?\s*(?:活動|記錄|紀錄|日報|業務)', query)
    if m:
        candidate = m.group(1).strip()
        # 排除營業所和時間詞
        if not any(x in candidate for x in ['營業所', '最近', '本月', '上月', '年', '月']):
            return candidate
    
    return None


def _fuzzy_match_customer(df, customer_name: str) -> 'pd.Series':
    """
    模糊匹配客戶名稱
    
    策略（按結果數量選最佳）：
    1. 完全匹配原始名稱
    2. 去除後綴後完全匹配
    3. 去除後綴後包含匹配
    4. 原始名稱包含匹配
    """
    if 'Customer' not in df.columns:
        return _pd.Series([False] * len(df), index=df.index)
    
    customer_col = df['Customer'].astype(str).fillna('')
    
    # 清理搜尋詞（去除常見後綴）
    clean_name = customer_name
    for suffix in CUSTOMER_KEYWORDS:
        clean_name = clean_name.replace(suffix, '')
    clean_name = clean_name.strip()
    
    # 收集所有可能的匹配結果
    candidates = []
    
    # 策略1：完全匹配原始名稱
    mask1 = customer_col == customer_name
    if mask1.sum() > 0:
        candidates.append(('exact_original', mask1, mask1.sum()))
    
    # 策略2：去除後綴後完全匹配（如「東台精機」→「東台」）
    if clean_name and clean_name != customer_name and len(clean_name) >= 2:
        mask2 = customer_col == clean_name
        if mask2.sum() > 0:
            candidates.append(('exact_clean', mask2, mask2.sum()))
    
    # 策略3：去除後綴後包含匹配
    if clean_name and len(clean_name) >= 2:
        mask3 = customer_col.str.contains(clean_name, na=False, regex=False)
        if mask3.sum() > 0:
            candidates.append(('contains_clean', mask3, mask3.sum()))
    
    # 策略4：原始名稱包含匹配
    mask4 = customer_col.str.contains(customer_name, na=False, regex=False)
    if mask4.sum() > 0:
        candidates.append(('contains_original', mask4, mask4.sum()))
    
    # 選擇結果最多的匹配
    if candidates:
        # 按匹配數量排序，取最多的
        candidates.sort(key=lambda x: x[2], reverse=True)
        best_match = candidates[0]
        return best_match[1]
    
    # 策略5：搜尋詞被客戶欄位包含（最後手段）
    def check_contained(val):
        val = str(val).strip()
        if not val or val.lower() == 'nan':
            return False
        return customer_name in val or (clean_name and clean_name in val)
    
    mask5 = customer_col.apply(check_contained)
    if mask5.sum() > 0:
        return mask5
    
    return _pd.Series([False] * len(df), index=df.index)

# ─────────────────────────────────────────────────────────────
# 解析函數
# ─────────────────────────────────────────────────────────────

def _detect_canonical_branch(q: str) -> Optional[str]:
    """從查詢中偵測營業所"""
    q = q or ""
    for canonical, syns in BRANCH_SYNONYMS.items():
        if canonical in q:
            return canonical
        for s in syns:
            if s and s in q:
                return canonical
    return None


def _parse_date_from_query(q: str) -> Tuple[Optional[_dt.date], Optional[tuple]]:
    """
    解析查詢中的時間資訊
    
    Returns:
        (exact_date, year_month_or_range)
        - exact_date: 單一日期 (date object) 或 None
        - year_month_or_range: 
          - (year, month) 表示某年某月
          - ('range', start_date, end_date) 表示日期範圍
          - None
    """
    if not q:
        return None, None
    
    today = _dt.date.today()
    
    # 1. 最近30天 / 最近一個月
    if re.search(r'最近30[天日]|最近一個?月', q):
        start = today - _dt.timedelta(days=30)
        return None, ('range', start, today)
    
    # 2. 最近7天 / 最近一週
    if re.search(r'最近7[天日]|最近一[個]?[週周禮拜]', q):
        start = today - _dt.timedelta(days=7)
        return None, ('range', start, today)
    
    # 3. 最近N天
    m = re.search(r'最近(\d+)[天日]', q)
    if m:
        days = int(m.group(1))
        start = today - _dt.timedelta(days=days)
        return None, ('range', start, today)
    
    # 4. 最近N週
    m = re.search(r'最近(\d+)[週周]', q)
    if m:
        weeks = int(m.group(1))
        start = today - _dt.timedelta(weeks=weeks)
        return None, ('range', start, today)
    
    # 5. 最近N個月
    m = re.search(r'最近(\d+)個?月', q)
    if m:
        months = int(m.group(1))
        start = today - _dt.timedelta(days=months * 30)
        return None, ('range', start, today)
    
    # 6. 最近 / 最近的活動 → 預設 90 天
    if re.search(r'最近(?:的)?(?:活動|紀錄|記錄|業務)?', q):
        start = today - _dt.timedelta(days=90)
        return None, ('range', start, today)
    
    # 7. YYYY年MM月 或 YYYY/MM
    m = re.search(r'(20\d{2})[年/\-](\d{1,2})月?', q)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return None, (y, mo)
    
    # 8. 單獨的「N月」
    m = re.search(r'(?<!\d)(\d{1,2})月(?!\d)', q)
    if m:
        mo = int(m.group(1))
        y = today.year
        return None, (y, mo)
    
    # 9. 具體日期 YYYY/MM/DD
    m = re.search(r'(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})', q)
    if m:
        try:
            d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d, None
        except ValueError:
            pass
    
    return None, None

# ─────────────────────────────────────────────────────────────
# 輸出格式化
# ─────────────────────────────────────────────────────────────

def _format_markdown_table(df, limit: int = 50) -> str:
    """將 DataFrame 格式化為 Markdown 表格"""
    if df.empty:
        return ""
    
    df_show = df.head(limit)
    cols = ['Date', 'Worker', 'Customer', 'Class', 'Content']
    cols = [c for c in cols if c in df_show.columns]
    
    header = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    
    rows = []
    for _, r in df_show.iterrows():
        row_vals = []
        for c in cols:
            val = str(r.get(c, ""))[:80]  # 截斷過長內容
            val = val.replace("|", "｜").replace("\n", " ")
            row_vals.append(val)
        rows.append("| " + " | ".join(row_vals) + " |")
    
    return header + "\n" + sep + "\n" + "\n".join(rows)


def _class_distribution(df) -> Dict[str, int]:
    """統計活動類型分佈"""
    if 'Class' not in df.columns:
        return {}
    
    dist = {}
    for val in df['Class'].astype(str).fillna(''):
        parts = [p.strip() for p in re.split(r'[、,，/]+', val) if p.strip()]
        for p in parts:
            dist[p] = dist.get(p, 0) + 1
    
    return dict(sorted(dist.items(), key=lambda x: -x[1]))

# ─────────────────────────────────────────────────────────────
# 主查詢函數
# ─────────────────────────────────────────────────────────────

def _direct_business_query_text(query: str, csv_path: str = None) -> Optional[str]:
    """
    直接從 CSV 查詢業務資料
    
    Args:
        query: 查詢字串（如「台南營業所最近的活動」「客戶東台精機的活動」）
        csv_path: CSV 檔案路徑（可選，會自動偵測）
    
    Returns:
        格式化的查詢結果字串，或 None（查無資料）
    """
    if not _HAS_PANDAS:
        return None
    
    # 取得 CSV 路徑
    csv_path = csv_path or _guess_business_csv()
    if not csv_path or not os.path.exists(csv_path):
        return None
    
    # 讀取 CSV
    try:
        df = _pd.read_csv(csv_path, encoding='utf-8')
        # 過濾空行和無效資料
        df = df.dropna(how='all')  # 移除全空行
        df = df[df['Date'].notna() & (df['Date'].astype(str).str.strip() != '')]  # 確保有日期
    except Exception:
        return None
    
    if df.empty or 'Date' not in df.columns:
        return None
    
    # 解析查詢條件
    branch = _detect_canonical_branch(query or '')
    exact_date, year_month = _parse_date_from_query(query or '')
    customer_name = _extract_customer_name(query or '')
    
    # 建立過濾條件
    _df = df.copy()
    _df = _df.reset_index(drop=True)  # 🔧 重置 index 確保對齊
    _df['_Date'] = _pd.to_datetime(_df['Date'], errors='coerce')
    mask = _pd.Series([True] * len(_df), index=_df.index)  # 🔧 使用相同 index
    
    # 客戶過濾（優先級最高）
    if customer_name:
        customer_mask = _fuzzy_match_customer(_df, customer_name)
        # 🔧 確保 index 對齊
        customer_mask = customer_mask.reindex(_df.index, fill_value=False)
        if customer_mask.any():
            mask = mask & customer_mask
        else:
            # 找不到客戶，返回提示
            return f"❌ 查無客戶「{customer_name}」的相關記錄\n\n💡 建議：\n- 確認客戶名稱是否正確\n- 嘗試使用簡稱（如「東台」而非「東台精機」）"
    
    # 時間過濾
    if exact_date:
        mask = mask & (_df['_Date'].dt.date == exact_date)
    elif year_month:
        if isinstance(year_month, tuple) and len(year_month) == 3 and year_month[0] == 'range':
            _, start_date, end_date = year_month
            mask = mask & (_df['_Date'].dt.date >= start_date) & (_df['_Date'].dt.date <= end_date)
        else:
            y, m = year_month
            mask = mask & (_df['_Date'].dt.year == y) & (_df['_Date'].dt.month == m)
    
    # 營業所過濾
    if branch and 'Depart' in _df.columns:
        mask = mask & _df['Depart'].astype(str).str.contains(branch, na=False)
    
    # 執行過濾
    filtered = _df.loc[mask]  # 🔧 使用 .loc 而非直接索引
    if filtered.empty:
        return None
    
    # 統計
    total = len(filtered)
    visit_count = 0
    for v in filtered.get('Class', _pd.Series([], dtype=object)).astype(str).fillna(''):
        parts = [p.strip() for p in re.split(r'[、,，/]+', v) if p.strip()]
        if '業務拜訪' in parts:
            visit_count += 1
    
    # 主要客戶
    if 'Customer' in filtered.columns:
        top_customers = (filtered['Customer'].astype(str).fillna('')
                        .replace('', _pd.NA).dropna()
                        .value_counts().head(5).index.tolist())
    else:
        top_customers = []
    
    # 活動類型分佈
    dist = _class_distribution(filtered)
    dist_text = ', '.join([f"{k}: {v}次" for k, v in list(dist.items())[:8]]) if dist else 'N/A'
    
    # 日期標題
    if exact_date:
        title_date = f"{exact_date.year}/{exact_date.month}/{exact_date.day}"
    elif year_month:
        if isinstance(year_month, tuple) and len(year_month) == 3 and year_month[0] == 'range':
            _, start_date, end_date = year_month
            title_date = f"{start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')}"
        else:
            y, m = year_month
            title_date = f"{y}/{m:02d}"
    else:
        title_date = "全部"
    
    branch_text = branch or "全部營業所"
    
    # 排序並取前 50 筆
    filtered_sorted = filtered.sort_values('_Date', ascending=False)
    table_md = _format_markdown_table(filtered_sorted, limit=50)
    
    # 組合輸出
    result = f"""**查詢結果概述**
{title_date} {branch_text} 共有 {total} 筆業務記錄，其中業務拜訪 {visit_count} 筆。

**詳細記錄**
{table_md}

**統計分析**
- **筆數**: {total}
- **主要客戶**: {', '.join(top_customers[:5]) if top_customers else 'N/A'}
- **活動類型**: {dist_text}

**時間軸分析**
"""
    
    # 加入時間軸（最新 5 筆）
    for _, r in filtered_sorted.head(5).iterrows():
        d = r.get('Date', 'N/A')
        w = r.get('Worker', 'N/A')
        c = r.get('Customer', 'N/A')
        cls = r.get('Class', 'N/A')
        result += f"- {d}: {w} 拜訪 {c}，進行 {cls}\n"
    
    result += "\n📋 參考資料來源：\nbusiness"
    
    return result

# ─────────────────────────────────────────────────────────────
# Debug 函數
# ─────────────────────────────────────────────────────────────

def debug_business_csv(query: str) -> str:
    """Debug 用：測試 CSV 查詢"""
    try:
        result = _direct_business_query_text(query)
        return result or "沒有命中 CSV"
    except Exception as e:
        return f"錯誤: {e}"
