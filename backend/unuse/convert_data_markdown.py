#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_data_markdown.py — Convert all DOCX/RTF under backend/data/markdown to Markdown.

Usage:
  # from backend/
  python convert_data_markdown.py
  # options
  python convert_data_markdown.py --wrap none --force --format gfm
  # or convert a custom path
  python convert_data_markdown.py --path ./data/markdown/subfolder
"""

import argparse
import os
import sys
import time
import pathlib
from typing import Iterable, List, Tuple

try:
    import pypandoc
except Exception as e:
    print("❌ pypandoc 未安裝：請先執行 `pip install pypandoc`", file=sys.stderr)
    sys.exit(1)

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BACKEND_ROOT / "data" / "markdown"

def has_pandoc() -> bool:
    try:
        _ = pypandoc.get_pandoc_version()
        return True
    except Exception:
        return False

def iter_targets(root: pathlib.Path) -> Iterable[pathlib.Path]:
    exts = {'.docx', '.rtf'}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            fp = pathlib.Path(dirpath) / fn
            if fp.suffix.lower() in exts:
                name = fp.name
                if name.startswith('~$') or name.startswith('.'):  # skip temp/hidden
                    continue
                yield fp

def needs_convert(src: pathlib.Path, dst: pathlib.Path, force: bool) -> bool:
    if force or not dst.exists():
        return True
    try:
        return src.stat().st_mtime > dst.stat().st_mtime
    except Exception:
        return True

def convert_one(src: pathlib.Path, to_fmt: str, wrap: str, force: bool) -> Tuple[bool, str]:
    dst = src.with_suffix('.md')
    if not needs_convert(src, dst, force):
        return True, f"⏩ 跳過（已最新） {src.relative_to(DEFAULT_DATA_DIR.parent)}"

    extra = []
    if wrap == "none":
        extra += ["--wrap=none"]
    elif wrap == "preserve":
        extra += ["--wrap=preserve"]
    # auto = pandoc default

    # Extract images for docx
    if src.suffix.lower() == ".docx":
        media_dir = src.parent / "media" / src.stem
        extra += [f"--extract-media={media_dir}"]

    try:
        pypandoc.convert_file(str(src), to=to_fmt, outputfile=str(dst), extra_args=extra)
        return True, f"✅ {src.relative_to(DEFAULT_DATA_DIR.parent)} → {dst.relative_to(DEFAULT_DATA_DIR.parent)}"
    except OSError as e:
        return False, f"❌ Pandoc 失敗（可能未安裝）：{src} :: {e}"
    except Exception as e:
        return False, f"❌ 轉換失敗：{src} :: {e}"

def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert DOCX/RTF to Markdown under data/markdown.")
    parser.add_argument("--path", default=str(DEFAULT_DATA_DIR), help="要轉換的根目錄（預設 backend/data/markdown）")
    parser.add_argument("--format", default="gfm", dest="fmt", help="輸出 Markdown 格式（預設 gfm）")
    parser.add_argument("--wrap", choices=["none", "auto", "preserve"], default="none", help="換行策略（預設 none）")
    parser.add_argument("--force", action="store_true", help="強制重轉，即使輸出較新也覆蓋")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.path).resolve()
    if not root.exists():
        print(f"⚠️ 指定路徑不存在：{root}", file=sys.stderr)
        return 1

    if not has_pandoc():
        print("❌ 系統未偵測到 pandoc。請先安裝：", file=sys.stderr)
        print("   Ubuntu: apt-get update && apt-get install -y pandoc", file=sys.stderr)
        print("   或參考：https://pandoc.org/installing.html", file=sys.stderr)
        return 2

    targets = list(iter_targets(root))
    if not targets:
        print(f"⚠️ 在 {root} 找不到任何 .docx / .rtf", file=sys.stderr)
        return 0

    print(f"🔎 目錄：{root}")
    print(f"📦 待轉換：{len(targets)}（format={args.fmt}, wrap={args.wrap}, force={args.force}）")

    ok, fail, skip = 0, 0, 0
    start = time.time()
    for i, src in enumerate(targets, 1):
        success, msg = convert_one(src, args.fmt, args.wrap, args.force)
        if success:
            if msg.startswith("⏩"):
                skip += 1
            else:
                ok += 1
        else:
            fail += 1
        print(f"[{i}/{len(targets)}] {msg}", flush=True)

    elapsed = time.time() - start
    print(f"—— 完成：成功 {ok}、跳過 {skip}、失敗 {fail}，耗時 {elapsed:.1f}s ——")
    return 0 if fail == 0 else 3

if __name__ == "__main__":
    sys.exit(main())
