#!/usr/bin/env python3
"""
整合 PDF 處理器
使用 OpenAI Vision API 處理 PDF 文件並轉換為文字
"""
import os
import json
import base64
import time
from pathlib import Path
from typing import Dict, List, Any
import fitz  # PyMuPDF
from openai import OpenAI

class IntegratedPDFProcessor:
    def __init__(self, api_key: str, base_dir: str, vision_model: str = "gpt-4o"):
        """
        初始化 PDF 處理器
        
        Args:
            api_key: OpenAI API 密鑰
            base_dir: 基礎目錄路徑
            vision_model: 視覺模型名稱 (gpt-4o, gpt-4-turbo, gpt-4.1, etc.)
        """
        self.client = OpenAI(api_key=api_key)
        self.base_dir = Path(base_dir)
        self.vision_model = vision_model
        
        print(f"🤖 使用視覺模型: {vision_model}")
        
        # 設置目錄結構
        self.input_dir = self.base_dir / "data" / "pdfs"  
        self.ocr_output_dir = self.base_dir / "data" / "ocr_txt"
        
        # 確保目錄存在
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.ocr_output_dir.mkdir(parents=True, exist_ok=True)
    
    def pdf_to_images(self, pdf_path: Path) -> List[bytes]:
        """
        將 PDF 轉換為圖片
        
        Args:
            pdf_path: PDF 文件路徑
            
        Returns:
            圖片數據列表
        """
        images = []
        
        try:
            # 打開 PDF
            doc = fitz.open(pdf_path)
            
            for page_num in range(doc.page_count):
                page = doc[page_num]
                
                # 設置渲染參數
                matrix = fitz.Matrix(2.0, 2.0)  # 2倍縮放，提高圖片質量
                pix = page.get_pixmap(matrix=matrix)
                
                # 轉換為 PNG 格式的字節數據
                img_data = pix.tobytes("png")
                images.append(img_data)
                
                print(f"  ✓ 已轉換第 {page_num + 1} 頁")
            
            doc.close()
            
        except Exception as e:
            print(f"  ❌ PDF 轉圖片失敗: {e}")
            
        return images
    
    def image_to_base64(self, image_data: bytes) -> str:
        """
        將圖片數據轉換為 base64 字符串
        
        Args:
            image_data: 圖片字節數據
            
        Returns:
            base64 字符串
        """
        return base64.b64encode(image_data).decode('utf-8')
    
    def ocr_image_with_openai(self, image_data: bytes, page_num: int) -> str:
        """
        使用 OpenAI Vision API 進行 OCR
        
        Args:
            image_data: 圖片數據
            page_num: 頁碼
            
        Returns:
            識別的文字
        """
        try:
            # 轉換為 base64
            base64_image = self.image_to_base64(image_data)
            
            # 調用 OpenAI Vision API
            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "請提取這個圖片中的所有文字內容，保持原有的格式和結構。如果有表格，請保持表格格式。圖片中可能包含中文、日文或英文文字，請準確識別並保留原文。如果是日文產品型錄，請保留日文原文並在括號內提供中文翻譯。請用繁體中文回應。"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=4096
            )
            
            text = response.choices[0].message.content
            print(f"  ✓ 第 {page_num + 1} 頁 OCR 完成")
            
            # 添加延遲避免 API 限制
            time.sleep(1)
            
            return text
            
        except Exception as e:
            print(f"  ❌ 第 {page_num + 1} 頁 OCR 失敗: {e}")
            return f"[第 {page_num + 1} 頁 OCR 失敗: {e}]"
    
    def process_pdf(self, pdf_path: Path) -> bool:
        """
        處理單個 PDF 文件
        
        Args:
            pdf_path: PDF 文件路徑
            
        Returns:
            是否處理成功
        """
        print(f"\n📄 處理文件: {pdf_path.name}")
        
        try:
            # 1. PDF 轉圖片
            print(f"  🔄 正在轉換 PDF 為圖片...")
            images = self.pdf_to_images(pdf_path)
            
            if not images:
                print(f"  ❌ PDF 轉圖片失敗")
                return False
            
            # 2. OCR 處理
            print(f"  🔄 正在進行 OCR 處理... (共 {len(images)} 頁)")
            all_text = []
            
            for i, image_data in enumerate(images):
                text = self.ocr_image_with_openai(image_data, i)
                all_text.append(f"=== 第 {i + 1} 頁 ===\n{text}\n")
            
            # 3. 保存文字檔案
            output_path = self.ocr_output_dir / f"{pdf_path.stem}.txt"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"文件: {pdf_path.name}\n")
                f.write(f"處理時間: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 50 + "\n\n")
                f.write('\n'.join(all_text))
            
            print(f"  ✅ 文字檔案已保存: {output_path}")
            return True
            
        except Exception as e:
            print(f"  ❌ 處理失敗: {e}")
            return False
    
    def process_all_pdfs(self) -> Dict[str, Any]:
        """
        處理所有 PDF 文件
        
        Returns:
            處理結果統計
        """
        pdf_files = list(self.input_dir.glob("*.pdf"))
        
        if not pdf_files:
            return {
                "total": 0,
                "success": 0,
                "failed": 0,
                "output_dir": str(self.ocr_output_dir)
            }
        
        success_count = 0
        failed_count = 0
        
        for pdf_file in pdf_files:
            if self.process_pdf(pdf_file):
                success_count += 1
            else:
                failed_count += 1
        
        return {
            "total": len(pdf_files),
            "success": success_count,
            "failed": failed_count,
            "output_dir": str(self.ocr_output_dir)
        }
    
    def get_status(self) -> Dict[str, Any]:
        """
        獲取處理器狀態
        
        Returns:
            狀態資訊
        """
        pdf_files = list(self.input_dir.glob("*.pdf"))
        txt_files = list(self.ocr_output_dir.glob("*.txt"))
        
        return {
            "input_dir": str(self.input_dir),
            "output_dir": str(self.ocr_output_dir),
            "pdf_count": len(pdf_files),
            "txt_count": len(txt_files),
            "pdf_files": [f.name for f in pdf_files],
            "txt_files": [f.name for f in txt_files]
        }