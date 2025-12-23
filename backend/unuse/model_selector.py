#!/usr/bin/env python3
"""
OpenAI 視覺模型選擇器
顯示可用的視覺模型並測試連接
"""
import os
from openai import OpenAI
from dotenv import load_dotenv

# 載入環境變數
from pathlib import Path

# 先嘗試載入上層目錄的 .env 文件
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

def test_vision_models():
    """測試可用的視覺模型"""
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY 未設置")
        return
    
    client = OpenAI(api_key=api_key)
    
    # 常見的視覺模型列表（按推薦順序）
    vision_models = [
        "gpt-4o",           # 最新的多模態模型
        "gpt-4o-mini",      # 較小的 4o 版本
        "gpt-4-turbo",      # GPT-4 Turbo with Vision
        "gpt-4.1",          # GPT-4.1（如果可用）
        "gpt-4.5",          # GPT-4.5（如果可用）
    ]
    
    print("🔍 測試可用的視覺模型...")
    print("=" * 50)
    
    working_models = []
    
    for model in vision_models:
        try:
            print(f"🧪 測試 {model}...", end=" ")
            
            # 嘗試列出模型或進行簡單的請求
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": "Hello"
                    }
                ],
                max_tokens=10
            )
            
            print("✅ 可用")
            working_models.append(model)
            
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "model_not_found" in error_msg:
                print("❌ 不可用")
            elif "401" in error_msg:
                print("❌ API 密鑰無效")
                break
            elif "429" in error_msg:
                print("⚠️  速率限制（但模型存在）")
                working_models.append(model)
            else:
                print(f"❓ 未知錯誤: {error_msg}")
    
    print("\n📋 可用的視覺模型:")
    print("=" * 30)
    
    if working_models:
        for i, model in enumerate(working_models, 1):
            print(f"{i}. {model}")
        
        print(f"\n💡 推薦使用: {working_models[0]}")
        
        # 保存推薦模型到環境變數文件
        try:
            # 使用正確的 .env 文件路徑
            env_file = Path(__file__).parent.parent / '.env'
            if not env_file.exists():
                env_file = Path('.env')  # 如果上層沒有，使用當前目錄
            
            with open(env_file, 'r') as f:
                env_content = f.read()
            
            if 'VISION_MODEL=' in env_content:
                # 更新現有的 VISION_MODEL
                lines = env_content.split('\n')
                for i, line in enumerate(lines):
                    if line.startswith('VISION_MODEL='):
                        lines[i] = f'VISION_MODEL={working_models[0]}'
                        break
                env_content = '\n'.join(lines)
            else:
                # 添加新的 VISION_MODEL
                env_content += f'\nVISION_MODEL={working_models[0]}\n'
            
            with open(env_file, 'w') as f:
                f.write(env_content)
            
            print(f"✅ 已將推薦模型保存到 {env_file}: VISION_MODEL={working_models[0]}")
            
        except Exception as e:
            print(f"⚠️  無法更新 .env 文件: {e}")
            print(f"💡 請手動在 .env 文件中添加: VISION_MODEL={working_models[0]}")
    
    else:
        print("❌ 沒有找到可用的視覺模型")
        print("💡 請檢查：")
        print("   1. API 密鑰是否正確")
        print("   2. 是否有足夠的配額")
        print("   3. 網路連接是否正常")

if __name__ == "__main__":
    test_vision_models()