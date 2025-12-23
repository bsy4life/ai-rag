# biz_incremental.py
import os, hashlib
from typing import Dict, List

# 從你的 core.py 取用既有設定與 embedding（不動 core 原始碼）
from core import VECTOR_DB_DIR, COLLECTION_NAME_BIZ, BUSINESS_CSV_FILE, embedding
from langchain_chroma import Chroma
from langchain_core.documents import Document

def _first(row: dict, keys: List[str]) -> str:
    for k in keys:
        v = str(row.get(k, "") or "").strip()
        if v:
            return v
    return ""

def _stable_row_id(row: dict) -> str:
    # 以關鍵欄位組合做 SHA1，確保同一筆商務紀錄有穩定 ID
    sig = "|".join([
        _first(row, ["Date", "日期", "date"]),
        _first(row, ["Worker", "業務", "業務人員", "人員", "worker"]),
        _first(row, ["Customer", "客戶", "customer"]),
        _first(row, ["Class", "類別", "活動類型", "class"]),
        _first(row, ["Content", "活動內容", "內容", "備註", "說明", "content"]),
    ])
    return "biz:" + hashlib.sha1(sig.encode("utf-8")).hexdigest()

def sync_business_csv_embeddings(prune_deleted: bool = True) -> Dict:
    """
    增量 upsert 業務 CSV 到 Chroma：
      - 新/改：依穩定 row_id 先刪舊再加新
      - 刪：prune_deleted=True 會移除向量庫內但 CSV 已不存在的 row_id
    回傳: {"total":N, "upserted":x, "deleted":y}
    """
    try:
        import pandas as pd  # 用你的專案已經可選載入的 pandas
    except Exception as e:
        return {"total": 0, "upserted": 0, "deleted": 0, "error": f"pandas not available: {e}"}

    csv_path = BUSINESS_CSV_FILE
    if not csv_path or not os.path.exists(csv_path):
        return {"total": 0, "upserted": 0, "deleted": 0, "error": f"CSV not found: {csv_path}"}

    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8")
    except Exception as e:
        return {"total": 0, "upserted": 0, "deleted": 0, "error": f"read csv failed: {e}"}

    try:
        vectordb = Chroma(
            collection_name=COLLECTION_NAME_BIZ,
            embedding_function=embedding,
            persist_directory=VECTOR_DB_DIR,
        )
    except Exception as e:
        return {"total": 0, "upserted": 0, "deleted": 0, "error": f"vectordb init failed: {e}"}

    # 取得既有 ids
    try:
        got = vectordb.get(include=["ids"])
        existing_ids = set(got.get("ids", []))
    except Exception:
        existing_ids = set()

    # 建立文件與新 ids
    docs, new_ids = [], []
    for idx, row in df.iterrows():
        r = {k: ("" if row[k] is None else str(row[k])) for k in row.index}
        rid = _stable_row_id(r)
        new_ids.append(rid)
        content = (
            f"日期: {_first(r, ['Date','日期','date'])}\n"
            f"業務: {_first(r, ['Worker','業務','業務人員','人員','worker'])}\n"
            f"客戶: {_first(r, ['Customer','客戶','customer'])}\n"
            f"類別: {_first(r, ['Class','類別','活動類型','class'])}\n"
            f"內容: {_first(r, ['Content','活動內容','內容','備註','說明','content'])}\n"
        )
        meta = {
            "src": "business_csv",
            "doc_type": "business",
            "date": _first(r, ['Date','日期','date']),
            "worker": _first(r, ['Worker','業務','業務人員','人員','worker']),
            "customer": _first(r, ['Customer','客戶','customer']),
            "class": _first(r, ['Class','類別','活動類型','class']),
            "row_index": int(idx),
        }
        docs.append(Document(page_content=content, metadata=meta))

    # 先刪舊（只刪同一 rid 的舊資料，安全）
    to_delete = [rid for rid in new_ids if rid in existing_ids]
    deleted = 0
    if to_delete:
        try:
            vectordb.delete(ids=to_delete)
            deleted = len(to_delete)
        except Exception:
            pass

    # 再新增（分批）
    add_batch = max(1, min(int(os.getenv("EMBED_ADD_BATCH_BIZ", "512")), 2048))
    upserted = 0
    for i in range(0, len(docs), add_batch):
        batch_docs = docs[i:i+add_batch]
        batch_ids = new_ids[i:i+add_batch]
        try:
            vectordb.add_documents(batch_docs, ids=batch_ids)
            upserted += len(batch_docs)
        except Exception:
            # 某些批失敗也不中斷，盡量多 upsert
            pass

    # 清理 CSV 已刪除的舊資料
    pruned = 0
    if prune_deleted:
        new_set = set(new_ids)
        surplus = list(existing_ids - new_set)
        if surplus:
            try:
                vectordb.delete(ids=surplus)
                pruned = len(surplus)
            except Exception:
                pass

    try:
        vectordb.persist()
    except Exception:
        pass

    return {"total": len(new_ids), "upserted": upserted, "deleted": deleted + pruned}
