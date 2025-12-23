#!/usr/bin/env python3
"""
PDF 轉 RAG 知識庫腳本
將 PDF 文件通過 OpenAI Vision API 轉換為文字，並直接輸出到 RAG 系統的知識庫目錄
"""
import os
import sys
from pathlib import Path

# 添加當前目錄到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 嘗試載入 .env 文件
try:
    from dotenv import load_dotenv
    # 先嘗試載入上層目錄的 .env 文件
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ 已載入環境變數: {env_path}")
    else:
        # 如果上層沒有，嘗試當前目錄
        load_dotenv()
except ImportError:
    print("💡 提示: 安裝 python-dotenv 可以使用 .env 文件")
    print("   pip install python-dotenv")

def main():
    # 檢查環境
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ 請設置 OPENAI_API_KEY 環境變數")
        print("   方法 1: export OPENAI_API_KEY='your-api-key-here'")
        print("   方法 2: 在專案根目錄創建 .env 文件並添加:")
        print("          OPENAI_API_KEY=your-api-key-here")
        print("   方法 3: 添加到 ~/.bashrc 或 ~/.zshrc")
        return
    
    try:
        # 導入整合處理器
        from integrated_pdf_processor import IntegratedPDFProcessor
        
        # 獲取當前目錄 (backend 目錄)
        base_dir = Path(__file__).parent
        
        print("🚀 PDF 轉 RAG 知識庫工具")
        print("支援中文、日文、英文混合文檔")
        print("=" * 40)
        
        # 初始化處理器
        vision_model = os.getenv("VISION_MODEL", "gpt-4o")  # 從環境變數讀取，默認 gpt-4o
        processor = IntegratedPDFProcessor(api_key, str(base_dir), vision_model)
        
        # 檢查 PDF 目錄
        pdf_dir = processor.input_dir
        if not pdf_dir.exists():
            pdf_dir.mkdir(parents=True)
            print(f"📁 已創建 PDF 輸入目錄: {pdf_dir}")
            print(f"💡 請將 PDF 文件放入此目錄後重新運行")
            return
        
        pdf_files = list(pdf_dir.glob("*.pdf"))
        if not pdf_files:
            print(f"📁 PDF 輸入目錄: {pdf_dir}")
            print(f"❌ 目錄中沒有 PDF 文件")
            print(f"💡 請將 PDF 文件放入此目錄後重新運行")
            return
        
        print(f"📁 PDF 輸入目錄: {pdf_dir}")
        print(f"📁 文字輸出目錄: {processor.ocr_output_dir}")
        print(f"📄 找到 {len(pdf_files)} 個 PDF 文件:")
        
        for pdf_file in pdf_files:
            file_size = pdf_file.stat().st_size / 1024 / 1024  # MB
            print(f"   - {pdf_file.name} ({file_size:.1f} MB)")
        
        # 檢查文檔語言特徵
        has_japanese = any("japan" in pdf.name.lower() or "jp" in pdf.name.lower() or 
                          "日" in pdf.name for pdf in pdf_files)
        
        if has_japanese:
            print(f"\n🈳 檢測到可能包含日文的文檔，OCR 會特別處理多語言內容")
        
        # 詢問用戶是否繼續
        response = input(f"\n🤔 是否開始處理這些 PDF 文件? (y/N): ").lower()
        if response != 'y':
            print("❌ 用戶取消操作")
            return
        
        # 開始處理
        print("\n🔄 開始處理 PDF 文件...")
        result = processor.process_all_pdfs()
        
        if result["success"] > 0:
            print(f"\n🎉 OCR 處理成功!")
            print(f"✅ 已處理 {result['success']}/{result['total']} 個 PDF 文件")
            print(f"📂 文字檔案已保存到: {result['output_dir']}")
            
            # 嘗試重建知識庫
            try:
                from core import reload_qa_chain
                print(f"\n🔄 正在重建 RAG 知識庫...")
                reload_qa_chain()
                print(f"✅ 知識庫重建完成!")
                print(f"💡 現在可以重啟 app.py 開始使用問答系統")
                
                if has_japanese:
                    print(f"🈳 日文產品資訊已包含中文翻譯，便於搜索和理解")
                
            except Exception as e:
                print(f"\n⚠️  自動重建知識庫失敗: {e}")
                print(f"💡 請手動重啟 app.py 服務來重建知識庫")
        else:
            print(f"\n❌ 處理失敗，請檢查錯誤信息")
    
    except ImportError as e:
        print(f"❌ 導入錯誤: {e}")
        print(f"💡 請確保已安裝必要的依賴:")
        print(f"   pip install openai PyMuPDF python-dotenv")
    except Exception as e:
        print(f"❌ 運行錯誤: {e}")

if __name__ == "__main__":
    main()