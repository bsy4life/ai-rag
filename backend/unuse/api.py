# api.py - SanShin AI 完整 API（生產級）
"""
API 端點：
1. 查詢 API（智慧/技術/業務/個人）
2. 個人知識庫管理
3. 系統管理
4. 圖片服務
"""

import os
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import (
    APIRouter, HTTPException, UploadFile, File, 
    Query, BackgroundTasks
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import PERSONAL_KB_CONFIG, TEMP_DIR
from core_engine import get_engine, query as engine_query, reload_engine
from personal_kb import get_personal_kb, add_document, search_personal

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════════

class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field(default="smart", pattern="^(smart|technical|business|personal)$")
    user_id: Optional[str] = Field(default="default")
    use_cache: bool = Field(default=True)

class AskResponse(BaseModel):
    success: bool
    answer: str
    source_type: str
    sources: List[str] = []
    images: List[dict] = []
    from_cache: bool = False
    cost_estimate: Optional[dict] = None
    metadata: Optional[dict] = None

class PersonalUploadResponse(BaseModel):
    success: bool
    message: str
    doc_id: Optional[str] = None
    filename: Optional[str] = None
    chunks: Optional[int] = None
    images: Optional[int] = None
    keywords: Optional[List[str]] = None
    error: Optional[str] = None

class PersonalSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)

class PersonalSearchResponse(BaseModel):
    success: bool
    query: str
    results: List[dict] = []
    total: int = 0

# ═══════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════

router = APIRouter(tags=["SanShin AI"])

# ═══════════════════════════════════════════════════════════════
# 查詢 API
# ═══════════════════════════════════════════════════════════════

@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """
    智慧問答
    
    - **mode**: smart（自動判斷）, technical（技術）, business（業務）, personal（個人）
    """
    try:
        query = request.query.strip()
        
        # 個人模式特殊處理
        if request.mode == "personal":
            return await ask_personal(query, request.user_id)
        
        # 一般查詢
        result = engine_query(query, request.mode)
        
        return AskResponse(
            success=True,
            answer=result.answer,
            source_type=result.source_type,
            sources=result.sources[:5],
            images=result.images,
            from_cache=result.from_cache,
            cost_estimate=result.cost_estimate,
            metadata=result.metadata,
        )
    
    except Exception as e:
        logger.error(f"查詢失敗: {e}")
        return AskResponse(
            success=False,
            answer=f"查詢發生錯誤：{str(e)}",
            source_type="error",
        )


async def ask_personal(query: str, user_id: str) -> AskResponse:
    """個人知識庫查詢"""
    try:
        kb = get_personal_kb(user_id)
        results = kb.search(query, top_k=5)
        
        if not results:
            return AskResponse(
                success=True,
                answer="在個人知識庫中未找到相關內容。請確認是否已上傳相關文件。",
                source_type="personal",
                sources=[],
            )
        
        # 組裝上下文
        all_images = []
        
        for r in results:
            for img in r.images[:2]:
                all_images.append({
                    "doc_id": r.doc_id,
                    "filename": r.filename,
                    "image_name": img.get("name"),
                    "url": f"/kb/personal/{user_id}/images/{r.doc_id}/{img.get('name')}",
                    "context": img.get("paragraph_text", ""),
                })
        
        # 生成回答
        from core_engine import get_engine, SearchResult
        engine = get_engine()
        
        search_results = [
            SearchResult(
                content=r.content,
                source=r.filename,
                doc_type="personal",
                score=r.score,
            )
            for r in results
        ]
        
        answer, cost = engine.generate_answer(query, search_results, "personal")
        
        # 添加圖片提示
        if all_images:
            answer += f"\n\n📷 找到 {len(all_images)} 張相關圖片，請查看下方。"
        
        return AskResponse(
            success=True,
            answer=answer,
            source_type="personal",
            sources=[r.filename for r in results],
            images=all_images,
            cost_estimate=cost,
        )
    
    except Exception as e:
        logger.error(f"個人查詢失敗: {e}")
        return AskResponse(
            success=False,
            answer=f"查詢失敗：{str(e)}",
            source_type="error",
        )


# ═══════════════════════════════════════════════════════════════
# 個人知識庫 API
# ═══════════════════════════════════════════════════════════════

