import os
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, Callable
from git import Repo, GitCommandError
from git.exc import InvalidGitRepositoryError


class GitManager:
    def __init__(self, repo_url: str = "", local_path: str = "", branch: str = "main"):
        self.repo_url = repo_url
        self.local_path = Path(local_path) if local_path else Path("repo")
        self.branch = branch
        self.repo: Optional[Repo] = None
        self._progress_callback: Optional[Callable[[str], None]] = None
    
    def set_progress_callback(self, callback: Callable[[str], None]):
        self._progress_callback = callback
    
    def _notify(self, message: str):
        if self._progress_callback:
            self._progress_callback(message)
    
    def is_initialized(self) -> bool:
        try:
            Repo(self.local_path)
            return True
        except InvalidGitRepositoryError:
            return False
    
    def init_repository(self, username: str = "", email: str = "", token: str = "") -> Tuple[bool, str]:
        try:
            self._notify("开始初始化仓库...")
            
            if self.local_path.exists():
                shutil.rmtree(self.local_path)
            
            self.local_path.mkdir(parents=True, exist_ok=True)
            
            auth_url = self._build_auth_url(username, token)
            
            self._notify("克隆远程仓库...")
            self.repo = Repo.clone_from(auth_url, self.local_path, branch=self.branch)
            
            if username and email:
                with self.repo.config_writer() as config:
                    config.set_value("user", "name", username)
                    config.set_value("user", "email", email)
            
            self._notify("仓库初始化成功")
            return True, "仓库初始化成功"
            
        except GitCommandError as e:
            error_msg = f"Git命令错误: {str(e)}"
            self._notify(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"初始化失败: {str(e)}"
            self._notify(error_msg)
            return False, error_msg
    
    def _build_auth_url(self, username: str, token: str) -> str:
        if not token:
            return self.repo_url
        
        if "github.com" in self.repo_url:
            if self.repo_url.startswith("https://"):
                return self.repo_url.replace("https://", f"https://{username}:{token}@")
            elif self.repo_url.startswith("git@"):
                return self.repo_url
        return self.repo_url
    
    def load_repository(self) -> bool:
        try:
            self.repo = Repo(self.local_path)
            return True
        except Exception:
            return False
    
    def get_file_hash(self, file_path: Path) -> str:
        if not file_path.exists():
            return ""
        
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def copy_files(self, source_files: List[Path]) -> List[Tuple[str, bool]]:
        results = []
        
        for source_file in source_files:
            try:
                dest_file = self.local_path / source_file.name
                shutil.copy2(source_file, dest_file)
                results.append((source_file.name, True))
            except Exception as e:
                results.append((source_file.name, False))
        
        return results
    
    def has_changes(self, source_files: List[Path], stored_hashes: dict) -> Tuple[bool, List[Path], dict]:
        changed_files = []
        current_hashes = {}
        
        for source_file in source_files:
            if not source_file.exists():
                continue
            
            current_hash = self.get_file_hash(source_file)
            current_hashes[source_file.name] = current_hash
            
            stored_hash = stored_hashes.get(source_file.name, "")
            if current_hash != stored_hash:
                changed_files.append(source_file)
        
        return len(changed_files) > 0, changed_files, current_hashes
    
    def commit_and_push(self, commit_message: str = "") -> Tuple[bool, str]:
        if not self.repo:
            if not self.load_repository():
                return False, "仓库未加载"
        
        try:
            self._notify("检查文件变更...")
            
            # 强制添加所有文件
            self.repo.git.add("-A")
            
            # 获取当前时间
            upload_time = datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')
            self._notify(f"上传时间: {upload_time}")
            
            # 检查是否有实际变更
            has_changes = self.repo.is_dirty(untracked_files=True) or len(self.repo.untracked_files) > 0
            
            if not has_changes:
                self._notify("检测到没有文件变更，创建强制上传提交...")
            
            # 设置提交消息
            if not commit_message:
                commit_message = f"自动更新 - 上传时间: {upload_time}"
            
            # 创建提交（允许空提交）
            self._notify(f"提交变更: {commit_message}")
            # 使用 git commit 命令而不是 index.commit，因为 --allow-empty 不被 API 支持
            self.repo.git.commit('--allow-empty', '-m', commit_message)
            
            self._notify("推送到远程仓库...")
            origin = self.repo.remote(name="origin")
            origin.push(refspec=f"HEAD:{self.branch}")
            
            self._notify("推送成功")
            return True, f"上传成功 - {upload_time}"
                
        except GitCommandError as e:
            error_msg = f"Git操作失败: {str(e)}"
            self._notify(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"上传失败: {str(e)}"
            self._notify(error_msg)
            return False, error_msg
    
    def sync_and_upload(self, source_files: List[Path], stored_hashes: dict, 
                        username: str = "", token: str = "") -> Tuple[bool, str, dict]:
        try:
            # 确保仓库已加载
            if not self.repo:
                if not self.load_repository():
                    return False, "无法加载仓库，请先初始化仓库", stored_hashes
            
            has_changes, changed_files, current_hashes = self.has_changes(source_files, stored_hashes)
            
            # 无论是否有变化，都强制上传
            if has_changes:
                self._notify(f"检测到 {len(changed_files)} 个文件变更")
            else:
                self._notify("检测到没有文件变更，执行强制上传...")
            
            if username and token:
                auth_url = self._build_auth_url(username, token)
                with self.repo.config_writer() as config:
                    config.set_value('remote "origin"', 'url', auth_url)
            
            self._notify("拉取最新代码...")
            try:
                self.repo.git.pull("origin", self.branch)
            except GitCommandError:
                self._notify("拉取失败，继续上传...")
            
            # 只复制有变化的文件
            if has_changes and changed_files:
                copy_results = self.copy_files(changed_files)
                failed_copies = [name for name, success in copy_results if not success]
                
                if failed_copies:
                    return False, f"复制文件失败: {', '.join(failed_copies)}", stored_hashes
            
            # 始终执行提交和推送（即使没有变化）
            commit_message = f"自动更新 - {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}"
            success, message = self.commit_and_push(commit_message)
            
            if success:
                return True, message, current_hashes
            else:
                return False, message, stored_hashes
                
        except Exception as e:
            return False, f"同步失败: {str(e)}", stored_hashes
