#!/usr/bin/env python3
# 診斷業務資料解析問題

import os
from pathlib import Path
from core import BUSINESS_DATA_DIR, BusinessReportProcessor, get_qa_system

def diagnose_business_parsing():
    """診斷業務資料解析問題"""
    print("🔍 診斷業務資料解析問題...")
    
    if not os.path.exists(BUSINESS_DATA_DIR):
        print(f"❌ 業務資料目錄不存在：{BUSINESS_DATA_DIR}")
        return
    
    # 找到業務檔案
    txt_files = list(Path(BUSINESS_DATA_DIR).glob("**/*.txt"))
    print(f"📁 找到 {len(txt_files)} 個業務檔案")
    
    if not txt_files:
        print("❌ 沒有找到業務檔案")
        return
    
    # 分析第一個檔案
    test_file = txt_files[0]
    print(f"\n📄 分析檔案: {test_file.name}")
    print(f"📊 檔案大小: {test_file.stat().st_size:,} bytes")
    
    try:
        with open(test_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 統計原始標記
        doc_time_count = content.count('Doc_Time:')
        worker_count = content.count('Worker:')
        customer_count = content.count('Customer:')
        date_count = content.count('Date:')
        
        print(f"\n📈 原始統計:")
        print(f"   Doc_Time: {doc_time_count:,} 個")
        print(f"   Worker: {worker_count:,} 個")
        print(f"   Customer: {customer_count:,} 個")
        print(f"   Date: {date_count:,} 個")
        
        # 檢查2025年記錄
        lines_2025 = [line for line in content.split('\n') if '2025' in line]
        print(f"   包含 2025: {len(lines_2025)} 行")
        
        # 取樣顯示2025年記錄
        print(f"\n📝 2025年記錄樣本（前10行）:")
        for i, line in enumerate(lines_2025[:10]):
            print(f"   {i+1}. {line.strip()}")
        
        # 測試解析器
        print(f"\n🧪 測試解析器...")
        processor = BusinessReportProcessor()
        
        # 取一小部分測試
        test_content = '\n'.join(content.split('\n')[:10000])  # 前10000行
        docs = processor.parse_business_report(test_content)
        
        print(f"✅ 測試解析結果: {len(docs)} 個文檔")
        
        if docs:
            # 統計解析結果中的2025年記錄
            docs_2025 = [doc for doc in docs if '2025' in doc.metadata.get('date', '')]
            print(f"   其中2025年記錄: {len(docs_2025)} 個")
            
            # 顯示樣本
            print(f"\n📋 解析後的2025年記錄樣本:")
            for i, doc in enumerate(docs_2025[:5]):
                print(f"   {i+1}. 日期: {doc.metadata.get('date')}")
                print(f"      業務人員: {doc.metadata.get('worker')}")
                print(f"      客戶: {doc.metadata.get('customer')}")
                print(f"      活動: {doc.metadata.get('content_type')}")
                print()
        
    except Exception as e:
        print(f"❌ 分析失敗: {e}")
        import traceback
        traceback.print_exc()

def check_vectordb_status():
    """檢查向量庫狀態"""
    print("\n🔍 檢查向量庫狀態...")
    
    qa_system = get_qa_system()
    if not qa_system:
        print("❌ QA系統未初始化")
        return
    
    if qa_system.business_vectordb:
        try:
            # 嘗試檢索2025年記錄
            retriever = qa_system.business_retriever
            if retriever:
                docs = retriever.get_relevant_documents("2025年 業務拜訪")
                print(f"📊 檢索到的2025年相關文檔: {len(docs)} 個")
                
                for i, doc in enumerate(docs[:3]):
                    print(f"   文檔{i+1}: {doc.page_content[:100]}...")
                    print(f"   來源: {doc.metadata.get('source', 'Unknown')}")
                    print()
            else:
                print("❌ 業務檢索器未初始化")
        except Exception as e:
            print(f"❌ 檢索測試失敗: {e}")
    else:
        print("❌ 業務向量庫未建立")

def suggest_fixes():
    """建議修正方案"""
    print("\n💡 建議修正方案:")
    print("1. 🔧 調整檢索參數 - 增加檢索數量")
    print("2. 📊 重新解析業務資料 - 確保所有記錄都被正確解析")
    print("3. 🔄 重建向量庫 - 使用更大的批次大小")
    print("4. ⚙️ 修改查詢策略 - 使用更廣泛的搜尋詞")

if __name__ == "__main__":
    print("🚀 SanShin AI 業務資料診斷工具")
    
    # 1. 診斷解析
    diagnose_business_parsing()
    
    # 2. 檢查向量庫
    check_vectordb_status()
    
    # 3. 建議修正
    suggest_fixes()
    
    print("\n✅ 診斷完成")