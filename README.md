# 🧠 AI-RAG 聊天助理系統

一個基於 FastAPI + PostgreSQL + LangChain 的企業內部文件問答系統，支援文件向量化、自動 Watchdog 更新、PWA 安裝體驗。

![登入畫面](frontend/sanshin_logo.png)

## 🚀 功能特點

- 📁 自動載入 `backend/data/` 中的 PDF / TXT
- 🤖 支援 ChatGPT 文本問答與向量查詢
- 🔎 LangChain + Chroma 向量庫
- 🛡 JWT 驗證 + 帳號管理介面
- 📲 支援 PWA（桌面/手機安裝）
- 🔁 Watchdog 即時監控資料夾

## 📦 技術架構

- FastAPI + Uvicorn
- PostgreSQL 資料庫
- Chroma 向量資料庫
- LangChain 文本查詢引擎
- Docker + Nginx + HTTPS（自簽）

## 📂 專案結構

```
ai-rag/
├── backend/
│   ├── app.py              # FastAPI 主程式
│   ├── core.py             # 向量庫處理邏輯
│   ├── data/               # 放入 PDF/TXT 檔案
│   ├── vectorstore/        # Chroma 向量儲存
│   └── frontend/           # 靜態頁面 + JS + PWA
├── docker-compose.yml
├── nginx.conf
└── certs/                  # 自簽憑證
```

## 🛠 快速啟動指南

```bash
# 1. 複製 .env 並設定環境變數
cp .env.example .env

# 2. 建立自簽憑證
mkdir -p certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/selfsigned.key \
  -out certs/selfsigned.crt \
  -subj "/C=TW/ST=Taiwan/L=Taipei/O=Company/CN=localhost"

# 3. 啟動容器服務
docker compose up --build
```

## 🔐 預設管理者帳號

| 帳號 | 密碼     |
|------|----------|
| admin | admin123 |

## 📌 注意事項

- 向量儲存檔案已加入 `.gitignore`，不建議納入 Git 控管
- `/backend/data/` 資料夾可自動監控檔案變更並重建向量庫

---

## 📄 License

MIT License © 2025 SanShin AI