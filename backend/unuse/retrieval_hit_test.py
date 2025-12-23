#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retrieval_hit_test.py — Quick Hit@K test for your RAG retriever (Chroma).

Usage Examples:

  # 單筆（以內容關鍵字判定命中；預設 K=5）
  python retrieval_hit_test.py --query "LESHRP8 規格" --expect "LESHRP8" --k 5

  # 以檔名判定（例如預期命中 smoke.md）
  python retrieval_hit_test.py --query "LESHRP8 規格" --expect "smoke.md" --k 5 --match filename

  # 批次 TSV（首列 header: query\texpect）— 內容判定：
  python retrieval_hit_test.py queries.tsv --k 5

  # 批次 CSV（首列 header: query,expect）— 檔名判定：
  python retrieval_hit_test.py queries.csv --k 10 --match filename
"""
import argparse
import os
import sys
import unicodedata
from typing import List, Tuple

try:
    import core  # reuse your existing vectorstore/client + NFKC
except Exception as e:
    print(f"❌ 無法匯入 core.py：{e}", file=sys.stderr)
    sys.exit(1)

def nfkc(s: str) -> str:
    try:
        return core._nfkc(s)  # 用你的正規化
    except Exception:
        return unicodedata.normalize("NFKC", s or "")

def get_vectordb():
    """建同設定的 Chroma vectorstore（跟你的 app 一致）"""
    try:
        client = core._make_client()
        vs = core._make_vectorstore(client)
        return vs
    except Exception as e:
        print(f"❌ 無法建立向量庫（請確認 core.py 已建庫）：{e}", file=sys.stderr)
        sys.exit(2)

def read_pairs_from_file(path: str) -> List[Tuple[str,str]]:
    pairs: List[Tuple[str,str]] = []
    with open(path, "r", encoding="utf-8") as f:
        header = f.readline()
        if not header:
            return pairs
        header = header.strip()
        delim = "\t" if ("\t" in header) else ","
        cols = [c.strip() for c in header.split(delim)]
        try:
            qi = cols.index("query")
            ei = cols.index("expect")
        except ValueError:
            raise ValueError("檔案首行需包含欄位 'query' 與 'expect'")
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = [p.strip() for p in line.split(delim)]
            if max(qi, ei) >= len(parts):
                continue
            q = parts[qi]
            e = parts[ei]
            if q:
                pairs.append((q, e))
    return pairs

def match_hit(doc, expect: str, mode: str) -> bool:
    """命中判定：mode='content' 比內容；'filename' 比來源檔名"""
    if mode == "filename":
        src = (doc.metadata or {}).get("source", "") or ""
        base = os.path.basename(src)
        return expect.lower() in base.lower()
    txt = doc.page_content or ""
    return nfkc(expect) in nfkc(txt)

def eval_single_query(vs, query: str, expect: str, k: int, mode: str):
    docs = vs.similarity_search(nfkc(query), k=k)
    hit = any(match_hit(d, expect, mode) for d in docs)
    top_sources = [os.path.basename((d.metadata or {}).get("source","")) for d in docs]
    return hit, top_sources

def main(argv=None):
    ap = argparse.ArgumentParser(description="Compute Hit@K for your retriever quickly.")
    ap.add_argument("file", nargs="?", help="TSV/CSV 檔（欄位：query, expect），可省略用 --query/--expect")
    ap.add_argument("--query", help="單筆查詢")
    ap.add_argument("--expect", help="單筆預期（關鍵字或檔名片段）")
    ap.add_argument("--k", type=int, default=5, help="Top-K（預設 5）")
    ap.add_argument("--match", choices=["content","filename"], default="content",
                    help="命中判定方式：content=內容關鍵字（預設）、filename=來源檔名包含 expect")
    args = ap.parse_args(argv)

    if args.file is None and (not args.query or not args.expect):
        ap.error("需要 TSV/CSV 檔案，或同時提供 --query 與 --expect")

    vs = get_vectordb()

    tests: List[Tuple[str,str]] = []
    if args.file:
        tests = read_pairs_from_file(args.file)
        if not tests:
            print("⚠️ 檔案沒有可用測試列", file=sys.stderr)
            return 3
    else:
        tests = [(args.query, args.expect)]

    total = len(tests)
    hits = 0

    print(f"🔎 評估 {total} 筆，K={args.k}，模式={args.match}")
    for i, (q, e) in enumerate(tests, 1):
        ok, sources = eval_single_query(vs, q, e, args.k, args.match)
        hits += int(ok)
        status = "✅ HIT" if ok else "❌ MISS"
        print(f"[{i}/{total}] {status}  Q='{q}'  Expect='{e}'")
        print(f"        Top{args.k} sources: {', '.join(sources) if sources else '(none)'}")

    rate = (hits / total * 100.0) if total else 0.0
    print(f"—— Hit@{args.k}: {hits}/{total} = {rate:.1f}% ——")
    return 0 if hits == total else 1

if __name__ == "__main__":
    sys.exit(main())
