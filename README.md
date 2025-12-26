# 🧠 SanShin AI

**SanShin AI** 是一個內部部署的智慧問答與業務分析平台，基於 FastAPI + LangChain + OpenAI/Anthropic 架構。

支援多種知識庫類型、AI 驅動的業務智能分析、多輪對話記憶，以及完整的 PWA 行動體驗。

---

## ✨ 核心功能

### 📚 知識庫問答
- **技術文檔** - 自動向量化 PDF/Markdown/TXT，三層檢索（關鍵字 + BM25 + 向量）
- **個人知識庫** - 用戶專屬文檔空間，支援圖片提取
- **智慧型號識別** - SMC、VALQUA、玖基等產品型號自動識別

### 📊 業務智能分析 (NEW!)
- **純 AI 驅動** - 自然語言查詢業務數據，無需編寫規則
- **BI 洞察** - 自動趨勢分析、異常偵測、建議生成
- **動態代碼生成** - AI 生成 Pandas 查詢，彈性處理各種問題
- **視覺化建議** - 推薦適合的圖表類型

### 🔧 系統特性
- **多 LLM 支援** - OpenAI GPT-4o / Anthropic Claude，可自動切換
- **分層模型** - 簡單問題用小模型，複雜問題用大模型
- **完整快取** - TTL + 持久化，降低 API 成本
- **Reranker** - Cohere / 本地模型優化排序
- **PWA 支援** - 可安裝為桌面/手機 App

---

## 🏗 系統架構

```
┌─────────────────────────────────────────────────────────────┐
│                      SanShin AI                             │
├─────────────────────────────────────────────────────────────┤
│  Frontend (PWA)                                             │
│  └── index.html + script.js + Service Worker               │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Backend (app.py)                                   │
│  ├── /ask          - 統一問答入口                           │
│  ├── /api/business/* - 業務 AI API                         │
│  ├── /kb/*         - 個人知識庫 API                         │
│  └── /system/*     - 系統管理 API                           │
├─────────────────────────────────────────────────────────────┤
│  Core Engine (core.py)                                      │
│  ├── 三層檢索: 關鍵字 + BM25 + 向量                          │
│  ├── 分層 LLM: simple/complex/business                      │
│  └── 查詢分類: 技術/業務/個人 自動路由                        │
├─────────────────────────────────────────────────────────────┤
│  Business AI Engine (business_ai_engine.py) 🆕              │
│  ├── AI 意圖解析 - 理解自然語言                              │
│  ├── 代碼生成 - 動態 Pandas 查詢                            │
│  ├── BI 分析 - 趨勢/異常/建議                               │
│  └── 自然語言回覆                                           │
├─────────────────────────────────────────────────────────────┤
│  Data Layer                                                 │
│  ├── ChromaDB (向量庫)                                      │
│  ├── PostgreSQL (用戶/聊天記錄)                              │
│  └── CSV (業務日報數據)                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 專案結構

```
ai-rag/
├── app.py                 # FastAPI 主入口
├── core.py                # 問答核心引擎
├── business_ai_engine.py  # 🆕 AI 業務智能引擎
├── business_csv.py        # 傳統業務查詢（回退用）
├── business_processor.py  # 業務日報 TXT → CSV 處理
├── personal_kb.py         # 個人知識庫
├── vectordb.py            # 向量資料庫封裝
├── config.py              # 統一配置中心
├── loaders.py             # 文檔載入器
├── cache.py               # 快取系統
├── auth.py                # 認證相關
├── models.py              # SQLAlchemy 模型
├── watcher.py             # 文件監控服務
├── index.html             # 前端主頁面
├── script.js              # 前端邏輯
├── docker-compose.yml     # Docker 部署配置
├── Dockerfile             # 容器建構檔
└── requirements.txt       # Python 依賴
```

---

## 🚀 快速開始

### 1. 環境變數 (.env)

```env
# LLM 配置
LLM_PROVIDER=openai              # openai / anthropic / auto
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx     # 可選

# 模型選擇
OPENAI_MODEL_DEFAULT=gpt-4o-mini
OPENAI_MODEL_COMPLEX=gpt-4o
OPENAI_MODEL_BUSINESS=gpt-4o     # 業務分析用

# 業務查詢模式
BUSINESS_QUERY_MODE=ai           # ai（AI驅動）或 legacy（傳統規則）

# 資料庫
DATABASE_URL=postgresql://user:pass@db:5432/sanshin

