# business_query.py
# 專責：把使用者中文查詢轉成 Chroma 的 metadata filter
# 版本：優化版 - 移除與 core.py 重複的功能

from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────
# 常數定義
# ─────────────────────────────────────────────────────────────

TZ = timezone(timedelta(hours=8))  # Asia/Taipei

# 業務員 → 營業所 對照表
BRANCH_BY_WORKER: Dict[str, str] = {
    # 台南
    "蔡俊昇": "台南", "黃淯麟": "台南", "林振宇": "台南",
    "徐銘邦": "台南", "陳俊役": "台南", "呂政輝": "台南",
    # 高雄
    "蘇鳳池": "高雄", "陳晉緯": "高雄", "蔡翔宇": "高雄", "黃德霖": "高雄",
    # 台中
    "廖緯霖": "台中", "廖茂辰": "台中", "蔡豐升": "台中", "黃源賀": "台中",
    "許閔傑": "台中", "陳政寬": "台中", "廖祐誠": "台中",
    # 台北
    "吳宜澤": "台北", "劉明宗": "台北", "陳韻龍": "台北",
}

# ─────────────────────────────────────────────────────────────
# 時間窗解析
# ─────────────────────────────────────────────────────────────

def _month_range(year: int, month: int) -> Tuple[datetime, datetime]:
    """計算指定月份的起迄日期"""
    start = datetime(year, month, 1, tzinfo=TZ)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=TZ) - timedelta(seconds=1)
    else:
        end = datetime(year, month + 1, 1, tzinfo=TZ) - timedelta(seconds=1)
    return start, end


def parse_time_window(q: str, now: Optional[datetime] = None) -> Tuple[str, str]:
    """
    從查詢字串解析時間窗，回傳 (start, end) 格式為 "YYYY/MM/DD"
    
    支援格式：
      - 2025年10月 / 2025-10 / 2025/10
      - 最近 / 最近的活動 → 90 天
      - 最近一個月 / 最近30天 → 30 天
      - 最近一週 / 最近7天 → 7 天
      - 最近N天 / 最近N週 / 最近N個月
    """
    now = now or datetime.now(TZ)

    # 1. YYYY年MM月 或 YYYY-MM / YYYY/MM
    m = re.search(r'(20\d{2})[年/\-\.](\d{1,2})月?', q)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        s, e = _month_range(y, mo)
        return s.strftime("%Y/%m/%d"), e.strftime("%Y/%m/%d")

    # 2. 最近30天 / 最近一個月
    if re.search(r'最近30[天日]|最近一個?月', q):
        s = now - timedelta(days=30)
        return s.strftime("%Y/%m/%d"), now.strftime("%Y/%m/%d")

    # 3. 最近7天 / 最近一週
    if re.search(r'最近7[天日]|最近一[個]?[週周禮拜]', q):
        s = now - timedelta(days=7)
        return s.strftime("%Y/%m/%d"), now.strftime("%Y/%m/%d")

    # 4. 最近N天
    m = re.search(r'最近(\d+)[天日]', q)
    if m:
        days = int(m.group(1))
        s = now - timedelta(days=days)
        return s.strftime("%Y/%m/%d"), now.strftime("%Y/%m/%d")

    # 5. 最近N週
    m = re.search(r'最近(\d+)[週周]', q)
    if m:
        weeks = int(m.group(1))
        s = now - timedelta(weeks=weeks)
        return s.strftime("%Y/%m/%d"), now.strftime("%Y/%m/%d")

    # 6. 最近N個月
    m = re.search(r'最近(\d+)個?月', q)
    if m:
        months = int(m.group(1))
        s = now - timedelta(days=months * 30)
        return s.strftime("%Y/%m/%d"), now.strftime("%Y/%m/%d")

    # 7. 最近 / 最近的活動 → 預設 90 天
    if re.search(r'最近(?:的)?(?:活動|紀錄|記錄|業務)?', q):
        s = now - timedelta(days=90)
        return s.strftime("%Y/%m/%d"), now.strftime("%Y/%m/%d")

    # 預設：近 30 天
    s = now - timedelta(days=30)
    return s.strftime("%Y/%m/%d"), now.strftime("%Y/%m/%d")

# ─────────────────────────────────────────────────────────────
# 營業所 / 業務員解析
# ─────────────────────────────────────────────────────────────

def parse_branch(q: str) -> Optional[str]:
    """從查詢中解析營業所"""
    q = (q or "").lower()
    if "台南" in q or "臺南" in q or "tainan" in q:
        return "台南"
    if "台中" in q or "臺中" in q or "taichung" in q:
        return "台中"
    if "高雄" in q or "kaohsiung" in q:
        return "高雄"
    if "台北" in q or "臺北" in q or "taipei" in q:
        return "台北"
    return None


def parse_workers(q: str) -> List[str]:
    """從查詢中擷取業務員名字"""
    return [name for name in BRANCH_BY_WORKER if name in q]


def workers_for_branch(branch: str) -> List[str]:
    """取得指定營業所的所有業務員"""
    return [w for w, b in BRANCH_BY_WORKER.items() if b == branch]

# ─────────────────────────────────────────────────────────────
# Chroma Filter 建構（核心功能）
# ─────────────────────────────────────────────────────────────

def build_chroma_filter(q: str, *, now: Optional[datetime] = None) -> Dict:
    """
    將查詢轉成 Chroma vectorstore 的 filter
    
    用於 LangChain 的 similarity_search(filter=...) 
    日期存為字串 "YYYY/MM/DD"，用字典序比較
    
    Returns:
        Dict: Chroma filter，例如:
        {
            "date": {"$gte": "2025/08/01", "$lte": "2025/10/31"},
            "worker": {"$in": ["黃淯麟", "林振宇"]}
        }
    """
    start, end = parse_time_window(q, now=now)
    f: Dict = {"date": {"$gte": start, "$lte": end}}

    # 1) 若指定業務員，以人名優先
    names = parse_workers(q)
    if names:
        f["worker"] = {"$in": names}
        return f

    # 2) 否則看是否提到營業所
    branch = parse_branch(q)
    if branch:
        ws = workers_for_branch(branch)
        if ws:
            f["worker"] = {"$in": ws}

    return f