@router.post("/kb/personal/upload", response_model=PersonalUploadResponse)
async def upload_personal_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Query(default="default"),
    async_process: bool = Query(default=True),
):
    """上傳文件到個人知識庫"""
    # 檢查格式
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in PERSONAL_KB_CONFIG.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的格式: {ext}"
        )
    
    # 儲存暫存檔
    os.makedirs(TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(TEMP_DIR, f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    
    try:
        content = await file.read()
        
        # 檢查大小
        max_size = PERSONAL_KB_CONFIG.max_file_size_mb * 1024 * 1024
        if len(content) > max_size:
            raise HTTPException(status_code=400, detail="檔案太大")
        
        with open(temp_path, 'wb') as f:
            f.write(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"儲存失敗: {e}")
    
    # 處理文件
    if async_process:
        background_tasks.add_task(
            process_document_background, user_id, temp_path, file.filename
        )
        return PersonalUploadResponse(
            success=True,
            message="文件已上傳，正在處理中...",
            filename=file.filename,
        )
    else:
        try:
            result = add_document(user_id, temp_path, file.filename)
            return PersonalUploadResponse(
                success=result.get("success", False),
                message="處理完成" if result.get("success") else result.get("error", "錯誤"),
                **{k: v for k, v in result.items() if k not in ["success", "error"]}
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


def process_document_background(user_id: str, file_path: str, filename: str):
    """背景處理文件"""
    try:
        result = add_document(user_id, file_path, filename)
        logger.info(f"文件處理完成: {filename} -> {result}")
    except Exception as e:
        logger.error(f"文件處理失敗: {filename} -> {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.post("/kb/personal/search", response_model=PersonalSearchResponse)
async def search_personal_kb_api(
    request: PersonalSearchRequest,
    user_id: str = Query(default="default"),
):
    """搜尋個人知識庫"""
    try:
        results = search_personal(user_id, request.query, request.top_k)
        
        return PersonalSearchResponse(
            success=True,
            query=request.query,
            results=[
                {
                    "doc_id": r.doc_id,
                    "filename": r.filename,
                    "content": r.content,
                    "score": r.score,
                    "match_type": r.match_type,
                    "images": [
                        {**img, "url": f"/kb/personal/{user_id}/images/{r.doc_id}/{img.get('name')}"}
                        for img in r.images
                    ],
                }
                for r in results
            ],
            total=len(results),
        )
    except Exception as e:
        return PersonalSearchResponse(success=False, query=request.query)


@router.get("/kb/personal/documents")
async def list_personal_documents(user_id: str = Query(default="default")):
    """列出個人文件"""
    kb = get_personal_kb(user_id)
    return {
        "success": True,
        "user_id": user_id,
        "documents": kb.list_documents(),
        "stats": kb.get_stats(),
    }


@router.delete("/kb/personal/documents/{doc_id}")
async def delete_personal_document(doc_id: str, user_id: str = Query(default="default")):
    """刪除個人文件"""
    kb = get_personal_kb(user_id)
    if kb.remove_document(doc_id):
        return {"success": True, "message": f"文件 {doc_id} 已刪除"}
    raise HTTPException(status_code=404, detail="文件不存在")


@router.get("/kb/personal/{user_id}/images/{doc_id}/{image_name}")
async def get_personal_image(user_id: str, doc_id: str, image_name: str):
    """取得個人文件圖片"""
    kb = get_personal_kb(user_id)
    image_path = kb.get_image_path(doc_id, image_name)
    
    if image_path and os.path.exists(image_path):
        ext = os.path.splitext(image_name)[1].lower()
        mime = {'png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}.get(ext, 'image/png')
        return FileResponse(image_path, media_type=mime, headers={"Cache-Control": "max-age=86400"})
    
    raise HTTPException(status_code=404, detail="圖片不存在")


# ═══════════════════════════════════════════════════════════════
# 系統管理 API
# ═══════════════════════════════════════════════════════════════

@router.get("/system/stats")
async def get_system_stats():
    """取得系統統計"""
    engine = get_engine()
    return {"success": True, "engine": engine.get_stats(), "timestamp": datetime.now().isoformat()}


@router.post("/system/reload")
async def reload_system():
    """重新載入系統"""
    reload_engine()
    return {"success": True, "message": "系統已重新載入"}


@router.get("/system/health")
async def health_check():
    """健康檢查"""
    engine = get_engine()
    stats = engine.get_stats()
    return {
        "status": "healthy" if stats.get("initialized") else "initializing",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "vectordb": stats.get("vectordb_loaded", False),
            "bm25": stats.get("bm25_loaded", False),
            "reranker": stats.get("reranker_enabled", False),
        }
    }


@router.delete("/cache/clear")
async def clear_cache():
    """清空快取"""
    get_engine().cache.clear()
    return {"success": True, "message": "快取已清空"}


def setup_routes(app):
    """設定路由"""
    app.include_router(router)
    logger.info("✅ API 路由已載入")
