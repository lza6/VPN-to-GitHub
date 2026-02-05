"""
GitHub Uploader - GitHub OAuth认证
使用GitHub CLI进行认证
"""
import sys
import json
import subprocess
from typing import Optional, Callable
from dataclasses import dataclass
from httpx import Client

from credential_manager import credential_manager, GitHubCredential


@dataclass
class AuthResult:
    """认证结果"""
    success: bool
    credential: Optional[GitHubCredential] = None
    error: Optional[str] = None


class GitHubAuth:
    """
    GitHub OAuth认证管理器
    使用GitHub CLI进行认证
    """
    
    def __init__(self):
        self._on_auth_complete: Optional[Callable[[AuthResult], None]] = None
        
        # 检测代理设置
        import os
        http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
        https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        
        # 清理代理地址（移除空字符串和无效地址）
        def clean_proxy(proxy_str):
            if not proxy_str:
                return None
            proxy_str = proxy_str.strip()
            if not proxy_str or proxy_str == "http://" or proxy_str == "https://":
                return None
            return proxy_str
        
        http_proxy = clean_proxy(http_proxy)
        https_proxy = clean_proxy(https_proxy)
        
        # HTTP客户端（自动使用代理）
        proxy = https_proxy or http_proxy
        if proxy:
            print(f"已配置代理: {proxy}")
        
        self._client = Client(
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "GitHub-Auto-Uploader"
            },
            proxy=proxy if proxy else None
        )
    
    def __del__(self):
        if hasattr(self, '_client'):
            self._client.close()
    
    def is_authenticated(self) -> bool:
        """检查是否已认证"""
        return credential_manager.has_credential()
    
    def get_current_user(self) -> Optional[GitHubCredential]:
        """获取当前登录用户"""
        return credential_manager.load_credential()
    
    def start_gh_cli_auth(
        self,
        on_complete: Callable[[AuthResult], None],
        status_callback: Optional[Callable[[str], None]] = None,
        auto_web_login: bool = True,
    ) -> bool:
        """
        使用 GitHub CLI 进行认证（推荐方式）
        
        Args:
            on_complete: 认证完成时的回调
            status_callback: 状态更新回调
            auto_web_login: 是否自动使用web方式登录
            
        Returns:
            是否成功开始认证流程
        """
        self._on_auth_complete = on_complete
        
        try:
            if status_callback:
                status_callback("正在检查GitHub CLI登录状态...")
            
            # 检查是否已登录
            encoding = 'gbk' if sys.platform == 'win32' else 'utf-8'
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                encoding=encoding,
                errors='ignore',
                timeout=10
            )
            
            if result.returncode == 0:
                # 已登录，获取 token
                print("检测到 GitHub CLI 已登录")
                return self._get_gh_cli_token(on_complete, status_callback)
            else:
                # 未登录，自动执行web登录
                print("GitHub CLI 未登录，启动自动web登录")
                if auto_web_login:
                    return self._auto_web_login(on_complete, status_callback)
                else:
                    on_complete(AuthResult(
                        success=False,
                        error="NOT_LOGGED_IN"  # 特殊标记，表示需要打开终端登录
                    ))
                    return False
                
        except FileNotFoundError:
            on_complete(AuthResult(
                success=False,
                error="未找到 GitHub CLI (gh)\n\n"
                      "请安装 GitHub CLI: https://cli.github.com/\n"
                      "或者使用其他登录方式"
            ))
            return False
        except subprocess.TimeoutExpired:
            # 超时也可能是未登录，尝试自动web登录
            print("检查登录状态超时，尝试自动web登录")
            if auto_web_login:
                return self._auto_web_login(on_complete, status_callback)
            else:
                on_complete(AuthResult(
                    success=False,
                    error="检查登录状态超时，请尝试重新配置 GitHub CLI 或手动执行 'gh auth login'"
                ))
                return False
        except Exception as e:
            print(f"GitHub CLI 认证失败: {e}")
            on_complete(AuthResult(success=False, error=str(e)))
            return False
    
    def _auto_web_login(
        self,
        on_complete: Callable[[AuthResult], None],
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """自动使用web方式登录GitHub CLI"""
        import webbrowser
        import threading
        
        def login_worker():
            """在后台线程中执行登录流程"""
            try:
                # 先进行网络诊断
                if status_callback:
                    status_callback("正在诊断网络连接...")
                
                if not self._check_github_accessibility(status_callback):
                    on_complete(AuthResult(
                        success=False,
                        error="无法连接到 GitHub\n\n请检查：\n"
                              "1. 网络连接是否正常\n"
                              "2. 是否需要配置代理\n"
                              "3. 防火墙是否阻止了 GitHub 访问\n\n"
                              "如果需要配置代理，请在终端中执行：\n"
                              "set HTTP_PROXY=http://proxy.example.com:port\n"
                              "set HTTPS_PROXY=http://proxy.example.com:port"
                    ))
                    return
                
                # 使用web方式启动GitHub CLI登录
                # gh auth login --web --hostname github.com 会打开浏览器，用户在浏览器中完成授权
                cmd = ["gh", "auth", "login", "--web", "--hostname", "github.com", "--git-protocol", "https"]
                
                if status_callback:
                    status_callback("正在启动GitHub CLI web登录...")
                    print(f"执行命令: {' '.join(cmd)}")
                
                # 在新进程中启动登录命令
                encoding = 'gbk' if sys.platform == 'win32' else 'utf-8'
                
                # Windows下不使用CREATE_NO_WINDOW，让浏览器能正常打开
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding=encoding,
                    errors='ignore',
                )
                
                if status_callback:
                    status_callback(f"进程已启动 (PID: {process.pid})")
                
                # 检查进程是否启动成功
                if process.poll() is not None:
                    # 进程已经结束
                    stdout, stderr = process.communicate()
                    error_msg = stderr.strip() if stderr else stdout.strip()
                    if status_callback:
                        status_callback(f"启动失败: {error_msg}")
                    on_complete(AuthResult(
                        success=False,
                        error=f"GitHub CLI 启动失败: {error_msg}\n\n"
                              "可能的原因：\n"
                              "1. 网络连接问题\n"
                              "2. 代理配置错误\n"
                              "3. GitHub CLI 版本过旧"
                    ))
                    return
                
                if status_callback:
                    status_callback("浏览器已打开，请在浏览器中完成GitHub授权...")
                    status_callback("提示：授权成功后程序会自动继续，无需手动操作")
                
                # 实时读取输出
                import time
                start_time = time.time()
                while True:
                    # 检查进程是否结束
                    if process.poll() is not None:
                        break
                    
                    # 检查超时
                    if time.time() - start_time > 300:
                        process.terminate()
                        break
                    
                    # 短暂等待
                    time.sleep(1)
                
                # 获取进程输出
                stdout, stderr = process.communicate(timeout=5)
                if stderr:
                    print(f"GitHub CLI 错误输出: {stderr}")
                
                # 登录完成后，重新检查状态并获取token
                result = subprocess.run(
                    ["gh", "auth", "status"],
                    capture_output=True,
                    text=True,
                    encoding=encoding,
                    errors='ignore',
                    timeout=10
                )
                
                if result.returncode == 0:
                    if status_callback:
                        status_callback("登录成功，正在获取Token...")
                    # 调用获取token的方法
                    self._get_gh_cli_token(on_complete, status_callback)
                else:
                    if status_callback:
                        status_callback("登录未完成或已取消")
                    on_complete(AuthResult(
                        success=False,
                        error="登录未完成，请重试"
                    ))
                    
            except subprocess.TimeoutExpired:
                if status_callback:
                    status_callback("登录超时，请在浏览器中完成授权后重试")
                on_complete(AuthResult(
                    success=False,
                    error="登录超时，请重试"
                ))
            except Exception as e:
                print(f"自动登录异常: {e}")
                if status_callback:
                    status_callback(f"登录失败: {str(e)}")
                on_complete(AuthResult(
                    success=False,
                    error=f"自动登录失败: {str(e)}"
                ))
        
        # 在新线程中执行登录，避免阻塞UI
        login_thread = threading.Thread(target=login_worker, daemon=True)
        login_thread.start()
        
        return True
    
    def _check_github_accessibility(
        self,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """检查 GitHub 可访问性"""
        import socket
        try:
            if status_callback:
                status_callback("正在解析 github.com DNS...")
            
            # 检查 DNS 解析
            socket.gethostbyname('github.com')
            
            if status_callback:
                status_callback("DNS 解析成功")
            
            # 检查 HTTPS 连接
            if status_callback:
                status_callback("正在连接 GitHub...")
            
            response = self._client.get("https://github.com", timeout=10)
            
            if response.status_code == 200:
                if status_callback:
                    status_callback("GitHub 连接正常")
                return True
            else:
                if status_callback:
                    status_callback(f"GitHub 返回错误状态码: {response.status_code}")
                return False
                
        except socket.gaierror as e:
            if status_callback:
                status_callback(f"DNS 解析失败: {e}")
            return False
        except Exception as e:
            if status_callback:
                status_callback(f"连接 GitHub 失败: {e}")
            return False
    
    def _get_gh_cli_token(
        self,
        on_complete: Callable[[AuthResult], None],
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """从 GitHub CLI 获取访问令牌"""
        try:
            if status_callback:
                status_callback("正在从 GitHub CLI 获取 Token...")
            
            # 获取 token
            encoding = 'gbk' if sys.platform == 'win32' else 'utf-8'
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                encoding=encoding,
                errors='ignore',
                timeout=30
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                if status_callback:
                    status_callback(f"获取 Token 失败: {error_msg}")
                on_complete(AuthResult(
                    success=False,
                    error=f"获取 GitHub CLI token 失败: {error_msg}\n请确保已在终端中完成 'gh auth login'"
                ))
                return False
            
            access_token = result.stdout.strip()
            
            if not access_token:
                if status_callback:
                    status_callback("获取的 Token 为空")
                on_complete(AuthResult(
                    success=False,
                    error="获取的 Token 为空，请检查 GitHub CLI 配置"
                ))
                return False
            
            if status_callback:
                status_callback(f"Token 获取成功，长度: {len(access_token)} 字符")
                status_callback("正在验证 Token 有效性...")
            
            # 获取用户信息
            user_info = self._get_user_info(access_token, status_callback)
            
            if not user_info:
                on_complete(AuthResult(
                    success=False,
                    error="获取用户信息失败，请检查网络连接或 Token 有效性"
                ))
                return False
            
            credential = GitHubCredential(
                access_token=access_token,
                scope="repo,read:user",
                username=user_info.get("login"),
                user_id=user_info.get("id"),
                avatar_url=user_info.get("avatar_url"),
            )
            
            # 保存凭证
            credential_manager.save_credential(credential)
            
            if status_callback:
                status_callback(f"Token 验证成功，用户: {user_info.get('login')}")
                status_callback("正在保存登录信息...")
            
            on_complete(AuthResult(
                success=True,
                credential=credential
            ))
            return True
            
        except subprocess.TimeoutExpired:
            if status_callback:
                status_callback("获取 Token 超时（30秒）")
            on_complete(AuthResult(
                success=False,
                error="获取 Token 超时，请重试"
            ))
            return False
        except Exception as e:
            print(f"获取 GitHub CLI token 失败: {e}")
            on_complete(AuthResult(success=False, error=str(e)))
            return False
    
    def _get_user_info(
        self,
        access_token: str,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[dict]:
        """获取GitHub用户信息"""
        try:
            response = self._client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                if status_callback:
                    status_callback(f"获取用户信息失败: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"获取用户信息失败: {e}")
            if status_callback:
                status_callback(f"获取用户信息失败: {str(e)}")
            return None
    
    def open_terminal_for_login(self) -> bool:
        """打开终端窗口让用户完成GitHub CLI登录"""
        try:
            cmd = 'gh auth login'
            
            if sys.platform == 'win32':  # Windows
                # 使用 CREATE_NEW_CONSOLE 创建新控制台窗口
                try:
                    subprocess.Popen(
                        ['cmd', '/k', cmd],
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                except (AttributeError, OSError):
                    # 如果 CREATE_NEW_CONSOLE 不可用，使用 start 命令
                    subprocess.Popen(
                        ['start', 'cmd', '/k', cmd],
                        shell=True
                    )
            else:  # Linux/macOS
                subprocess.Popen(
                    ['gnome-terminal', '--', 'bash', '-c', f'{cmd}; exec bash'],
                    shell=False
                )
            
            print("已打开终端窗口，请在其中完成登录。")
            return True
            
        except Exception as e:
            print(f"打开终端失败: {e}")
            return False
    
    def logout(self) -> bool:
        """登出"""
        success = credential_manager.delete_credential()
        if success:
            print("已登出")
            
            # 同时登出 GitHub CLI
            try:
                encoding = 'gbk' if sys.platform == 'win32' else 'utf-8'
                subprocess.run(
                    ['gh', 'auth', 'logout', '-h', 'github.com'],
                    capture_output=True,
                    text=True,
                    encoding=encoding,
                    errors='ignore',
                    timeout=10
                )
            except Exception:
                pass
            
        return success
    
    def refresh_user_info(self) -> Optional[GitHubCredential]:
        """刷新用户信息"""
        credential = credential_manager.load_credential()
        if not credential:
            return None
        
        user_info = self._get_user_info(credential.access_token)
        if user_info:
            credential.username = user_info.get("login")
            credential.user_id = user_info.get("id")
            credential.avatar_url = user_info.get("avatar_url")
            credential_manager.save_credential(credential)
        
        return credential
    
    def get_repositories(self) -> list:
        """获取仓库列表"""
        credential = credential_manager.load_credential()
        if not credential:
            return []
        
        try:
            headers = {
                'Authorization': f'token {credential.access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'GitHub-Auto-Uploader'
            }
            
            repos = []
            page = 1
            while page <= 10:
                url = f'https://api.github.com/user/repos?per_page=100&page={page}&sort=updated&affiliation=owner,collaborator'
                response = self._client.get(url, headers=headers)
                
                if response.status_code != 200:
                    break
                
                data = response.json()
                
                if not data:
                    break
                
                for repo in data:
                    repos.append({
                        'name': repo['name'],
                        'full_name': repo['full_name'],
                        'clone_url': repo['clone_url'],
                        'default_branch': repo['default_branch'],
                        'private': repo['private'],
                        'updated_at': repo['updated_at']
                    })
                
                if len(data) < 100:
                    break
                page += 1
            
            return repos
            
        except Exception as e:
            print(f"获取仓库列表失败: {e}")
            return []
    
    def get_branches(self, owner: str, repo: str) -> list:
        """获取分支列表"""
        credential = credential_manager.load_credential()
        if not credential:
            return []
        
        try:
            headers = {
                'Authorization': f'token {credential.access_token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'GitHub-Auto-Uploader'
            }
            
            response = self._client.get(
                f'https://api.github.com/repos/{owner}/{repo}/branches?per_page=100',
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                return [branch['name'] for branch in data]
            
            return []
            
        except Exception:
            return []
    
    def get_token(self) -> Optional[str]:
        """获取访问令牌"""
        return credential_manager.get_access_token()
    
    def get_user_info_dict(self) -> Optional[dict]:
        """获取用户信息（字典格式，兼容旧代码）"""
        credential = credential_manager.load_credential()
        if not credential:
            return None
        
        return {
            'login': credential.username,
            'id': credential.user_id,
            'avatar_url': credential.avatar_url,
        }


# 全局认证管理器实例
github_auth = GitHubAuth()