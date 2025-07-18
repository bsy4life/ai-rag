FROM tiangolo/uvicorn-gunicorn-fastapi:python3.9

# 建議加語言
ENV LANG C.UTF-8

WORKDIR /app

# 安裝系統套件（合併 && 一次清理，減少 image 層與大小）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# 先複製 requirements.txt，這樣未來只有 requirements.txt 變才會重新 pip install
COPY requirements.txt .

# 安裝 Python 套件（建議升級 pip，有些新版 whl 較快且體積小）
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 再複製 app 其餘檔案
COPY . .

# <--- 使用 Ollama Llama3免費本地模型=1  使用OpenAI=0 --->
ENV USE_FREE_MODEL=0
# 禁用 huggingface tokenizers 警告
ENV TOKENIZERS_PARALLELISM=false

# 執行 uvicorn 伺服器
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
