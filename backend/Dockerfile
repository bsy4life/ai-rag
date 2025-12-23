FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴 + Tesseract OCR + PDF/DOCX 轉換工具
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libmagic1 \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    poppler-utils \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# 複製 requirements 並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式
COPY . .

# 建立必要目錄
RUN mkdir -p /app/data/personal_kb /app/temp /app/cache

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
