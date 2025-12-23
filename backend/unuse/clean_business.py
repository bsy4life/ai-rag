#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_business.py
將《業務日報格式.txt》類原始文字檔清洗為結構化 CSV，並輸出簡易 Markdown 預覽。

特點：
- 以換頁符 \f 視為各筆紀錄分隔（若無換頁，也會嘗試以 Doc_Time/Date 等關鍵欄位切分）
- 解析常見欄位：Date, Worker, Customer, Class, Content, Depart, Manager, Level, Doc_Status, TimeCreated, Doc_Time
- 正規化日期為 YYYY/MM/DD、活動類型為「逗號+空白」清單
- 自動從 $UpdatedBy / Manager 中抽出 CN=中文名
- 可一次處理多個檔案
- 產出：clean_business.csv（UTF-8 BOM）與 clean_business_preview.md

需求：
- Python 3.8+
- pandas
"""

from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    print("❌ 需要套件 pandas，請先安裝： pip install pandas", file=sys.stderr)
    sys.exit(1)

# -----------------------
# 解析與正規化工具
# -----------------------

KEY_MAP = {
    # 正規化欄位名稱映射
    "date": "Date",
    "日期": "Date",
    "worker": "Worker",
    "員工": "Worker",
    "customer": "Customer",
    "客戶": "Customer",
    "class": "Class",
    "活動類型": "Class",
    "content": "Content",
    "活動內容": "Content",
    "depart": "Depart",
    "部門": "Depart",
    "manager": "Manager",
    "主管": "Manager",
    "submanager": "SubManager",
    "level": "Level",
    "doc_st": "Doc_Status",
    "文件狀態": "Doc_Status",
    "timecreated": "TimeCreated",
    "doc_time": "Doc_Time",
    "$updatedby": "$UpdatedBy",
}

TARGET_COLS = [
    "Date","Worker","Customer","Class","Content","Depart",
    "Manager","Level","Doc_Status","TimeCreated","Doc_Time"
]

RE_KEY_VALUE = re.compile(r"^([A-Za-z0-9_\-$\u4e00-\u9fa5]+)\s*[:：]\s*(.*)$")

def normalize_key(k: str) -> str:
    k = k.strip()
    k_l = k.lower()
    # 先 map 英/中 → 標準 key
    if k_l in KEY_MAP:
        return KEY_MAP[k_l]
    # 特殊鍵（大小寫／中英文混搭）
    if k in KEY_MAP:
        return KEY_MAP[k]
    # 已經是標準目標欄位
    if k in TARGET_COLS or k in ["$UpdatedBy", "SubManager"]:
        return k
    # fallback：維持原樣（避免遺失資訊）
    return k

def normalize_date(s: str) -> str:
    """將日期正規化為 YYYY/MM/DD；若無法解析則原樣返回。"""
    s = (s or "").strip()
    if not s:
        return s
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}/{int(mo):02d}/{int(d):02d}"
    # 有時 Date 不純，嘗試在字串中抓第一個 YYYY-MM-DD/ YYYY/MM/DD
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}/{int(mo):02d}/{int(d):02d}"
    return s

def normalize_class(s: str) -> str:
    """將活動類型字串清洗成以逗號+空白分隔的清單文字。"""
    s = (s or "").strip()
    if not s:
        return s
    s = s.replace("，", ",").replace("、", ",")
    s = s.replace(" ", "")
    parts = [p for p in re.split(r"[,\s]+", s) if p]
    return ", ".join(parts)

def extract_cn_name(s: str) -> str:
    """
    從類似 'CN=黃德霖/O=Sanshin' 抽出 '黃德霖'。
    若沒有 CN=，則回傳原字串。
    """
    if not isinstance(s, str):
        return s
    m = re.search(r"CN=([^/，,；;\s]+)", s)
    return m.group(1) if m else s

def guess_record_splits(text: str) -> List[str]:
    """
    初步切分紀錄：
    - 優先使用 \f
    - 若無 \f，則以出現 'Doc_Time:' 或 'Date:' 的行為分段起始，聚合到下一段開始前
    """
    if "\f" in text:
        blocks = re.split(r"\f+", text)
        return [b for b in blocks if b.strip()]
    # 退路：以關鍵欄位行為分段
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
    """
    解析單一區塊為欄位 dict，僅保留 TARGET_COLS ＋少量關鍵輔助欄位。
    """
    data: Dict[str, str] = {
        "Date": "",
        "Worker": "",
        "Customer": "",
        "Class": "",
        "Content": "",
        "Depart": "",
        "Manager": "",
        "Level": "",
        "Doc_Status": "",
        "TimeCreated": "",
        "Doc_Time": "",
    }

    # 行清洗
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]

    # 暫存原始鍵值（防止同鍵多次出現時的覆蓋）
    raw_map: Dict[str, str] = {}

    for ln in lines:
        m = RE_KEY_VALUE.match(ln)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        norm_k = normalize_key(k)
        if norm_k in raw_map:
            # 合併（用分號連接），避免覆蓋掉
            raw_map[norm_k] = f"{raw_map[norm_k]}; {v}"
        else:
            raw_map[norm_k] = v

    # 映射到標準欄位
    for tgt in data.keys():
        if tgt in raw_map:
            data[tgt] = raw_map[tgt]

    # 從 $UpdatedBy 推 Worker，若 Worker 空
    if not data["Worker"] and "$UpdatedBy" in raw_map:
        data["Worker"] = extract_cn_name(raw_map["$UpdatedBy"])

    # Manager 也抽 CN 名
    if data["Manager"]:
        data["Manager"] = extract_cn_name(data["Manager"])

    # 正規化日期與活動類型
    data["Date"] = normalize_date(data["Date"])
    data["Class"] = normalize_class(data["Class"])

    return data

def clean_files(input_paths: List[Path]) -> pd.DataFrame:
    """讀取多個檔案，清洗並彙整為單一 DataFrame。"""
    rows: List[Dict[str, str]] = []

    for p in input_paths:
        if not p.exists() or not p.is_file():
            print(f"⚠️ 跳過不存在的檔案：{p}", file=sys.stderr)
            continue
        # 嘗試以 UTF-8 讀取，不行就用 cp950/big5 作為退路
        for enc in ("utf-8", "cp950", "big5", "utf-8-sig"):
            try:
                text = p.read_text(encoding=enc, errors="ignore")
                break
            except Exception:
                text = None
        if text is None:
            print(f"❌ 無法讀取檔案：{p}", file=sys.stderr)
            continue

        blocks = guess_record_splits(text)
        for b in blocks:
            rec = parse_block(b)
            # 至少要有 Date 或 Content 才視為有效
            if any(rec.values()) and (rec.get("Date") or rec.get("Content")):
                rows.append(rec)

    if not rows:
        return pd.DataFrame(columns=TARGET_COLS)

    df = pd.DataFrame(rows, columns=TARGET_COLS).drop_duplicates().reset_index(drop=True)

    # 產生月份欄位 YYYY/MM
    df["_Month"] = df["Date"].astype(str).str.slice(0, 7)
    return df

def save_outputs(df: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "clean_business.csv"
    md_path  = out_dir / "clean_business_preview.md"

    # CSV（BOM 以利 Excel 開啟中文不亂碼）
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Markdown 簡報（每月/業務活動數）
    md_lines = ["# 業務日報清洗預覽", ""]
    if not df.empty:
        piv = (df.groupby(["_Month","Worker"])
                 .size()
                 .rename("活動數")
                 .reset_index()
                 .sort_values(["_Month","活動數"], ascending=[True, False]))
        try:
            md_lines += ["## 每月各業務活動數", "", piv.to_markdown(index=False), ""]
        except Exception:
            # 某些環境無 tabulate 支援時退路
            md_lines += ["## 每月各業務活動數", "", str(piv), ""]

        # 範例前 30 筆
        sample = df[TARGET_COLS].head(30)
        try:
            md_lines += ["## 清洗後樣例（前 30 筆）", "", sample.to_markdown(index=False), ""]
        except Exception:
            md_lines += ["## 清洗後樣例（前 30 筆）", "", str(sample), ""]

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"✅ 已輸出 CSV：{csv_path}")
    print(f"✅ 已輸出預覽：{md_path}")
    print(f"📊 資料筆數：{len(df)}")

# -----------------------
# CLI
# -----------------------

def main():
    ap = argparse.ArgumentParser(
        description="清洗《業務日報》原始文字檔，輸出結構化 CSV 與 Markdown 預覽"
    )
    ap.add_argument(
        "inputs",
        nargs="+",
        help="輸入路徑（檔案或資料夾，支援多個）。若為資料夾，會抓取其中所有 .txt 檔"
    )
    ap.add_argument(
        "-o", "--out-dir",
        default="./",
        help="輸出資料夾（預設為目前目錄）"
    )
    args = ap.parse_args()

    in_paths: List[Path] = []
    for item in args.inputs:
        p = Path(item)
        if p.is_dir():
            in_paths += list(p.glob("*.txt"))
        elif p.is_file():
            in_paths.append(p)
        else:
            print(f"⚠️ 跳過無效路徑：{p}", file=sys.stderr)

    if not in_paths:
        print("❌ 找不到可處理的輸入檔案（.txt）", file=sys.stderr)
        sys.exit(2)

    df = clean_files(in_paths)
    save_outputs(df, Path(args.out_dir))


if __name__ == "__main__":
    main()
