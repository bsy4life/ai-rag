from core import reload_qa_chain
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver as Observer
import os
import time
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "clear")
MIN_RELOAD_INTERVAL = 1.0
_last_reload_ts = 0.0
_rebuild_timer = None

class ReloadHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        global _last_reload_ts, _rebuild_timer
        if event.is_directory:
            return
        print(f"👀 [watchdog] 偵測到變更: {event.event_type} - {event.src_path}", flush=True)
        now = time.time()
        if _rebuild_timer:
            _rebuild_timer.cancel()
        _rebuild_timer = threading.Timer(MIN_RELOAD_INTERVAL, reload_qa_chain)
        _rebuild_timer.start()

def start_watchdog():
    print(f"🛠️ Watchdog 監聽目錄：{DATA_DIR}", flush=True)
    if not os.path.exists(DATA_DIR):
        print("❌ 監控資料夾不存在！請確認掛載正確", flush=True)
    else:
        print(f"📁 資料夾內容：{os.listdir(DATA_DIR)}", flush=True)
    observer = Observer()
    observer.schedule(ReloadHandler(), path=DATA_DIR, recursive=True)
    observer.start()
    print(f"👀 正在使用 PollingObserver 監控 {DATA_DIR} ...", flush=True)
    return observer
