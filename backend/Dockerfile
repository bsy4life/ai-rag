FROM python:3.10-slim
FROM tiangolo/uvicorn-gunicorn-fastapi:python3.9

WORKDIR /app

# 先複製 requirements.txt，這樣如果程式碼改動但套件沒變，就能用快取
COPY requirements.txt .

# 安裝 Python 套件（這層能快取）
RUN pip install --no-cache-dir -r requirements.txt

# 安裝系統套件（這層也能快取，放在 requirements 後是因為 pip 可能先 fail）
RUN apt-get update && apt-get install -y \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# 最後再複製你的所有程式碼，這一層變動最頻繁
COPY . .

# <--- 使用 Ollama Llama3免費本地模型=1  使用OpenAI=0 --->
ENV USE_FREE_MODEL=0

# 執行 uvicorn 伺服器
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
