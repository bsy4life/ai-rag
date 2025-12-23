import os
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime

# === 常數定義 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_DB_DIR = os.path.join(BASE_DIR, "data", "vectordb_sanshin")

HASH_FILE_TECH = os.path.join(VECTOR_DB_DIR, "technical_docs_hash.txt")
HASH_FILE_BIZ = os.path.join(VECTOR_DB_DIR, "business_reports_hash.txt")


# === Hash 計算工具 ===
def hash_dir(path: str) -> str:
    """計算資料夾內所有檔案的 hash"""
    sha = hashlib.sha256()
    path_obj = Path(path)
    if not path_obj.exists():
        return ""

    for file in sorted(path_obj.rglob("*")):
        if file.is_file():
            sha.update(file.name.encode("utf-8"))
            try:
                with open(file, "rb") as f:
                    while chunk := f.read(8192):
                        sha.update(chunk)
            except Exception:
                continue
    return sha.hexdigest()


def hash_csv_file(path: str) -> str:
    """計算 CSV 檔案的 hash"""
    sha = hashlib.sha256()
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


# === Hash 存取函數 ===
def save_hash_with_metadata(h: str, hash_file: str, stats: Dict):
    """保存 Hash 並記錄詳細統計資訊"""
    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    meta_lines = [
        f"hash={h}",
        f"records={stats.get('records', 0)}",
        f"files={stats.get('files', 0)}",
        f"generated_at={datetime.now().isoformat()}",
    ]
    with open(hash_file, "w", encoding="utf-8") as f:
        f.write("\n".join(meta_lines))


def load_hash_with_info(hash_file: str) -> Tuple[Optional[str], Dict]:
    """載入 Hash 與統計資訊"""
    if not os.path.exists(hash_file):
        return None, {}
    try:
        with open(hash_file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return None, {}

    h = None
    stats = {}
    for line in lines:
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k == "hash":
            h = v
        else:
            stats[k] = v
    return h, stats


def save_hash(h: str, hash_file: str):
    """保存 Hash (簡易版)"""
    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    with open(hash_file, "w", encoding="utf-8") as f:
        f.write(h)


def load_hash(hash_file: str) -> Optional[str]:
    """載入 Hash (簡易版)"""
    if not os.path.exists(hash_file):
        return None
    try:
        with open(hash_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


# === 向量庫摘要 ===
def generate_vectordb_summary() -> str:
    """生成向量庫摘要資訊"""
    lines = []
    for file, label in [(HASH_FILE_TECH, "技術文檔"), (HASH_FILE_BIZ, "業務資料")]:
        h, stats = load_hash_with_info(file)
        if not h:
            lines.append(f"{label}: 無紀錄")
        else:
            lines.append(
                f"{label}: hash={h[:10]}..., 記錄={stats.get('records', '?')} 筆, "
                f"檔案數={stats.get('files', '?')}, 生成時間={stats.get('generated_at', '?')}"
            )

    summary_file = os.path.join(VECTOR_DB_DIR, "vectordb_summary.txt")
    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return summary_file
