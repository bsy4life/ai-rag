#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
business_processor.py - 業務日報處理器（整合版）

功能：
1. 解析 Lotus Notes 匯出的業務日報 TXT
2. 日期過濾：只保留最近 N 個月的資料
3. 增量更新：與現有 CSV 合併，避免重複
4. 自動觸發向量庫重建

使用方式：
- CLI: python business_processor.py input.txt -m 12 -o ./data/business/
- API: 透過 /knowledge/upload-business 端點
"""

from __future__ import annotations
import argparse
import re
import os
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

try:
    import pandas as pd
except ImportError:
    raise ImportError("需要套件 pandas: pip install pandas")

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────

# 預設保留月數
DEFAULT_MONTHS_TO_KEEP = 12

# 欄位映射
KEY_MAP = {
    "date": "Date", "日期": "Date",
    "worker": "Worker", "員工": "Worker",
    "customer": "Customer", "客戶": "Customer",
    "class": "Class", "活動類型": "Class",
    "content": "Content", "活動內容": "Content",
    "depart": "Depart", "部門": "Depart",
    "manager": "Manager", "主管": "Manager",
    "level": "Level",
    "doc_st": "Doc_Status", "文件狀態": "Doc_Status",
    "timecreated": "TimeCreated",
    "doc_time": "Doc_Time",
    "$updatedby": "$UpdatedBy",
}

TARGET_COLS = [
    "Date", "Worker", "Customer", "Class", "Content", "Depart",
    "Manager", "Level", "Doc_Status", "TimeCreated", "Doc_Time"
]

RE_KEY_VALUE = re.compile(r"^([A-Za-z0-9_\-$\u4e00-\u9fa5]+)\s*[:：]\s*(.*)$")

# ─────────────────────────────────────────────────────────────
# 解析工具
# ─────────────────────────────────────────────────────────────

def normalize_key(k: str) -> str:
    """正規化欄位名稱"""
    k = k.strip()
    k_l = k.lower()
    if k_l in KEY_MAP:
        return KEY_MAP[k_l]
    if k in KEY_MAP:
        return KEY_MAP[k]
    if k in TARGET_COLS or k in ["$UpdatedBy", "SubManager"]:
        return k
    return k

def normalize_date(s: str) -> str:
    """將日期正規化為 YYYY/MM/DD"""
    s = (s or "").strip()
    if not s:
        return s
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}/{int(mo):02d}/{int(d):02d}"
    return s

def parse_date(s: str) -> Optional[datetime]:
    """解析日期字串為 datetime"""
    s = normalize_date(s)
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y/%m/%d")
    except:
        return None

def normalize_class(s: str) -> str:
    """清洗活動類型"""
    s = (s or "").strip()
    if not s:
        return s
    s = s.replace("，", ",").replace("、", ",").replace(" ", "")
    parts = [p for p in re.split(r"[,\s]+", s) if p]
    return ", ".join(parts)

def extract_cn_name(s: str) -> str:
    """從 CN=名字/O=Org 格式抽出名字"""
    if not isinstance(s, str):
        return s
    m = re.search(r"CN=([^/，,；;\s]+)", s)
    return m.group(1) if m else s

def compute_record_hash(rec: Dict[str, str]) -> str:
    """計算記錄的唯一 hash（用於去重）"""
    key_fields = ["Date", "Worker", "Customer", "Content", "TimeCreated"]
    key_str = "|".join(str(rec.get(f, "")) for f in key_fields)
    return hashlib.md5(key_str.encode()).hexdigest()[:12]

# ─────────────────────────────────────────────────────────────
# 記錄切分與解析
# ─────────────────────────────────────────────────────────────

def split_records(text: str) -> List[str]:
    """將文字切分為多筆記錄"""
    # 優先使用換頁符
    if "\f" in text:
        blocks = re.split(r"\f+", text)
        return [b for b in blocks if b.strip()]
    
    # 退路：以 Doc_Time 或 Date 行為分段
    lines = text.splitlines()
    blocks, curr = [], []
    rec_start_re = re.compile(r"^\s*(Doc_Time|Date)\s*[:：]")
    
    for ln in lines:
        if rec_start_re.search(ln) and curr:
            blocks.append("\n".join(curr))
            curr = [ln]
        else:
            curr.append(ln)
    if curr:
        blocks.append("\n".join(curr))
    
    return [b for b in blocks if b.strip()]

def parse_block(block: str) -> Dict[str, str]:
    """解析單一區塊為欄位 dict"""
    data = {col: "" for col in TARGET_COLS}
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    raw_map: Dict[str, str] = {}
    
    for ln in lines:
        m = RE_KEY_VALUE.match(ln)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        norm_k = normalize_key(k)
        if norm_k in raw_map:
            raw_map[norm_k] = f"{raw_map[norm_k]}; {v}"
        else:
            raw_map[norm_k] = v
    
    # 映射到標準欄位
    for tgt in data.keys():
        if tgt in raw_map:
            data[tgt] = raw_map[tgt]
    
    # 從 $UpdatedBy 推 Worker
    if not data["Worker"] and "$UpdatedBy" in raw_map:
        data["Worker"] = extract_cn_name(raw_map["$UpdatedBy"])
    
    # Manager 抽名字
    if data["Manager"]:
        data["Manager"] = extract_cn_name(data["Manager"])
    
    # 正規化
    data["Date"] = normalize_date(data["Date"])
    data["Class"] = normalize_class(data["Class"])
    
    return data

# ─────────────────────────────────────────────────────────────
# 主處理邏輯
# ─────────────────────────────────────────────────────────────

def process_business_file(
    input_path: str,
    months_to_keep: int = DEFAULT_MONTHS_TO_KEEP,
    existing_csv: Optional[str] = None,
    output_csv: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict]:
    """
    處理業務日報檔案
    
    Args:
        input_path: 輸入的 TXT 檔案路徑
        months_to_keep: 保留最近幾個月的資料
        existing_csv: 現有的 CSV 檔案（用於增量更新）
        output_csv: 輸出的 CSV 檔案路徑
    
    Returns:
        (DataFrame, 統計資訊)
    """
    stats = {
        "input_file": input_path,
        "raw_records": 0,
        "filtered_by_date": 0,
        "duplicates_removed": 0,
        "final_records": 0,
        "date_range": {"min": None, "max": None},
        "cutoff_date": None,
    }
    
    # 計算截止日期
    cutoff_date = datetime.now() - relativedelta(months=months_to_keep)
    stats["cutoff_date"] = cutoff_date.strftime("%Y/%m/%d")
    
    # 讀取輸入檔案
    input_path = Path(input_path)
    text = None
    for enc in ("utf-8", "utf-8-sig", "cp950", "big5"):
        try:
            text = input_path.read_text(encoding=enc, errors="ignore")
            break
        except:
            continue
    
    if text is None:
        raise ValueError(f"無法讀取檔案: {input_path}")
    
    # 解析記錄
    blocks = split_records(text)
    rows = []
    
    for b in blocks:
        rec = parse_block(b)
        if not any(rec.values()) or not (rec.get("Date") or rec.get("Content")):
            continue
        
        stats["raw_records"] += 1
        
        # 日期過濾
        rec_date = parse_date(rec["Date"])
        if rec_date and rec_date < cutoff_date:
            stats["filtered_by_date"] += 1
            continue
        
        # 加入 hash 用於去重
        rec["_hash"] = compute_record_hash(rec)
        rows.append(rec)
    
    # 建立 DataFrame
    df_new = pd.DataFrame(rows)
    
    if df_new.empty:
        return pd.DataFrame(columns=TARGET_COLS), stats
    
    # 合併現有資料（如果有的話）
    if existing_csv and Path(existing_csv).exists():
        try:
            df_existing = pd.read_csv(existing_csv, encoding="utf-8-sig")
            
            # 確保現有資料也有 hash
            if "_hash" not in df_existing.columns:
                df_existing["_hash"] = df_existing.apply(
                    lambda r: compute_record_hash(r.to_dict()), axis=1
                )
            
            # 現有資料也要過濾日期
            df_existing["_parsed_date"] = df_existing["Date"].apply(parse_date)
            df_existing = df_existing[
                df_existing["_parsed_date"].isna() | 
                (df_existing["_parsed_date"] >= cutoff_date)
            ]
            df_existing = df_existing.drop(columns=["_parsed_date"])
            
            # 合併並去重
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            before_dedup = len(df_combined)
            df_combined = df_combined.drop_duplicates(subset=["_hash"], keep="last")
            stats["duplicates_removed"] = before_dedup - len(df_combined)
            
            df_final = df_combined
        except Exception as e:
            print(f"⚠️ 讀取現有 CSV 失敗，將使用新資料: {e}")
            df_final = df_new.drop_duplicates(subset=["_hash"], keep="last")
    else:
        df_final = df_new.drop_duplicates(subset=["_hash"], keep="last")
    
    # 移除 hash 欄位，整理輸出
    if "_hash" in df_final.columns:
        df_final = df_final.drop(columns=["_hash"])
    
    # 確保欄位順序
    for col in TARGET_COLS:
        if col not in df_final.columns:
            df_final[col] = ""
    df_final = df_final[TARGET_COLS]
    
    # 依日期排序（最新在前）
    df_final = df_final.sort_values("Date", ascending=False).reset_index(drop=True)
    
    # 統計
    stats["final_records"] = len(df_final)
    if not df_final.empty:
        dates = df_final["Date"].dropna()
        if len(dates) > 0:
            stats["date_range"]["min"] = dates.min()
            stats["date_range"]["max"] = dates.max()
    
    # 輸出 CSV
    if output_csv:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df_final.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 已輸出: {output_path}")
    
    return df_final, stats

def generate_summary(df: pd.DataFrame, stats: Dict) -> str:
    """產生處理摘要"""
    lines = [
        "# 業務日報處理摘要",
        "",
        f"- 處理時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 原始記錄: {stats['raw_records']} 筆",
        f"- 日期過濾: {stats['filtered_by_date']} 筆（早於 {stats['cutoff_date']}）",
        f"- 去重: {stats['duplicates_removed']} 筆",
        f"- 最終記錄: {stats['final_records']} 筆",
        "",
    ]
    
    if stats["date_range"]["min"]:
        lines.append(f"- 資料範圍: {stats['date_range']['min']} ~ {stats['date_range']['max']}")
    
    if not df.empty:
        # 各業務活動數統計
        lines.append("")
        lines.append("## 各業務活動數（最近）")
        worker_counts = df.groupby("Worker").size().sort_values(ascending=False).head(10)
        for worker, count in worker_counts.items():
            lines.append(f"- {worker}: {count} 筆")
        
        # 活動類型統計
        lines.append("")
        lines.append("## 活動類型分布")
        class_counts = df["Class"].value_counts().head(10)
        for cls, count in class_counts.items():
            lines.append(f"- {cls}: {count} 筆")
    
    return "\n".join(lines)


def cleanup_old_business_files(business_dir: str, keep_count: int = 3) -> List[str]:
    """
    清理舊的業務資料檔案，只保留最新的幾個
    
    Args:
        business_dir: 業務資料目錄
        keep_count: 保留的檔案數量
    
    Returns:
        被刪除的檔案列表
    """
    import glob
    
    # 找出所有帶時間戳的業務檔案
    pattern = os.path.join(business_dir, "business_*.csv")
    files = glob.glob(pattern)
    
    # 排除固定檔名
    files = [f for f in files if not f.endswith("clean_business.csv")]
    
    if len(files) <= keep_count:
        return []
    
    # 按修改時間排序（最新的在前）
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    # 刪除舊檔案
    deleted = []
    for f in files[keep_count:]:
        try:
            os.remove(f)
            deleted.append(os.path.basename(f))
            print(f"🗑️ 已刪除舊檔案: {os.path.basename(f)}")
        except Exception as e:
            print(f"⚠️ 無法刪除 {f}: {e}")
    
    # 同時清理舊的 summary 檔案
    summary_files = glob.glob(os.path.join(business_dir, "business_summary*.md"))
    for sf in summary_files:
        try:
            os.remove(sf)
            deleted.append(os.path.basename(sf))
            print(f"🗑️ 已刪除摘要檔案: {os.path.basename(sf)}")
        except:
            pass
    
    return deleted

# ─────────────────────────────────────────────────────────────
# API 整合函數
# ─────────────────────────────────────────────────────────────

def process_and_update_knowledge_base(
    input_path: str,
    business_dir: str,
    months_to_keep: int = DEFAULT_MONTHS_TO_KEEP,
    trigger_reload: bool = True
) -> Dict:
    """
    處理業務日報並更新知識庫（供 API 呼叫）
    
    Args:
        input_path: 上傳的 TXT 檔案路徑
        business_dir: 業務資料目錄
        months_to_keep: 保留月數
        trigger_reload: 是否觸發向量庫重建
    
    Returns:
        處理結果
    """
    # 產生帶日期的檔名：business_YYYYMMDD_HHMM.csv
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    new_csv_name = f"business_{timestamp}.csv"
    new_csv_path = os.path.join(business_dir, new_csv_name)
    
    # 固定檔名（供系統使用）
    fixed_csv_path = os.path.join(business_dir, "clean_business.csv")
    
    # 處理檔案
    df, stats = process_business_file(
        input_path=input_path,
        months_to_keep=months_to_keep,
        existing_csv=fixed_csv_path if os.path.exists(fixed_csv_path) else None,
        output_csv=new_csv_path
    )
    
    # 同時更新固定檔名（供系統查詢用）
    if os.path.exists(new_csv_path):
        import shutil
        shutil.copy2(new_csv_path, fixed_csv_path)
    
    # 清理舊的時間戳檔案（只保留最新 3 個）
    cleanup_old_business_files(business_dir, keep_count=3)
    
    result = {
        "success": True,
        "stats": stats,
        "csv_path": new_csv_path,
        "csv_name": new_csv_name,
        "fixed_csv_path": fixed_csv_path,
    }
    
    # 觸發重建（如果需要）
    if trigger_reload:
        try:
            from core import reload_qa_system
            reload_qa_system()
            result["reloaded"] = True
        except Exception as e:
            result["reloaded"] = False
            result["reload_error"] = str(e)
    
    return result

# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="業務日報處理器 - 支援日期過濾和增量更新"
    )
    parser.add_argument("input", help="輸入的 TXT 檔案")
    parser.add_argument(
        "-m", "--months", type=int, default=DEFAULT_MONTHS_TO_KEEP,
        help=f"保留最近幾個月的資料（預設: {DEFAULT_MONTHS_TO_KEEP}）"
    )
    parser.add_argument(
        "-o", "--output-dir", default="./",
        help="輸出目錄（預設: 當前目錄）"
    )
    parser.add_argument(
        "--merge", action="store_true",
        help="與現有 CSV 合併（增量更新）"
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 產生帶時間戳的檔名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = output_dir / f"business_{timestamp}.csv"
    fixed_csv_path = output_dir / "clean_business.csv"
    
    existing = str(fixed_csv_path) if args.merge and fixed_csv_path.exists() else None
    
    df, stats = process_business_file(
        input_path=args.input,
        months_to_keep=args.months,
        existing_csv=existing,
        output_csv=str(csv_path)
    )
    
    # 同時更新固定檔名
    import shutil
    shutil.copy2(str(csv_path), str(fixed_csv_path))
    
    # 清理舊檔案
    cleanup_old_business_files(str(output_dir), keep_count=3)
    
    # 輸出摘要到終端
    summary = generate_summary(df, stats)
    print("\n" + summary)
    print(f"\n✅ 已儲存: {csv_path}")
    print(f"✅ 已更新: {fixed_csv_path}")

if __name__ == "__main__":
    main()
