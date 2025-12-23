# test_tech_extract.py
# 純離線：從 Markdown 抽出包含「NO.6500 / 6500 / 6500AC / 6502 / 6503」的段落做預覽
# 用法：
#   python test_tech_extract.py --query "NO.6500 產品內容" \
#     --data-dir "data/markdown" --top-k 5

import argparse, glob, os, re
from typing import List, Tuple

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def list_md_files(root: str) -> List[str]:
    pats = ("**/*.md", "**/*.markdown", "**/*.txt")
    out = []
    for p in pats:
        out.extend(glob.glob(os.path.join(root, p), recursive=True))
    return sorted(set(out))

def make_patterns() -> List[re.Pattern]:
    pats = [
        r"\bNO[.\-_ ]?6500\b",
        r"\bN0[.\-_ ]?6500\b",        # N+零 的誤打
        r"№\s*6500",                 # 記號
        r"\b6500AC\b",
        r"\b6502\b",
        r"\b6503\b",
        r"\b6500\b",
    ]
    return [re.compile(p, re.IGNORECASE) for p in pats]

def cut_section_around_headings(txt: str, hit_pos: int) -> str:
    """以命中點為中心，往上找最近的 #### 或 ### 或 ## 當作段落起點，
       往下到下一個同級/更高級標題為止。若找不到就取 ±1200 字。"""
    # 找到上一個 heading
    up_iter = list(re.finditer(r"^(#{2,6})\s.*$", txt, flags=re.MULTILINE))
    start = max(0, hit_pos - 1200)
    end = min(len(txt), hit_pos + 1200)
    for m in up_iter:
        if m.start() <= hit_pos:
            start = m.start()
    # 找到下一個 heading
    for m in up_iter:
        if m.start() > hit_pos:
            end = m.start()
            break
    sect = txt[start:end]
    # 簡單清理：連續空白、過長行
    sect = re.sub(r"[ \t]+\n", "\n", sect)
    sect = re.sub(r"\n{3,}", "\n\n", sect)
    return sect.strip()

def extract_hits_from_file(path: str, patterns: List[re.Pattern]) -> List[Tuple[int, str]]:
    txt = read_text(path)
    hits = []
    for pat in patterns:
        for m in pat.finditer(txt):
            pos = m.start()
            sect = cut_section_around_headings(txt, pos)
            hits.append((pos, sect))
    # 去重（以內容為鍵）
    uniq = []
    seen = set()
    for pos, s in hits:
        key = (path, s[:400])
        if key not in seen:
            seen.add(key)
            uniq.append((pos, s))
    return uniq

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    files = list_md_files(args.data_dir)
    if not files:
        print(f"❌ 找不到檔案：{args.data_dir}")
        return

    patterns = make_patterns()
    bucket = []
    for fp in files:
        try:
            hs = extract_hits_from_file(fp, patterns)
            if hs:
                bucket.append((fp, hs))
        except Exception as e:
            print(f"⚠️ 讀取失敗 {fp}: {e}")

    if not bucket:
        print("❌ 沒有任何命中。")
        return

    print(f"🎯 有 {len(bucket)} 個檔案命中，顯示前 {args.top_k}：\n")
    shown = 0
    for fp, hs in bucket:
        print(f"📄 {fp}")
        for idx, (pos, sect) in enumerate(hs[:2], 1):  # 每檔最多顯示 2 段
            print(f"  ├─ 片段#{idx} @ {pos}\n")
            # 把 HTML 標籤壓掉一部分，利於讀
            preview = re.sub(r"<[^>]+>", "", sect)
            print(preview.strip())
            print("\n  ─────────────────────────\n")
            shown += 1
            if shown >= args.top_k:
                print("✅ Done.")
                return
    print("✅ Done.")

if __name__ == "__main__":
    main()
