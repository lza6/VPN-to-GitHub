import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime


@dataclass
class AppConfig:
    repo_full_name: str = ""
    repo_url: str = ""
    branch: str = "main"
    target_folder: str = ""
    upload_interval_hours: int = 6
    auto_start: bool = False
    minimize_to_tray: bool = True
    files_to_upload: List[str] = field(default_factory=lambda: [
        "ACL4SSR_Online_FullyamI",
        "all.yaml",
        "base64.txt",
        "bdg.yaml",
        "mihomo.yaml"
    ])
    last_upload_time: str = ""
    file_hashes: Dict[str, str] = field(default_factory=dict)
    git_username: str = ""
    git_email: str = ""
    # 窗口位置和大小
    window_x: int = 100
    window_y: int = 100
    window_width: int = 1100
    window_height: int = 900
    window_maximized: bool = False
    # 统计信息
    total_upload_count: int = 0
    success_upload_count: int = 0
    failed_upload_count: int = 0
    first_upload_time: str = ""


class ConfigManager:
    CONFIG_FILE = "app_config.json"
    
    def __init__(self):
        self.config_path = Path(self.CONFIG_FILE)
        self._config = AppConfig()
        self.load()
    
    def load(self) -> AppConfig:
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._config = AppConfig(**data)
            except Exception:
                self._config = AppConfig()
        return self._config
    
    def save(self) -> bool:
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(self._config), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
    
    @property
    def config(self) -> AppConfig:
        return self._config
    
    def update(self, **kwargs) -> bool:
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        return self.save()
    
    def get_file_hash(self, filename: str) -> str:
        return self._config.file_hashes.get(filename, "")
    
    def set_file_hash(self, filename: str, file_hash: str) -> bool:
        self._config.file_hashes[filename] = file_hash
        return self.save()
    
    def update_last_upload_time(self) -> bool:
        self._config.last_upload_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        return self.save()
    
    def get_target_files(self) -> List[Path]:
        if not self._config.target_folder:
            return []
        
        target_path = Path(self._config.target_folder)
        if not target_path.exists():
            return []
        
        files = []
        for filename in self._config.files_to_upload:
            file_path = target_path / filename
            if file_path.exists():
                files.append(file_path)
        return files
