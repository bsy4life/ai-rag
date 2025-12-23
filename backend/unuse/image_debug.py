# local_image_debug.py - 本地版本的圖片調試工具
import os
import re
from pathlib import Path
from collections import defaultdict

def analyze_markdown_images(data_dir: str):
    """分析 Markdown 文件中的圖片引用"""
    
    results = {
        'total_files': 0,
        'total_image_refs': 0,
        'by_pattern': defaultdict(int),
        'by_file': defaultdict(list),
        'unique_images': set(),
        'missing_images': [],
        'found_images': []
    }
    
    # 不同的圖片匹配模式
    patterns = {
        'markdown_basic': r'!\[([^\]]*)\]\(([^)]+?)\)',
        'markdown_with_title': r'!\[([^\]]*)\]\(([^)]+?)(?:\s+"([^"]*)")?\)',
        'html_img_basic': r'<img[^>]+src=[\'"]+([^>\'"]+)[\'"]+[^>]*>',
        'html_img_with_alt': r'<img[^>]+src=[\'"]+([^>\'"]+)[\'"]+[^>]*(?:alt=[\'"]+([^>\'"]*?)[\'"]+)?[^>]*>',
        'html_img_with_style': r'<img[^>]+src=[\'"]+([^>\'"]+)[\'"]+[^>]*style=[^>]*>',
    }
    
    data_path = Path(data_dir)
    media_dir = data_path / "media"
    
    print(f"🔍 分析目錄: {data_dir}")
    print(f"🖼️ 媒體目錄: {media_dir}")
    print(f"📁 資料目錄存在: {'是' if data_path.exists() else '否'}")
    print(f"📁 媒體目錄存在: {'是' if media_dir.exists() else '否'}")
    
    if not data_path.exists():
        print(f"❌ 資料目錄不存在: {data_dir}")
        return results
    
    # 遍歷所有 Markdown 文件
    md_files = list(data_path.rglob("*.md"))
    print(f"📄 找到 Markdown 文件: {len(md_files)} 個")
    
    for md_file in md_files:
        results['total_files'] += 1
        print(f"\n📄 處理文件: {md_file.name}")
        
        try:
            with open(md_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            print(f"   ❌ 讀取失敗: {e}")
            continue
        
        file_images = []
        
        # 測試每種模式
        for pattern_name, pattern in patterns.items():
            matches = list(re.finditer(pattern, content, re.IGNORECASE))
            pattern_count = len(matches)
            
            if pattern_count > 0:
                print(f"   📊 {pattern_name}: {pattern_count} 個匹配")
                results['by_pattern'][pattern_name] += pattern_count
                
                for match in matches:
                    if 'src=' in match.group(0):  # HTML
                        img_path = match.group(1)
                    else:  # Markdown
                        img_path = match.group(2) if len(match.groups()) > 1 else match.group(1)
                    
                    file_images.append({
                        'pattern': pattern_name,
                        'path': img_path,
                        'match_text': match.group(0)[:100] + '...' if len(match.group(0)) > 100 else match.group(0)
                    })
                    
                    results['unique_images'].add(img_path)
        
        results['by_file'][md_file.name] = file_images
        results['total_image_refs'] += len(file_images)
        
        print(f"   📊 文件總圖片引用: {len(file_images)}")
    
    # 檢查圖片實際存在情況
    print(f"\n🔍 檢查圖片實際存在情況...")
    for img_path in results['unique_images']:
        if _check_image_exists(img_path, media_dir, data_path):
            results['found_images'].append(img_path)
        else:
            results['missing_images'].append(img_path)
    
    return results

def _check_image_exists(img_path: str, media_base_dir: Path, data_dir: Path) -> bool:
    """檢查圖片是否存在"""
    clean_path = img_path.strip('\'"')
    
    # 處理絕對路徑
    if os.path.isabs(clean_path):
        path_parts = Path(clean_path).parts
        media_indices = [i for i, part in enumerate(path_parts) if part == 'media']
        
        if len(media_indices) >= 2:
            doc_folder_idx = media_indices[0] + 1
            img_name_idx = media_indices[1] + 1
            
            if doc_folder_idx < len(path_parts) and img_name_idx < len(path_parts):
                extracted_doc_name = path_parts[doc_folder_idx]
                img_name = path_parts[img_name_idx]
                
                local_path = media_base_dir / extracted_doc_name / "media" / img_name
                return local_path.exists()
    
    # 處理相對路徑
    img_name = Path(clean_path.lstrip('./')).name
    
    # 在所有可能的位置搜尋
    if media_base_dir.exists():
        for root, dirs, files in os.walk(media_base_dir):
            if img_name in files:
                return True
    
    return False

def print_analysis_report(results: dict):
    """打印分析報告"""
    print(f"\n" + "="*60)
    print(f"📊 圖片分析報告")
    print(f"="*60)
    
    print(f"📄 總文件數: {results['total_files']}")
    print(f"🖼️ 總圖片引用數: {results['total_image_refs']}")
    print(f"🔗 唯一圖片路徑數: {len(results['unique_images'])}")
    print(f"✅ 存在的圖片: {len(results['found_images'])}")
    print(f"❌ 缺失的圖片: {len(results['missing_images'])}")
    
    print(f"\n📊 按模式分組:")
    for pattern, count in results['by_pattern'].items():
        print(f"   {pattern}: {count}")
    
    print(f"\n📄 按文件分組:")
    for filename, images in results['by_file'].items():
        if images:  # 只顯示有圖片的文件
            print(f"   {filename}: {len(images)} 張圖片")
            # 顯示前幾個圖片路徑
            for img in images[:3]:
                print(f"      - {img['path']} ({img['pattern']})")
    
    if results['missing_images']:
        print(f"\n❌ 缺失的圖片範例（前10個）:")
        for img_path in results['missing_images'][:10]:
            print(f"   {img_path}")
    
    if results['found_images']:
        print(f"\n✅ 存在的圖片範例（前5個）:")
        for img_path in results['found_images'][:5]:
            print(f"   {img_path}")

def analyze_actual_media_directory(data_dir: str):
    """分析實際的媒體目錄結構"""
    media_dir = Path(data_dir) / "media"
    
    print(f"\n📁 實際媒體目錄分析:")
    print(f"媒體目錄路徑: {media_dir}")
    
    if not media_dir.exists():
        print(f"❌ 媒體目錄不存在")
        return
    
    print(f"✅ 媒體目錄存在")
    
    total_actual_images = 0
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}
    
    for root, dirs, files in os.walk(media_dir):
        image_files = [f for f in files if Path(f).suffix.lower() in image_extensions]
        if image_files:
            rel_path = Path(root).relative_to(media_dir)
            print(f"   📂 {rel_path}: {len(image_files)} 張圖片")
            total_actual_images += len(image_files)
            
            # 顯示前幾個檔案名
            for img_file in image_files[:3]:
                print(f"      - {img_file}")
            if len(image_files) > 3:
                print(f"      - ... 還有 {len(image_files) - 3} 張")
    
    print(f"\n🖼️ 實際存在的圖片檔案總數: {total_actual_images}")
    
    return total_actual_images

