import os
import time
import hashlib
from pathlib import Path
from typing import Set, List, Callable, Optional
from threading import Thread, Event
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, target_files: Set[str], callback: Callable[[str], None]):
        super().__init__()
        self.target_files = target_files
        self.callback = callback
    
    def on_modified(self, event):
        if not event.is_directory:
            filename = Path(event.src_path).name
            if filename in self.target_files:
                self.callback(filename)
    
    def on_created(self, event):
        if not event.is_directory:
            filename = Path(event.src_path).name
            if filename in self.target_files:
                self.callback(filename)


class FileWatcher:
    def __init__(self):
        self.observer: Optional[Observer] = None
        self.event_handler: Optional[FileChangeHandler] = None
        self._watch_path: Optional[Path] = None
        self._target_files: Set[str] = set()
        self._change_callback: Optional[Callable[[str], None]] = None
        self._running = False
    
    def start(self, watch_path: Path, target_files: List[str], 
              change_callback: Callable[[str], None]) -> bool:
        if self._running:
            self.stop()
        
        if not watch_path.exists():
            return False
        
        self._watch_path = watch_path
        self._target_files = set(target_files)
        self._change_callback = change_callback
        
        try:
            self.event_handler = FileChangeHandler(self._target_files, self._on_file_changed)
            self.observer = Observer()
            self.observer.schedule(self.event_handler, str(watch_path), recursive=False)
            self.observer.start()
            self._running = True
            return True
        except Exception:
            return False
    
    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        self._running = False
    
    def _on_file_changed(self, filename: str):
        if self._change_callback:
            self._change_callback(filename)
    
    def is_running(self) -> bool:
        return self._running


class FileHashCache:
    def __init__(self):
        self._hashes: dict = {}
        self._lock = Event()
        self._lock.set()
    
    def get_hash(self, filepath: Path) -> str:
        if not filepath.exists():
            return ""
        
        self._lock.wait()
        cached = self._hashes.get(str(filepath))
        
        current_mtime = filepath.stat().st_mtime
        current_size = filepath.stat().st_size
        cache_key = f"{current_mtime}_{current_size}"
        
        if cached and cached.get("key") == cache_key:
            return cached.get("hash", "")
        
        file_hash = self._calculate_hash(filepath)
        self._hashes[str(filepath)] = {
            "key": cache_key,
            "hash": file_hash
        }
        return file_hash
    
    def _calculate_hash(self, filepath: Path) -> str:
        hash_md5 = hashlib.md5()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return ""
    
    def clear(self):
        self._hashes.clear()
    
    def update_hash(self, filepath: Path, file_hash: str):
        if filepath.exists():
            current_mtime = filepath.stat().st_mtime
            current_size = filepath.stat().st_size
            cache_key = f"{current_mtime}_{current_size}"
            self._hashes[str(filepath)] = {
                "key": cache_key,
                "hash": file_hash
            }
