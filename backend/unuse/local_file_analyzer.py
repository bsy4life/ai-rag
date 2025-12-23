#!/usr/bin/env python3
"""
本地 OCR 檔案分析工具
分析 data/ocr_txt 中的檔案，評估是否需要清理
"""
import os
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple
from collections import Counter

class LocalFileAnalyzer:
    def __init__(self, data_dir: str = "/home/aiuser/ai-rag/backend/data/ocr_txt"):
        """
        初始化分析器
        
        Args:
            data_dir: 資料目錄路徑
        """
        self.data_dir = Path(data_dir)
        self.report_dir = self.data_dir.parent / "analysis_reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        
        # 雜訊模式
        self.noise_patterns = {
            'image_refs': r'!\[.*?\]\(.*?\)',
            'width_height': r'\{(?:width|height)=.*?\}',
            'format_marks': r'\[\.underline\]|\[\.bold\]|\[\.italic\]',
            'quote_marks': r'^>\s+',
            'empty_brackets': r'\[\s*\]|\(\s*\)',
            'media_paths': r'media/image\d+\.\w+',
            'excessive_spaces': r' {3,}',
            'excessive_newlines': r'\n{4,}'
        }
        
        # 有用內容模式
        self.useful_patterns = {
            'model_numbers': r'LES[A-Z]*\d+|LECP\d+|LEC[A-Z]*\d+',
            'specifications': r'\d+(?:\.\d+)?\s*(?:mm|kg|MPa|Pa|°C|℃|N|W|V|A)',
            'part_numbers': r'[A-Z]{2,}\d{2,}',
            'tables': r'(?:\|.*\|.*\n)+',
            'japanese_text': r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]+',
            'technical_terms': r'(?:速度|精度|行程|負載|壓力|溫度|電壓|電流|功率)'
        }
    
    def analyze_file(self, file_path: Path) -> Dict:
        """
        分析單個檔案
        
        Args:
            file_path: 檔案路徑
            
        Returns:
            分析結果字典
        """
        try:
            # 嘗試不同編碼讀取
            content = None
            for encoding in ['utf-8', 'big5', 'gb2312', 'shift_jis', 'cp950']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                # 最後嘗試忽略錯誤
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            
            # 基本統計
            stats = {
                'filename': file_path.name,
                'total_chars': len(content),
                'total_lines': content.count('\n'),
                'file_size_kb': file_path.stat().st_size / 1024,
                'encoding_detected': 'utf-8'  # 簡化顯示
            }
            
            # 計算雜訊
            noise_counts = {}
            total_noise_chars = 0
            for name, pattern in self.noise_patterns.items():
                matches = re.findall(pattern, content, re.MULTILINE)
                noise_counts[name] = len(matches)
                total_noise_chars += sum(len(m) for m in matches)
            
            # 計算有用內容
            useful_counts = {}
            for name, pattern in self.useful_patterns.items():
                matches = re.findall(pattern, content)
                useful_counts[name] = len(matches)
            
            # 計算比例
            noise_ratio = total_noise_chars / len(content) if len(content) > 0 else 0
            
            # 提取範例內容
            clean_sample = re.sub(r'!\[.*?\]\(.*?\)', '', content[:500])
            clean_sample = re.sub(r'\{.*?\}', '', clean_sample)
            clean_sample = re.sub(r'\n{3,}', '\n\n', clean_sample)
            
            return {
                'stats': stats,
                'noise': noise_counts,
                'useful': useful_counts,
                'noise_ratio': noise_ratio,
                'total_noise_chars': total_noise_chars,
                'sample_original': content[:500],
                'sample_cleaned': clean_sample,
                'recommendation': self.get_recommendation(noise_ratio, useful_counts)
            }
            
        except Exception as e:
            return {
                'stats': {'filename': file_path.name, 'error': str(e)},
                'noise': {},
                'useful': {},
                'noise_ratio': 0,
                'recommendation': 'ERROR'
            }
    
    def get_recommendation(self, noise_ratio: float, useful_counts: Dict) -> str:
        """
        根據分析結果給出建議
        
        Args:
            noise_ratio: 雜訊比例
            useful_counts: 有用內容統計
            
        Returns:
            建議字串
        """
        # 計算有用內容分數
        useful_score = (
            useful_counts.get('model_numbers', 0) * 10 +
            useful_counts.get('specifications', 0) * 5 +
            useful_counts.get('tables', 0) * 20 +
            useful_counts.get('technical_terms', 0) * 3
        )
        
        if noise_ratio > 0.3:
            return "HEAVY_CLEAN"  # 需要重度清理
        elif noise_ratio > 0.1:
            return "LIGHT_CLEAN"  # 需要輕度清理
        elif useful_score < 10:
            return "LOW_VALUE"    # 內容價值低
        else:
            return "DIRECT_USE"   # 可直接使用
    
    def analyze_all_files(self) -> Dict:
        """
        分析所有檔案
        
        Returns:
            總體分析結果
        """
        # 找出所有文字檔案
        text_files = []
        for ext in ['*.txt', '*.docx', '*.doc']:
            text_files.extend(self.data_dir.glob(ext))
        
        if not text_files:
            print(f"⚠️ 在 {self.data_dir} 中沒有找到檔案")
            return {}
        
        print(f"📂 分析目錄: {self.data_dir}")
        print(f"📄 找到 {len(text_files)} 個檔案")
        print("=" * 60)
        
        # 分析每個檔案
        all_results = []
        recommendations_count = Counter()
        
        for i, file_path in enumerate(text_files, 1):
            print(f"\n[{i}/{len(text_files)}] 分析: {file_path.name}")
            
            result = self.analyze_file(file_path)
            all_results.append(result)
            recommendations_count[result['recommendation']] += 1
            
            # 顯示簡要結果
            if 'error' not in result['stats']:
                print(f"  📊 大小: {result['stats']['file_size_kb']:.1f} KB")
                print(f"  📝 字元: {result['stats']['total_chars']:,}")
                print(f"  🗑️ 雜訊: {result['noise_ratio']:.1%}")
                print(f"  💡 建議: {result['recommendation']}")
                
                # 顯示發現的有用內容
                if result['useful']['model_numbers'] > 0:
                    print(f"  ✓ 發現 {result['useful']['model_numbers']} 個型號")
                if result['useful']['specifications'] > 0:
                    print(f"  ✓ 發現 {result['useful']['specifications']} 個規格數據")
                if result['useful']['tables'] > 0:
                    print(f"  ✓ 發現表格結構")
            else:
                print(f"  ❌ 錯誤: {result['stats']['error']}")
        
        # 生成總結報告
        summary = self.generate_summary(all_results, recommendations_count)
        
        # 保存詳細報告
        report_path = self.report_dir / "analysis_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'summary': summary,
                'details': all_results
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n{'='*60}")
        print("📊 總體分析結果")
        print(f"{'='*60}")
        print(f"檔案總數: {summary['total_files']}")
        print(f"總大小: {summary['total_size_mb']:.1f} MB")
        print(f"平均雜訊: {summary['average_noise_ratio']:.1%}")
        print(f"\n建議分布:")
        for rec, count in summary['recommendations'].items():
            print(f"  {rec}: {count} 個檔案")
        
        print(f"\n💡 總體建議:")
        for suggestion in summary['suggestions']:
            print(f"  • {suggestion}")
        
        print(f"\n📁 詳細報告已保存: {report_path}")
        
        return summary
    
    def generate_summary(self, results: List[Dict], rec_count: Counter) -> Dict:
        """
        生成總結報告
        
        Args:
            results: 所有檔案的分析結果
            rec_count: 建議統計
            
        Returns:
            總結字典
        """
        total_size = sum(r['stats'].get('file_size_kb', 0) for r in results)
        noise_ratios = [r['noise_ratio'] for r in results if r['noise_ratio'] > 0]
        
        summary = {
            'total_files': len(results),
            'total_size_mb': total_size / 1024,
            'average_noise_ratio': sum(noise_ratios) / len(noise_ratios) if noise_ratios else 0,
            'recommendations': dict(rec_count),
            'suggestions': []
        }
        
        # 生成建議
        if rec_count['HEAVY_CLEAN'] > len(results) * 0.3:
            summary['suggestions'].append("超過 30% 的檔案需要重度清理，建議使用清理工具處理所有檔案")
        elif rec_count['DIRECT_USE'] > len(results) * 0.7:
            summary['suggestions'].append("大部分檔案品質良好，可以直接使用")
        else:
            summary['suggestions'].append("檔案品質參差不齊，建議對需要清理的檔案個別處理")
        
        if summary['average_noise_ratio'] > 0.2:
            summary['suggestions'].append("平均雜訊比例偏高，清理後可提升搜索準確度")
        
        # 檢查是否有技術文檔
        total_specs = sum(r['useful'].get('specifications', 0) for r in results)
        if total_specs > 100:
            summary['suggestions'].append(f"發現大量技術規格數據 ({total_specs} 個)，這些是重要內容，清理時要小心保留")
        
        return summary
    
    def clean_files(self, level: str = "light") -> None:
        """
        根據分析結果清理檔案
        
        Args:
            level: 清理等級 ("light", "heavy", "auto")
        """
        print(f"\n🧹 開始清理檔案 (等級: {level})")
        
        clean_dir = self.data_dir.parent / "ocr_txt_cleaned"
        clean_dir.mkdir(parents=True, exist_ok=True)
        
        text_files = list(self.data_dir.glob("*.txt"))
        
        for file_path in text_files:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            if level == "auto":
                # 自動判斷清理等級
                result = self.analyze_file(file_path)
                if result['recommendation'] == "DIRECT_USE":
                    cleaned = content
                elif result['recommendation'] == "HEAVY_CLEAN":
                    cleaned = self.heavy_clean(content)
                else:
                    cleaned = self.light_clean(content)
            elif level == "heavy":
                cleaned = self.heavy_clean(content)
            else:
                cleaned = self.light_clean(content)
            
            # 保存清理後的檔案
            output_path = clean_dir / file_path.name
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            
            print(f"  ✓ {file_path.name} -> {output_path}")
        
        print(f"\n✅ 清理完成！檔案已保存到: {clean_dir}")
    
    def light_clean(self, text: str) -> str:
        """輕度清理：只移除明顯的雜訊"""
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)  # 圖片引用
        text = re.sub(r'\{(?:width|height)=.*?\}', '', text)  # 尺寸標記
        text = re.sub(r'\n{4,}', '\n\n\n', text)  # 過多換行
        text = re.sub(r' {3,}', '  ', text)  # 過多空格
        return text.strip()
    
    def heavy_clean(self, text: str) -> str:
        """重度清理：移除所有雜訊"""
        # 先做輕度清理
        text = self.light_clean(text)
        # 額外清理
        text = re.sub(r'\[\.underline\]|\[\.bold\]|\[\.italic\]', '', text)
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'media/image\d+\.\w+', '', text)
        text = re.sub(r'\[\s*\]|\(\s*\)', '', text)
        return text.strip()

def main():
    """主程式"""
    import sys
    
    # 檢查參數
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        data_dir = "/home/aiuser/ai-rag/backend/data/ocr_txt"
    
    analyzer = LocalFileAnalyzer(data_dir)
    
    # 分析檔案
    summary = analyzer.analyze_all_files()
    
    if not summary:
        return
    
    # 詢問是否要清理
    print("\n" + "="*60)
    print("是否要清理檔案？")
    print("1. 不清理 (分析完成)")
    print("2. 輕度清理 (只移除圖片引用和格式標記)")
    print("3. 重度清理 (移除所有雜訊)")
    print("4. 自動清理 (根據分析結果自動選擇)")
    
    choice = input("\n請選擇 (1-4): ").strip()
    
    if choice == "2":
        analyzer.clean_files("light")
    elif choice == "3":
        analyzer.clean_files("heavy")
    elif choice == "4":
        analyzer.clean_files("auto")
    else:
        print("✅ 分析完成，未進行清理")

if __name__ == "__main__":
    main()