def main():
    """主函數"""
    # 本地路徑 - 根據您的實際路徑調整
    possible_paths = [
        "data/markdown",  # 相對路徑
        "./data/markdown",  # 當前目錄下
        "../data/markdown",  # 上一層目錄
        os.path.expanduser("~/ai-rag/backend/data/markdown"),  # 完整路徑
    ]
    
    data_dir = None
    for path in possible_paths:
        if Path(path).exists():
            data_dir = str(Path(path).resolve())
            print(f"✅ 找到資料目錄: {data_dir}")
            break
    
    if not data_dir:
        print(f"❌ 找不到資料目錄，請手動指定:")
        print(f"可能的位置:")
        for path in possible_paths:
            print(f"  - {Path(path).resolve()}")
        return
    
    print(f"🚀 開始圖片分析...")
    
    # 分析 Markdown 中的圖片引用
    results = analyze_markdown_images(data_dir)
    print_analysis_report(results)
    
    # 分析實際的媒體目錄
    actual_count = analyze_actual_media_directory(data_dir)
    
    # 總結
    print(f"\n" + "="*60)
    print(f"📋 總結比較")
    print(f"="*60)
    print(f"Markdown 中引用的圖片: {results['total_image_refs']}")
    print(f"唯一圖片路徑: {len(results['unique_images'])}")
    print(f"實際存在的圖片檔案: {actual_count}")
    print(f"找到的圖片: {len(results['found_images'])}")
    print(f"缺失的圖片: {len(results['missing_images'])}")

if __name__ == "__main__":
    main()