import time
import threading
from typing import Callable, Optional
from datetime import datetime, timedelta


class UploadScheduler:
    def __init__(self):
        self._interval_hours: int = 6
        self._callback: Optional[Callable[[], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._next_run_time: Optional[datetime] = None
        self._last_run_time: Optional[datetime] = None
    
    def start(self, interval_hours: int, callback: Callable[[], None]) -> bool:
        """启动调度器，立即设置下次上传时间
        
        Args:
            interval_hours: 上传间隔（小时）
            callback: 上传回调函数
        """
        if self._running:
            self.stop()
        
        self._interval_hours = interval_hours
        self._callback = callback
        self._stop_event.clear()
        self._running = True
        
        # 立即设置下次上传时间（间隔时间后）
        self._next_run_time = datetime.now() + timedelta(hours=interval_hours)
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True
    
    def stop(self):
        self._stop_event.set()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self._next_run_time = None
    
    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                if self._next_run_time and datetime.now() >= self._next_run_time:
                    # 到达上传时间，执行上传
                    if self._callback:
                        self._callback()
                    self._last_run_time = datetime.now()
                    # 上传执行后，立即设置下次上传时间（间隔时间后）
                    # 这样可以实现：上传完成后 -> 倒计时 -> 再次上传
                    self._next_run_time = datetime.now() + timedelta(hours=self._interval_hours)
                
                time.sleep(30)
            except Exception:
                time.sleep(60)
    
    def is_running(self) -> bool:
        return self._running
    
    def get_next_run_time(self) -> Optional[datetime]:
        return self._next_run_time
    
    def get_last_run_time(self) -> Optional[datetime]:
        return self._last_run_time
    
    def get_remaining_time(self) -> Optional[timedelta]:
        if self._next_run_time:
            remaining = self._next_run_time - datetime.now()
            return remaining if remaining.total_seconds() > 0 else timedelta(0)
        return None
    
    def update_interval(self, interval_hours: int):
        self._interval_hours = interval_hours
        # 更新间隔时，如果有下次运行时间，重新计算
        if self._running and self._next_run_time:
            self._next_run_time = datetime.now() + timedelta(hours=interval_hours)
