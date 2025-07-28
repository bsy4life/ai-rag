
#  SanShin AI

SanShin AI 是一個內部部署的智慧問答平台，基於 FastAPI + LangChain + OpenAI 架構，支援本地文件問答、多輪對話記憶、自動向量更新與 PWA 安裝。

## 功能特性

- 文件夾自動向量化（支援 PDF / TXT）
- 問答記憶記錄，支援多輪上下文
- FastAPI 後端整合 OpenAI / Ollama 模型
- Service Worker + manifest 完整 PWA 安裝支援
- 使用者登入系統（帳號密碼）
- Nginx + 自簽 SSL 證書 或 Cloudflare Tunnel 快速內網測試

## 專案結構

```
ai-rag/
├── backend/               # FastAPI 應用程式
│   ├── app.py             # 主後端入口
│   ├── core.py            # 問答邏輯與向量資料庫
│   ├── data/              # 文件與向量儲存目錄
│   └── frontend/          # 前端 HTML + JS + PWA 靜態頁面
├── certs/                 # 自簽憑證（已在 .gitignore 排除）
├── docker-compose.yml     # 一鍵部署服務（DB、後端、Nginx）
├── Dockerfile             # FastAPI 建構檔
├── nginx.conf             # Nginx 設定
└── .gitignore             # 排除向量檔與憑證等機密
```

## 快速啟動

```bash
# 啟動 PostgreSQL + FastAPI + Nginx
docker compose up --build
```

前端預設可訪問：`https://<你的IP或Cloudflare域名>/frontend/`

> ✅ 若憑證失效可重新產生：`openssl req -x509 -newkey rsa:4096 -sha256 -nodes -keyout selfsigned.key -out selfsigned.crt -days 365 -config san.cnf`

---

## 📱 PWA 測試建議

- ✅ 使用 Chrome，訪問合法 HTTPS（自簽需信任）
- ✅ `manifest.json` + `sw.js` 載入成功
- ✅ 首次載入會出現「安裝」按鈕，可手動觸發

---

## 👨‍💻 Maintainer

Built with 💙 by SanShin Dev Team
