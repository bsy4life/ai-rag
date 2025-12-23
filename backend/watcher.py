import os
import time
import json
import logging
from typing import Optional
from urllib import request, error

from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - watcher - %(levelname)s - %(message)s"
)
log = logging.getLogger("watcher")


def _truthy(v: Optional[str]) -> bool:
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def get_data_root() -> str:
    """
    統一資料根目錄：
    1) KB_ROOT
    2) DATA_DIR / DATA_ROOT
    3) fallback: /app/data（docker 慣例）
    """
    kb_root = os.getenv("KB_ROOT")
    data_dir = os.getenv("DATA_DIR") or os.getenv("DATA_ROOT")
    root = kb_root or data_dir or "/app/data"
    return os.path.abspath(root)


def trigger_reload_via_api() -> bool:
    """
    最穩定：直接呼叫後端 API /system/reload
    - container 內用 service name：http://backend:8000
    - 若有權限驗證，可用 WATCHER_TOKEN 帶 Bearer token
    """
    backend_url = os.getenv("BACKEND_INTERNAL_URL", "http://backend:8000").rstrip("/")
    url = backend_url + "/system/reload"

    token = os.getenv("WATCHER_TOKEN")
    headers = {
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = "Bearer " + token

    req = request.Request(url, method="POST", headers=headers, data=b"{}")

    try:
        with request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            # 只截前 300 字，避免 log 太長
            log.info("✅ [Watcher] 已呼叫 %s，狀態=%s，回應=%s", url, resp.status, body[:300])
            return 200 <= resp.status < 300

    except error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        log.warning("⚠️ [Watcher] 呼叫 %s 失敗：HTTP %s，回應=%s", url, e.code, body[:300])
        return False

    except Exception as e:
        log.warning("⚠️ [Watcher] 呼叫 %s 失敗（非 HTTP）：%s", url, e)
        return False


class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, cooldown_sec: float):
        super().__init__()
        self.cooldown = cooldown_sec
        self.last_trigger = 0.0

    def _should_trigger(self) -> bool:
        now = time.time()
        if now - self.last_trigger < self.cooldown:
            return False
        self.last_trigger = now
        return True

    def on_any_event(self, event):
        # 忽略資料夾事件
        if event.is_directory:
            return

        path = getattr(event, "src_path", "") or ""
        event_type = getattr(event, "event_type", "unknown")

        # 只關心常見文件
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".md", ".txt", ".rtf"):
            return

        # Debounce
        if not self._should_trigger():
            return

        log.info("🔔 [Watcher] 變更偵測: %s (%s)", path, event_type)

        # ✅ 直接呼叫後端 /system/reload（最不會踩 core.py 函式名問題）
        ok = trigger_reload_via_api()
        if not ok:
            log.warning("⚠️ [Watcher] 觸發索引更新失敗（不致命）：/system/reload 未成功")


def main():
    print("==================================================")
    print("🚀 SanShin AI 文件監控服務啟動")
    print("==================================================")

    data_root = get_data_root()

    # 預設與你 log 一致：/app/data/markdown、/app/data/business
    tech_dir = os.getenv("WATCH_TECH_DIR", os.path.join(data_root, "markdown"))
    biz_dir = os.getenv("WATCH_BIZ_DIR", os.path.join(data_root, "business"))

    cooldown = float(os.getenv("WATCHER_COOLDOWN", "3.0"))

    force_polling = _truthy(os.getenv("WATCHDOG_FORCE_POLLING"))
    polling_interval = float(os.getenv("WATCHDOG_POLLING_INTERVAL", "1.0"))

    log.info("📌 [Watcher] DATA_ROOT = %s", data_root)
    log.info("👀 [Watcher] 開始監控技術文檔目錄: %s", tech_dir)
    log.info("👀 [Watcher] 開始監控業務資料目錄: %s", biz_dir)
    log.info("🚀 [Watcher] 文件監控已啟動，冷卻時間: %.1f秒", cooldown)
    log.info("🧭 [Watcher] 模式: %s", "PollingObserver" if force_polling else "Observer")

    os.makedirs(tech_dir, exist_ok=True)
    os.makedirs(biz_dir, exist_ok=True)

    handler = DebouncedHandler(cooldown_sec=cooldown)

    if force_polling:
        observer = PollingObserver(timeout=polling_interval)
    else:
        observer = Observer()

    observer.schedule(handler, tech_dir, recursive=True)
    observer.schedule(handler, biz_dir, recursive=True)
    observer.start()

    log.info("📋 [Watcher] 監控服務運行中，按 Ctrl+C 停止...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("🛑 [Watcher] 收到停止訊號，準備關閉...")
    finally:
        observer.stop()
        observer.join()
        log.info("✅ [Watcher] 已停止")


if __name__ == "__main__":
    main()