# 路徑
DATA_DIR=/app/data
BUSINESS_CSV_FILE=/app/data/business/clean_business.csv
```

### 2. Docker 啟動

```bash
# 建構並啟動
docker compose up --build -d

# 查看日誌
docker compose logs -f backend
```

### 3. 訪問系統

- 前端: `http://localhost:8000/`
- API 文檔: `http://localhost:8000/docs`

---

## 📊 業務 AI 使用範例

### 自然語言查詢

```
用戶: 台南營業所最近一個月的業績如何？有什麼趨勢？

AI: 📊 數據摘要
- 本月業務活動: 156 筆
- 業務拜訪: 89 次
- 活躍客戶數: 45 家

💡 關鍵洞察
1. 拜訪量較上月增加 12%
2. 東台精機是最頻繁拜訪的客戶（23 次）
3. 週三是拜訪高峰日

📈 趨勢分析
- 月中活動量明顯高於月初月末

✅ 建議行動
- 加強新客戶開發力度
- 分散拜訪日期，平衡工作量
```

### API 調用

```python
import requests

# AI 業務查詢
response = requests.post(
    "http://localhost:8000/api/business/ai-query",
    json={"query": "比較各營業所上月業績"},
    headers={"Authorization": f"Bearer {token}"}
)

result = response.json()
print(result["answer"])       # 自然語言回答
print(result["insights"])     # BI 洞察
print(result["recommendations"])  # 建議行動
```

---

## 🔌 API 端點

### 問答

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/ask` | 統一問答入口（自動路由技術/業務/個人） |

### 業務 AI

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/business/ai-query` | AI 業務查詢 |
| GET | `/api/business/schema` | 獲取數據 schema |
| GET | `/api/business/quick-stats` | 快速統計（儀表板用） |
| POST | `/api/business/reload` | 重新載入數據（管理員） |

### 知識庫

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/kb/personal/{user_id}/upload` | 上傳個人文檔 |
| GET | `/kb/personal/{user_id}/documents` | 列出文檔 |
| POST | `/knowledge/upload-business` | 上傳業務日報 |

### 系統

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/system/reload` | 重新載入向量庫 |
| GET | `/system/stats` | 系統統計 |
| GET | `/health` | 健康檢查 |

---

## ⚙️ 環境變數完整列表

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `LLM_PROVIDER` | `openai` | LLM 供應商 (openai/anthropic/auto) |
| `OPENAI_API_KEY` | - | OpenAI API 金鑰 |
| `ANTHROPIC_API_KEY` | - | Anthropic API 金鑰 |
| `BUSINESS_QUERY_MODE` | `ai` | 業務查詢模式 (ai/legacy) |
| `OPENAI_MODEL_BUSINESS` | `gpt-4o` | 業務分析使用的模型 |
| `DATA_DIR` | `/app/data` | 資料根目錄 |
| `VECTOR_DB_DIR` | `/app/data/vectordb_sanshin` | 向量庫目錄 |
| `BUSINESS_CSV_FILE` | `/app/data/business/clean_business.csv` | 業務 CSV 路徑 |
| `CACHE_ENABLED` | `true` | 啟用快取 |
| `CACHE_TTL` | `3600` | 快取 TTL（秒） |

---

## 📱 PWA 安裝

1. 使用 Chrome/Edge 訪問系統
2. 點擊網址列右側的安裝圖示
3. 或使用選單「安裝應用程式」
4. 支援離線快取基本功能

---

## 🔧 開發指南

### 本地開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動開發伺服器
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 測試業務 AI

```bash
# 互動式測試
python business_ai_engine.py

# 單元測試
python -c "
from business_ai_engine import BusinessAIEngine
engine = BusinessAIEngine()
print(engine.get_schema_info())
result = engine.query('最近有多少業務活動？')
print(result['answer'])
"
```

---

## 🔄 更新日誌

### v2.0.0 (2024-12)
- 🆕 新增 AI 驅動的業務智能引擎
- 🆕 BI 分析：趨勢偵測、異常識別、建議生成
- 🆕 動態 Pandas 代碼生成
- 🔧 支援 Anthropic Claude 模型
- 🔧 改進的錯誤處理與回退機制

### v1.x
- 技術文檔 RAG 問答
- 個人知識庫
- PWA 支援
- 多輪對話記憶

---

## 👨‍💻 維護者

Built with 💙 by SanShin Dev Team

---

## 📄 授權

本專案為內部使用，未經授權不得對外分發。
