import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QCheckBox, QPlainTextEdit,
    QFileDialog, QMessageBox, QGroupBox, QGridLayout, QSystemTrayIcon,
    QMenu, QStyle, QComboBox, QFrame, QSizePolicy, QScrollArea,
    QDateTimeEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QDateTime
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QPalette

from config_manager import ConfigManager
from git_manager import GitManager
from file_watcher import FileWatcher
from scheduler import UploadScheduler
from github_auth import GitHubAuth


class AuthWorker(QThread):
    progress = pyqtSignal(str)
    finished_signal = pyqtSignal(object)  # AuthResult
    
    def __init__(self, auth: GitHubAuth):
        super().__init__()
        self.auth = auth
    
    def run(self):
        try:
            def status_callback(msg):
                self.progress.emit(msg)
            
            def on_complete(result):
                self.finished_signal.emit(result)
            
            # 启用自动web登录
            self.auth.start_gh_cli_auth(on_complete, status_callback, auto_web_login=True)
        except Exception as e:
            from github_auth import AuthResult
            self.finished_signal.emit(AuthResult(success=False, error=f"授权过程出错: {str(e)}"))


class UploadWorker(QThread):
    progress = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, git_manager: GitManager, source_files: List[Path], 
                 stored_hashes: dict, username: str, token: str):
        super().__init__()
        self.git_manager = git_manager
        self.source_files = source_files
        self.stored_hashes = stored_hashes
        self.username = username
        self.token = token
        self.git_manager.set_progress_callback(self._on_progress)
    
    def _on_progress(self, message: str):
        self.progress.emit(message)
    
    def run(self):
        success, message, new_hashes = self.git_manager.sync_and_upload(
            self.source_files, self.stored_hashes, self.username, self.token
        )
        self.finished_signal.emit(success, message)
        self.new_hashes = new_hashes


class InitWorker(QThread):
    progress = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, git_manager: GitManager, username: str, email: str, token: str):
        super().__init__()
        self.git_manager = git_manager
        self.username = username
        self.email = email
        self.token = token
        self.git_manager.set_progress_callback(self._on_progress)
    
    def _on_progress(self, message: str):
        self.progress.emit(message)
    
    def run(self):
        success, message = self.git_manager.init_repository(
            self.username, self.email, self.token
        )
        self.finished_signal.emit(success, message)


class StyledButton(QPushButton):
    def __init__(self, text, color="#4361ee", parent=None):
        super().__init__(text, parent)
        self._base_color = color
        self._update_style()
    
    def _update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._base_color};
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {self._lighten_color(self._base_color)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(self._base_color)};
            }}
            QPushButton:disabled {{
                background-color: #dee2e6;
                color: #adb5bd;
            }}
        """)
    
    @staticmethod
    def _lighten_color(hex_color):
        color_map = {
            "#4361ee": "#5a73ff",
            "#3a0ca3": "#4d1ab8",
            "#7209b7": "#8a2bc7",
            "#f72585": "#ff4d9e",
            "#4cc9f0": "#6dd6f3",
            "#6c757d": "#868e96"
        }
        return color_map.get(hex_color, hex_color)
    
    @staticmethod
    def _darken_color(hex_color):
        color_map = {
            "#4361ee": "#3651d9",
            "#3a0ca3": "#2d0a8e",
            "#7209b7": "#5a0797",
            "#f72585": "#d61d6e",
            "#4cc9f0": "#3ab0d0",
            "#6c757d": "#5c636a"
        }
        return color_map.get(hex_color, hex_color)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.github_auth = GitHubAuth()
        self.git_manager: Optional[GitManager] = None
        self.file_watcher = FileWatcher()
        self.scheduler = UploadScheduler()
        self.upload_worker: Optional[UploadWorker] = None
        self.init_worker: Optional[InitWorker] = None
        self.auth_worker: Optional[AuthWorker] = None
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._repos: List[dict] = []
        
        self.setWindowTitle("GitHub自动上传工具")
        self.setMinimumSize(1100, 900)
        
        # 加载窗口位置和大小
        self._restore_window_geometry()
        
        self._setup_styles()
        self._setup_ui()
        self._setup_tray()
        self._load_config()
        self._setup_auto_check()
        
        # 检查认证状态
        is_auth = self.github_auth.is_authenticated()
        print(f"认证状态: {is_auth}")
        
        # 强制显示窗口（确保可见）
        print("强制显示窗口...")
        self.show()
        self.raise_()
        self.activateWindow()
        print("窗口初始化完成")
        
        # 延迟加载仓库列表（在窗口显示后）
        if is_auth:
            print("将在窗口显示后加载仓库列表...")
            QTimer.singleShot(100, self._load_repositories)  # 100ms后加载
        else:
            print("未登录，跳过自动加载仓库列表")
    
    def _restore_window_geometry(self):
        config = self.config_manager.config
        
        # 获取屏幕信息
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        
        # 检查保存的位置是否在屏幕内
        x, y = config.window_x, config.window_y
        width, height = config.window_width, config.window_height
        
        # 如果窗口位置在屏幕外，重置到屏幕中心
        if (x < screen_geometry.left() or 
            x > screen_geometry.right() or
            y < screen_geometry.top() or 
            y > screen_geometry.bottom()):
            print(f"警告: 窗口位置 ({x}, {y}) 不在屏幕内，重置到中心")
            x = (screen_geometry.width() - width) // 2 + screen_geometry.left()
            y = (screen_geometry.height() - height) // 2 + screen_geometry.top()
            config.window_x = x
            config.window_y = y
        
        self.move(config.window_x, config.window_y)
        self.resize(config.window_width, config.window_height)
        
        if config.window_maximized:
            self.showMaximized()
        
        print(f"窗口位置: ({self.x()}, {self.y()})")
        print(f"窗口大小: {self.width()}x{self.height()}")
    
    def _save_window_geometry(self):
        config = self.config_manager.config
        if not self.isMaximized():
            config.window_x = self.x()
            config.window_y = self.y()
            config.window_width = self.width()
            config.window_height = self.height()
        config.window_maximized = self.isMaximized()
        self.config_manager.save()
    
    def closeEvent(self, event):
        self._save_window_geometry()
        super().closeEvent(event)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 延迟保存，避免频繁写入
        if hasattr(self, '_resize_timer'):
            self._resize_timer.stop()
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._save_window_geometry)
        self._resize_timer.start(500)
    
    def moveEvent(self, event):
        super().moveEvent(event)
        # 延迟保存
        if hasattr(self, '_move_timer'):
            self._move_timer.stop()
        self._move_timer = QTimer(self)
        self._move_timer.setSingleShot(True)
        self._move_timer.timeout.connect(self._save_window_geometry)
        self._move_timer.start(500)
    
    def _setup_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f8f9fa;
            }
            QGroupBox {
                font-weight: 600;
                border: none;
                border-radius: 12px;
                margin-top: 16px;
                padding: 20px;
                background-color: white;
                color: #1a1a2e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
                padding: 0 12px;
                color: #1a1a2e;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel {
                color: #2d3436;
                font-size: 14px;
            }
            QLineEdit {
                padding: 12px 16px;
                border: 2px solid #e9ecef;
                border-radius: 8px;
                font-size: 14px;
                background-color: #f8f9fa;
                min-height: 24px;
                selection-background-color: #4361ee;
            }
            QLineEdit:focus {
                border-color: #4361ee;
                background-color: white;
            }
            QLineEdit:hover {
                border-color: #ced4da;
            }
            QComboBox {
                padding: 12px 16px;
                border: 2px solid #e9ecef;
                border-radius: 8px;
                font-size: 14px;
                background-color: #f8f9fa;
                min-height: 24px;
                min-width: 250px;
            }
            QComboBox:focus {
                border-color: #4361ee;
            }
            QComboBox:hover {
                border-color: #ced4da;
            }
            QComboBox::drop-down {
                border: none;
                width: 36px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 6px solid transparent;
                border-right: 6px solid transparent;
                border-top: 7px solid #6c757d;
                margin-right: 12px;
            }
            QComboBox QAbstractItemView {
                border: 2px solid #e9ecef;
                border-radius: 8px;
                background-color: white;
                selection-background-color: #4361ee;
                selection-color: white;
                padding: 8px;
            }
            QSpinBox {
                padding: 12px 16px;
                border: 2px solid #e9ecef;
                border-radius: 8px;
                font-size: 14px;
                background-color: #f8f9fa;
                min-height: 24px;
            }
            QSpinBox:focus {
                border-color: #4361ee;
            }
            QSpinBox:hover {
                border-color: #ced4da;
            }
            QCheckBox {
                font-size: 14px;
                spacing: 10px;
                color: #2d3436;
            }
            QCheckBox::indicator {
                width: 22px;
                height: 22px;
                border-radius: 6px;
                border: 2px solid #e9ecef;
                background-color: #f8f9fa;
            }
            QCheckBox::indicator:hover {
                border-color: #ced4da;
            }
            QCheckBox::indicator:checked {
                background-color: #4361ee;
                border-color: #4361ee;
            }
            QPlainTextEdit {
                border: 2px solid #e9ecef;
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 13px;
                background-color: #f8f9fa;
                selection-background-color: #4361ee;
            }
            QPlainTextEdit:focus {
                border-color: #4361ee;
                background-color: white;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #f1f3f5;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #adb5bd;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #868e96;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #f1f3f5;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #adb5bd;
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #868e96;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
    
    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(24)
        main_layout.setContentsMargins(32, 32, 32, 32)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(24)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # 顶部标题栏
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #4361ee, stop:0.5 #3a0ca3, stop:1 #7209b7);
                border-radius: 16px;
            }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(32, 28, 32, 28)
        header_layout.setSpacing(8)
        
        title_label = QLabel("GitHub 自动上传工具")
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: white;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title_label)
        
        subtitle_label = QLabel("智能同步配置文件到 GitHub 仓库")
        subtitle_label.setStyleSheet("color: rgba(255,255,255,0.95); font-size: 15px;")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(subtitle_label)
        
        scroll_layout.addWidget(header_frame)
        
        # 主内容区域 - 使用网格布局
        content_widget = QWidget()
        content_layout = QGridLayout(content_widget)
        content_layout.setSpacing(24)
        content_layout.setColumnStretch(0, 1)
        content_layout.setColumnStretch(1, 1)
        
        # 左侧列
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setSpacing(24)
        
        # GitHub 账号卡片
        auth_card = self._create_card("🔐 GitHub 账号")
        auth_layout = QVBoxLayout()
        auth_layout.setSpacing(16)
        
        auth_info_frame = QFrame()
        auth_info_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border-radius: 8px;
                padding: 16px;
            }
        """)
        auth_info_layout = QHBoxLayout(auth_info_frame)
        auth_info_layout.setContentsMargins(16, 12, 16, 12)
        
        self.auth_status_label = QLabel("状态: 未登录")
        self.auth_status_label.setStyleSheet("font-size: 15px; color: #6c757d; font-weight: 500;")
        auth_info_layout.addWidget(self.auth_status_label)
        auth_info_layout.addStretch()
        
        auth_layout.addWidget(auth_info_frame)
        
        auth_btn_layout = QHBoxLayout()
        auth_btn_layout.setSpacing(12)
        
        self.auth_btn = StyledButton("登录 GitHub", "#4361ee")
        self.auth_btn.setMinimumHeight(48)
        auth_btn_layout.addWidget(self.auth_btn)
        self.auth_btn.clicked.connect(self._start_auth)
        
        self.logout_btn = StyledButton("退出登录", "#6c757d")
        self.logout_btn.setMinimumHeight(48)
        auth_btn_layout.addWidget(self.logout_btn)
        self.logout_btn.clicked.connect(self._logout)
        self.logout_btn.setVisible(False)
        
        auth_layout.addLayout(auth_btn_layout)
        auth_card.setLayout(auth_layout)
        left_layout.addWidget(auth_card)
        
        # 文件夹设置卡片
        folder_card = self._create_card("📁 文件夹设置")
        folder_layout = QVBoxLayout()
        folder_layout.setSpacing(16)
        
        folder_input_layout = QHBoxLayout()
        folder_input_layout.setSpacing(12)
        
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("请选择包含配置文件的文件夹...")
        self.folder_input.setMinimumHeight(48)
        folder_input_layout.addWidget(self.folder_input)
        
        self.browse_btn = StyledButton("浏览", "#f72585")
        self.browse_btn.setMinimumWidth(100)
        self.browse_btn.setMinimumHeight(48)
        self.browse_btn.clicked.connect(self._browse_folder)
        folder_input_layout.addWidget(self.browse_btn)
        
        folder_layout.addLayout(folder_input_layout)
        
        folder_hint = QLabel("💡 支持的文件: ACL4SSR_Online_FullyamI, all.yaml, base64.txt, bdg.yaml, mihomo.yaml")
        folder_hint.setStyleSheet("color: #6c757d; font-size: 13px; padding: 8px 0;")
        folder_layout.addWidget(folder_hint)
        
        folder_card.setLayout(folder_layout)
        left_layout.addWidget(folder_card)
        
        # 右侧列
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setSpacing(24)
        
        # GitHub 仓库设置卡片
        repo_card = self._create_card("📦 GitHub 仓库设置")
        repo_layout = QVBoxLayout()
        repo_layout.setSpacing(16)
        
        # 仓库选择
        repo_row = QHBoxLayout()
        repo_row.setSpacing(12)
        
        repo_label = QLabel("选择仓库:")
        repo_label.setFixedWidth(90)
        repo_label.setStyleSheet("font-weight: 600;")
        repo_row.addWidget(repo_label)
        
        self.repo_combo = QComboBox()
        self.repo_combo.setEnabled(False)
        self.repo_combo.currentIndexChanged.connect(self._on_repo_selected)
        repo_row.addWidget(self.repo_combo)
        
        self.refresh_repos_btn = StyledButton("🔄", "#6c757d")
        self.refresh_repos_btn.setFixedWidth(48)
        self.refresh_repos_btn.setMinimumHeight(48)
        self.refresh_repos_btn.clicked.connect(self._load_repositories)
        self.refresh_repos_btn.setEnabled(False)
        repo_row.addWidget(self.refresh_repos_btn)
        
        repo_layout.addLayout(repo_row)
        
        # 分支选择
        branch_row = QHBoxLayout()
        branch_row.setSpacing(12)
        
        branch_label = QLabel("选择分支:")
        branch_label.setFixedWidth(90)
        branch_label.setStyleSheet("font-weight: 600;")
        branch_row.addWidget(branch_label)
        
        self.branch_combo = QComboBox()
        self.branch_combo.setEnabled(False)
        branch_row.addWidget(self.branch_combo)
        
        self.init_btn = StyledButton("初始化", "#4cc9f0")
        self.init_btn.setFixedWidth(100)
        self.init_btn.setMinimumHeight(48)
        self.init_btn.clicked.connect(self._init_repository)
        self.init_btn.setEnabled(False)
        branch_row.addWidget(self.init_btn)
        
        repo_layout.addLayout(branch_row)
        repo_card.setLayout(repo_layout)
        right_layout.addWidget(repo_card)
        
        # 定时上传设置卡片
        schedule_card = self._create_card("⏰ 定时上传设置")
        schedule_layout = QVBoxLayout()
        schedule_layout.setSpacing(16)
        
        # 上传间隔
        interval_row = QHBoxLayout()
        interval_row.setSpacing(12)
        
        interval_label = QLabel("上传间隔:")
        interval_label.setFixedWidth(90)
        interval_label.setStyleSheet("font-weight: 600;")
        interval_row.addWidget(interval_label)
        
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 168)
        self.interval_spin.setValue(6)
        self.interval_spin.setSuffix(" 小时")
        self.interval_spin.setMinimumHeight(48)
        interval_row.addWidget(self.interval_spin)
        
        interval_hint = QLabel("建议: 6-12 小时")
        interval_hint.setStyleSheet("color: #6c757d; font-size: 13px;")
        interval_row.addWidget(interval_hint)
        interval_row.addStretch()
        
        schedule_layout.addLayout(interval_row)
        
        # 复选框
        checkbox_row = QHBoxLayout()
        checkbox_row.setSpacing(40)
        
        self.auto_start_check = QCheckBox("开机自动启动（暂未启用）")
        self.auto_start_check.setStyleSheet("QCheckBox { font-size: 14px; }")
        checkbox_row.addWidget(self.auto_start_check)
        
        self.minimize_tray_check = QCheckBox("最小化到系统托盘")
        self.minimize_tray_check.setChecked(True)
        self.minimize_tray_check.setStyleSheet("QCheckBox { font-size: 14px; }")
        checkbox_row.addWidget(self.minimize_tray_check)
        checkbox_row.addStretch()
        
        schedule_layout.addLayout(checkbox_row)
        schedule_card.setLayout(schedule_layout)
        right_layout.addWidget(schedule_card)
        
        # 添加到网格布局
        content_layout.addWidget(left_column, 0, 0)
        content_layout.addWidget(right_column, 0, 1)
        
        scroll_layout.addWidget(content_widget)
        
        # 操作按钮区域
        action_card = self._create_card("🚀 操作控制")
        action_layout = QVBoxLayout()
        action_layout.setSpacing(16)
        
        # 开始任务设置
        task_row = QHBoxLayout()
        task_row.setSpacing(16)
        
        task_label = QLabel("首次上传时间:")
        task_label.setFixedWidth(110)
        task_label.setStyleSheet("font-weight: 600;")
        task_row.addWidget(task_label)
        
        self.first_upload_datetime = QDateTimeEdit()
        self.first_upload_datetime.setDateTime(QDateTime.currentDateTime().addSecs(60))
        self.first_upload_datetime.setCalendarPopup(True)
        self.first_upload_datetime.setDisplayFormat("yyyy年MM月dd日 HH:mm:ss")
        self.first_upload_datetime.setMinimumHeight(48)
        task_row.addWidget(self.first_upload_datetime)
        
        self.set_now_btn = StyledButton("⚡ 设置为当前+10秒", "#6c757d")
        self.set_now_btn.setFixedWidth(140)
        self.set_now_btn.setMinimumHeight(48)
        self.set_now_btn.clicked.connect(self._set_current_time_plus_10s)
        task_row.addWidget(self.set_now_btn)
        
        self.start_task_btn = StyledButton("📅 开始任务", "#4cc9f0")
        self.start_task_btn.setMinimumHeight(48)
        self.start_task_btn.clicked.connect(self._start_task)
        task_row.addWidget(self.start_task_btn)
        
        action_layout.addLayout(task_row)
        
        # 任务控制按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)
        
        self.stop_task_btn = StyledButton("⏹ 停止任务", "#f72585")
        self.stop_task_btn.setMinimumHeight(52)
        self.stop_task_btn.clicked.connect(self._stop_task)
        self.stop_task_btn.setEnabled(False)
        btn_row.addWidget(self.stop_task_btn)
        
        action_layout.addLayout(btn_row)
        
        # 状态信息
        status_row = QHBoxLayout()
        status_row.setSpacing(32)
        
        self.status_label = QLabel("状态: 未开始")
        self.status_label.setStyleSheet("font-size: 15px; color: #6c757d; font-weight: 500;")
        status_row.addWidget(self.status_label)
        
        self.next_upload_label = QLabel("下次上传: --")
        self.next_upload_label.setStyleSheet("font-size: 15px; color: #6c757d; font-weight: 500;")
        status_row.addWidget(self.next_upload_label)
        
        self.last_upload_label = QLabel("上次上传: --")
        self.last_upload_label.setStyleSheet("font-size: 15px; color: #6c757d; font-weight: 500;")
        status_row.addWidget(self.last_upload_label)
        status_row.addStretch()
        
        action_layout.addLayout(status_row)
        
        # 统计信息
        stats_row = QHBoxLayout()
        stats_row.setSpacing(32)
        
        self.total_count_label = QLabel("累计上传: 0 次")
        self.total_count_label.setStyleSheet("font-size: 15px; color: #6c757d; font-weight: 500;")
        stats_row.addWidget(self.total_count_label)
        
        self.success_count_label = QLabel("成功: 0 次")
        self.success_count_label.setStyleSheet("font-size: 15px; color: #28a745; font-weight: 500;")
        stats_row.addWidget(self.success_count_label)
        
        self.failed_count_label = QLabel("失败: 0 次")
        self.failed_count_label.setStyleSheet("font-size: 15px; color: #dc3545; font-weight: 500;")
        stats_row.addWidget(self.failed_count_label)
        stats_row.addStretch()
        
        action_layout.addLayout(stats_row)
        action_card.setLayout(action_layout)
        scroll_layout.addWidget(action_card)
        
        # 日志区域
        log_card = self._create_card("📝 运行日志")
        log_layout = QVBoxLayout()
        log_layout.setSpacing(12)
        
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(1000)
        self.log_text.setMinimumHeight(200)
        log_layout.addWidget(self.log_text)
        
        log_btn_row = QHBoxLayout()
        log_btn_row.addStretch()
        
        clear_btn = StyledButton("清空日志", "#6c757d")
        clear_btn.setFixedWidth(120)
        clear_btn.setMinimumHeight(40)
        clear_btn.clicked.connect(self._clear_log)
        log_btn_row.addWidget(clear_btn)
        
        log_layout.addLayout(log_btn_row)
        log_card.setLayout(log_layout)
        scroll_layout.addWidget(log_card, stretch=1)
        
        # 保存配置按钮
        self.save_config_btn = StyledButton("💾 保存配置", "#4361ee")
        self.save_config_btn.setMinimumHeight(52)
        self.save_config_btn.clicked.connect(self._save_config)
        scroll_layout.addWidget(self.save_config_btn)
        
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)
    
    def _create_card(self, title: str) -> QGroupBox:
        card = QGroupBox(title)
        card.setStyleSheet("""
            QGroupBox {
                font-weight: 700;
                border: none;
                border-radius: 16px;
                margin-top: 20px;
                padding: 24px;
                background-color: white;
                color: #1a1a2e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 24px;
                padding: 0 16px;
                color: #1a1a2e;
                font-size: 16px;
                font-weight: 700;
            }
        """)
        return card
    
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        
        self.tray_icon = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("GitHub自动上传工具")
        
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #e0e0e0;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 25px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2196F3;
                color: white;
            }
        """)
        
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.showNormal)
        tray_menu.addAction(show_action)
        
        tray_menu.addSeparator()
        
        upload_action = QAction("立即上传", self)
        upload_action.triggered.connect(self._upload_now)
        tray_menu.addAction(upload_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit_application)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()
    
    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.raise_()
            self.activateWindow()
    
    def _setup_auto_check(self):
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)
    
    def _update_status(self):
        if self.scheduler.is_running():
            remaining = self.scheduler.get_remaining_time()
            if remaining:
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                self.next_upload_label.setText(f"下次上传: {hours}小时{minutes}分钟后")
        
        if self.config_manager.config.last_upload_time:
            self.last_upload_label.setText(f"上次上传: {self.config_manager.config.last_upload_time}")
    
    def _load_config(self):
        config = self.config_manager.config
        self.folder_input.setText(config.target_folder)
        self.interval_spin.setValue(config.upload_interval_hours)
        self.auto_start_check.setChecked(config.auto_start)
        self.minimize_tray_check.setChecked(config.minimize_to_tray)
        
        if config.last_upload_time:
            self.last_upload_label.setText(f"上次上传: {config.last_upload_time}")
        
        # 加载统计信息
        self.total_count_label.setText(f"累计上传: {config.total_upload_count} 次")
        self.success_count_label.setText(f"成功: {config.success_upload_count} 次")
        self.failed_count_label.setText(f"失败: {config.failed_upload_count} 次")
        
        user_info = self.github_auth.get_user_info_dict()
        if user_info:
            username = user_info.get('login', '')
            self.auth_status_label.setText(f"状态: 已登录 ({username})")
            self.auth_status_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")
            self.auth_btn.setVisible(False)
            self.logout_btn.setVisible(True)
        
        if config.target_folder and Path(config.target_folder).exists():
            self._init_git_manager()
        
        # 注意：自动启动功能已移除，现在需要用户手动点击"开始任务"按钮并设置首次上传时间
        # if config.auto_start and config.target_folder and config.repo_full_name:
        #     self._start_monitoring()
    
    def _start_auth(self):
        self.auth_btn.setEnabled(False)
        self._log("开始GitHub授权流程...")
        self._log("正在检查GitHub CLI登录状态...")
        
        self.auth_worker = AuthWorker(self.github_auth)
        self.auth_worker.progress.connect(self._log)
        self.auth_worker.finished_signal.connect(self._on_auth_finished)
        self.auth_worker.start()
    
    def _on_auth_finished(self, result):
        from github_auth import AuthResult
        self.auth_btn.setEnabled(True)
        
        if isinstance(result, AuthResult) and result.success:
            username = result.credential.username if result.credential else ""
            self.auth_status_label.setText(f"状态: 已登录 ({username})")
            self.auth_status_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")
            self.auth_btn.setVisible(False)
            self.logout_btn.setVisible(True)
            self._log("授权成功")
            self._load_repositories()
        elif isinstance(result, AuthResult) and result.error == "NOT_LOGGED_IN":
            self._log("GitHub CLI 未登录，需要用户手动登录")
            self._show_login_dialog()
        else:
            error_msg = result.error if isinstance(result, AuthResult) else str(result)
            self._log(f"授权失败: {error_msg}")
            
            # 如果是登录超时或未完成，提供更友好的提示
            if "超时" in error_msg or "未完成" in error_msg:
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("登录提示")
                msg_box.setText("浏览器已打开，请在浏览器中完成GitHub授权")
                msg_box.setInformativeText("授权完成后，请点击下方按钮重新检测")
                msg_box.setIcon(QMessageBox.Icon.Information)
                
                retry_btn = msg_box.addButton("重新检测", QMessageBox.ButtonRole.ActionRole)
                cancel_btn = msg_box.addButton(QMessageBox.StandardButton.Cancel)
                
                msg_box.exec()
                
                if msg_box.clickedButton() == retry_btn:
                    self._start_auth()
            else:
                QMessageBox.critical(self, "授权失败", error_msg)
    
    def _show_login_dialog(self):
        """显示登录对话框，提示用户在浏览器中完成登录"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("等待登录")
        msg_box.setText("GitHub CLI 未登录")
        msg_box.setInformativeText("选择登录方式完成GitHub授权")
        msg_box.setIcon(QMessageBox.Icon.Information)
        
        # 添加"打开浏览器登录（推荐）"按钮
        web_login_btn = msg_box.addButton("🌐 打开浏览器登录（推荐）", QMessageBox.ButtonRole.ActionRole)
        # 添加"打开终端登录"按钮
        terminal_login_btn = msg_box.addButton("💻 打开终端登录", QMessageBox.ButtonRole.ActionRole)
        # 添加"测试网络连接"按钮
        test_network_btn = msg_box.addButton("🔍 测试网络连接", QMessageBox.ButtonRole.ActionRole)
        # 添加"重新检测"按钮
        retry_btn = msg_box.addButton("🔄 重新检测登录状态", QMessageBox.ButtonRole.ActionRole)
        # 添加"查看帮助"按钮
        help_btn = msg_box.addButton("❓ 查看帮助", QMessageBox.ButtonRole.ActionRole)
        # 添加取消按钮
        cancel_btn = msg_box.addButton(QMessageBox.StandardButton.Cancel)
        
        msg_box.exec()
        
        # 如果用户点击了"打开浏览器登录"
        if msg_box.clickedButton() == web_login_btn:
            self._log("正在启动浏览器登录...")
            # 使用web方式自动登录
            def on_complete(result):
                self._on_auth_finished(result)
            
            def status_callback(msg):
                self._log(msg)
            
            self.github_auth.start_gh_cli_auth(on_complete, status_callback, auto_web_login=True)
        # 如果用户点击了"打开终端登录"
        elif msg_box.clickedButton() == terminal_login_btn:
            success, message = self.github_auth.open_terminal_for_login()
            if success:
                self._log(message)
                # 再次显示对话框
                self._show_login_dialog()
            else:
                QMessageBox.critical(self, "错误", message)
        # 如果用户点击了"测试网络连接"
        elif msg_box.clickedButton() == test_network_btn:
            self._test_network_connection()
            # 再次显示对话框
            self._show_login_dialog()
        # 如果用户点击了"重新检测"
        elif msg_box.clickedButton() == retry_btn:
            self._start_auth()
        # 如果用户点击了"查看帮助"
        elif msg_box.clickedButton() == help_btn:
            self._show_login_help()
    
    def _test_network_connection(self):
        """测试网络连接"""
        self._log("开始测试网络连接...")
        
        import socket
        try:
            # 测试 DNS 解析
            self._log("正在解析 github.com DNS...")
            socket.gethostbyname('github.com')
            self._log("✅ DNS 解析成功")
            
            # 测试 HTTPS 连接
            self._log("正在连接 GitHub...")
            try:
                from httpx import Client
                client = Client(timeout=10)
                response = client.get("https://github.com")
                if response.status_code == 200:
                    self._log("✅ GitHub 连接正常")
                    QMessageBox.information(
                        self, 
                        "网络测试成功", 
                        "网络连接正常！\n\n可以尝试重新登录。"
                    )
                else:
                    self._log(f"❌ GitHub 返回状态码: {response.status_code}")
                    QMessageBox.warning(
                        self, 
                        "网络测试警告", 
                        f"可以连接到 GitHub，但返回状态码: {response.status_code}\n\n请稍后重试。"
                    )
                client.close()
            except Exception as e:
                self._log(f"❌ 连接 GitHub 失败: {e}")
                QMessageBox.warning(
                    self, 
                    "网络连接失败", 
                    f"无法连接到 GitHub！\n\n错误: {str(e)}\n\n请查看帮助了解更多信息。"
                )
        except socket.gaierror as e:
            self._log(f"❌ DNS 解析失败: {e}")
            QMessageBox.critical(
                self, 
                "DNS 解析失败", 
                f"无法解析 github.com！\n\n错误: {str(e)}\n\n请检查：\n1. 网络连接\n2. DNS 设置\n3. 代理配置"
            )
        except Exception as e:
            self._log(f"❌ 网络测试失败: {e}")
            QMessageBox.critical(
                self, 
                "网络测试失败", 
                f"网络测试失败！\n\n错误: {str(e)}"
            )
    
    def _show_login_help(self):
        """显示登录帮助信息"""
        help_text = """GitHub CLI 登录帮助

【推荐方式】浏览器登录（自动）
1. 点击"打开浏览器登录"按钮
2. 浏览器会自动打开 GitHub 授权页面
3. 在浏览器中登录你的 GitHub 账号
4. 授权成功后，程序会自动获取登录状态

【备用方式】终端登录
1. 点击"打开终端登录"按钮
2. 在终端中执行：gh auth login
3. 按照提示选择：
   - What account do you want to log into? -> GitHub.com
   - What is your preferred protocol? -> HTTPS
   - Authenticate Git with your GitHub credentials? -> Yes
   - How would you like to authenticate? -> Login with a web browser

【常见问题排查】

⚠️ 错误：error connecting to github.com

这个错误表示无法连接到 GitHub，请按以下步骤排查：

1. 网络连接检查
   - 在浏览器中打开 https://github.com 测试
   - 确认可以正常访问

2. 代理配置（如果需要）
   如果您使用代理，请配置环境变量：
   
   在 PowerShell 中：
   $env:HTTP_PROXY="http://proxy.example.com:port"
   $env:HTTPS_PROXY="http://proxy.example.com:port"
   
   在 CMD 中：
   set HTTP_PROXY=http://proxy.example.com:port
   set HTTPS_PROXY=http://proxy.example.com:port
   
   或者为 Git 配置代理：
   git config --global http.proxy http://proxy.example.com:port
   git config --global https.proxy http://proxy.example.com:port

3. 检查防火墙/安全软件
   - 确保防火墙允许访问 GitHub
   - 检查杀毒软件是否阻止连接
   - 尝试临时关闭安全软件测试

4. DNS 解析问题
   - 尝试使用公共 DNS 服务器：
     * 8.8.8.8 (Google DNS)
     * 1.1.1.1 (Cloudflare DNS)
   - 修改网络适配器的 DNS 设置

5. 检查 VPN/代理软件
   - 关闭所有 VPN 软件
   - 关闭其他代理工具（如 Clash、V2Ray 等）
   - 如果必须使用代理，请确保配置正确

6. GitHub 服务状态
   - 访问 https://githubstatus.com
   - 确认 GitHub 服务是否正常运行

7. 其他问题
   - 确认系统时间是否正确
   - 尝试重启计算机
   - 检查是否有其他程序占用端口

【手动验证连接】
在终端中执行以下命令测试：
ping github.com
curl -I https://github.com

【快速解决方案】
如果以上方法都无法解决，可以尝试：
1. 使用手机热点连接网络
2. 更换网络环境
3. 联系网络管理员"""
        
        QMessageBox.information(self, "登录帮助", help_text)
    
    def _logout(self):
        if self.github_auth.logout():
            self.auth_status_label.setText("状态: 未登录")
            self.auth_status_label.setStyleSheet("font-size: 14px; color: #666;")
            self.auth_btn.setVisible(True)
            self.logout_btn.setVisible(False)
            self.repo_combo.clear()
            self.repo_combo.setEnabled(False)
            self.branch_combo.clear()
            self.branch_combo.setEnabled(False)
            self.refresh_repos_btn.setEnabled(False)
            self.init_btn.setEnabled(False)
            self._log("已退出登录")
    
    def _load_repositories(self):
        if not self.github_auth.is_authenticated():
            self._log("未登录，无法获取仓库列表")
            return
        
        self._log("正在获取仓库列表...")
        print("开始获取仓库列表...")
        self._repos = self.github_auth.get_repositories()
        print(f"获取到 {len(self._repos)} 个仓库")
        
        self.repo_combo.clear()
        self.repo_combo.addItem("请选择仓库...", "")
        
        for repo in self._repos:
            # 使用 [P] 替代 emoji 避免Windows上的字体渲染问题导致的崩溃
            display_text = f"[P] {repo['full_name']}" if repo['private'] else repo['full_name']
            self.repo_combo.addItem(display_text, repo['full_name'])
        
        self.repo_combo.setEnabled(True)
        self.refresh_repos_btn.setEnabled(True)
        self._log(f"已加载 {len(self._repos)} 个仓库")
        
        config = self.config_manager.config
        if config.repo_full_name:
            index = self.repo_combo.findData(config.repo_full_name)
            if index >= 0:
                self.repo_combo.setCurrentIndex(index)
    
    def _on_repo_selected(self, index):
        if index <= 0:
            self.branch_combo.clear()
            self.branch_combo.setEnabled(False)
            self.init_btn.setEnabled(False)
            return
        
        repo_full_name = self.repo_combo.currentData()
        repo_info = next((r for r in self._repos if r['full_name'] == repo_full_name), None)
        
        if not repo_info:
            return
        
        self._log(f"正在获取分支列表: {repo_full_name}")
        
        owner, repo_name = repo_full_name.split('/')
        branches = self.github_auth.get_branches(owner, repo_name)
        
        self.branch_combo.clear()
        for branch in branches:
            self.branch_combo.addItem(branch)
        
        default_branch = repo_info.get('default_branch', 'main')
        default_index = self.branch_combo.findText(default_branch)
        if default_index >= 0:
            self.branch_combo.setCurrentIndex(default_index)
        
        self.branch_combo.setEnabled(True)
        self.init_btn.setEnabled(True)
        
        self._save_config()
    
    def _save_config(self):
        repo_full_name = self.repo_combo.currentData() if self.repo_combo.currentIndex() > 0 else ""
        branch = self.branch_combo.currentText() if self.branch_combo.count() > 0 else "main"
        
        repo_url = ""
        if repo_full_name:
            repo_info = next((r for r in self._repos if r['full_name'] == repo_full_name), None)
            if repo_info:
                repo_url = repo_info.get('clone_url', '')
        
        user_info = self.github_auth.get_user_info_dict()
        git_username = user_info.get('login', '') if user_info else ''
        git_email = user_info.get('email', '') if user_info else ''
        
        success = self.config_manager.update(
            target_folder=self.folder_input.text(),
            repo_full_name=repo_full_name,
            repo_url=repo_url,
            branch=branch,
            git_username=git_username,
            git_email=git_email,
            upload_interval_hours=self.interval_spin.value(),
            auto_start=self.auto_start_check.isChecked(),
            minimize_to_tray=self.minimize_tray_check.isChecked()
        )
        
        if success:
            self._log("配置已保存")
            QMessageBox.information(self, "成功", "配置已保存")
        
        return success
    
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if folder:
            self.folder_input.setText(folder)
            self._save_config()
    
    def _init_git_manager(self):
        target_folder = self.folder_input.text()
        if not target_folder:
            return
        
        repo_url = ""
        repo_full_name = self.repo_combo.currentData() if self.repo_combo.count() > 0 else ""
        if repo_full_name:
            repo_info = next((r for r in self._repos if r['full_name'] == repo_full_name), None)
            if repo_info:
                repo_url = repo_info.get('clone_url', '')
        
        if not repo_url and self.config_manager.config.repo_url:
            repo_url = self.config_manager.config.repo_url
        
        if not repo_url:
            return
        
        repo_path = Path(target_folder) / ".git_repo"
        self.git_manager = GitManager(
            repo_url=repo_url,
            local_path=str(repo_path),
            branch=self.branch_combo.currentText() if self.branch_combo.count() > 0 else "main"
        )
    
    def _init_repository(self):
        if not self.folder_input.text():
            QMessageBox.warning(self, "错误", "请先选择目标文件夹")
            return
        
        if self.repo_combo.currentIndex() <= 0:
            QMessageBox.warning(self, "错误", "请选择仓库")
            return
        
        self._init_git_manager()
        
        user_info = self.github_auth.get_user_info_dict()
        username = user_info.get('login', '') if user_info else ''
        email = user_info.get('email', '') if user_info else ''
        token = self.github_auth.get_token() or ''
        
        self.init_btn.setEnabled(False)
        self._log("开始初始化仓库...")
        
        self.init_worker = InitWorker(
            self.git_manager,
            username,
            email,
            token
        )
        self.init_worker.progress.connect(self._log)
        self.init_worker.finished_signal.connect(self._on_init_finished)
        self.init_worker.start()
    
    def _on_init_finished(self, success: bool, message: str):
        self.init_btn.setEnabled(True)
        if success:
            self._log(f"仓库初始化成功: {message}")
            QMessageBox.information(self, "成功", message)
        else:
            self._log(f"仓库初始化失败: {message}")
            QMessageBox.critical(self, "错误", message)
    
    def _on_file_changed(self, filename: str):
        self._log(f"检测到文件变更: {filename}")
    
    def _scheduled_upload(self):
        self._log("定时任务触发上传")
        self._perform_upload()
    
    def _upload_now(self):
        if not self.git_manager:
            QMessageBox.warning(self, "错误", "请先初始化仓库")
            return
        
        self._log("手动触发上传")
        self._perform_upload()
    
    def _perform_upload(self):
        if self.upload_worker and self.upload_worker.isRunning():
            self._log("上传任务正在进行中...")
            return
        
        target_files = self.config_manager.get_target_files()
        if not target_files:
            self._log("没有找到需要上传的文件")
            return
        
        user_info = self.github_auth.get_user_info_dict()
        username = user_info.get('login', '') if user_info else ''
        token = self.github_auth.get_token() or ''
        
        self.upload_worker = UploadWorker(
            self.git_manager,
            target_files,
            self.config_manager.config.file_hashes,
            username,
            token
        )
        self.upload_worker.progress.connect(self._log)
        self.upload_worker.finished_signal.connect(self._on_upload_finished)
        self.upload_worker.start()
    
    def _on_upload_finished(self, success: bool, message: str):
        
        config = self.config_manager.config
        config.total_upload_count += 1
        
        if success:
            self._log(f"上传成功: {message}")
            config.success_upload_count += 1
            self.config_manager.update_last_upload_time()
            
            if hasattr(self.upload_worker, 'new_hashes'):
                for filename, file_hash in self.upload_worker.new_hashes.items():
                    self.config_manager.set_file_hash(filename, file_hash)
            
            # 调度器会自动在下一次上传完成后设置下次上传时间
            if self.scheduler.is_running():
                next_time = self.scheduler.get_next_run_time()
                if next_time:
                    self._log(f"下次上传时间: {next_time.strftime('%Y年%m月%d日 %H:%M:%S')}")
            
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "上传成功",
                    f"文件已成功上传到GitHub\n{message}",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
        else:
            self._log(f"上传失败: {message}")
            config.failed_upload_count += 1
            
            # 上传失败，调度器仍然会按照预定时间尝试下一次上传
            if self.scheduler.is_running():
                self._log("上传失败，将按预定时间重试")
            
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "上传失败",
                    message,
                    QSystemTrayIcon.MessageIcon.Warning,
                    3000
                )
        
        self.config_manager.save()
        self._update_stats_display()
    
    def _update_stats_display(self):
        config = self.config_manager.config
        self.total_count_label.setText(f"累计上传: {config.total_upload_count} 次")
        self.success_count_label.setText(f"成功: {config.success_upload_count} 次")
        self.failed_count_label.setText(f"失败: {config.failed_upload_count} 次")
    
    def _set_current_time_plus_10s(self):
        """设置首次上传时间为当前时间+10秒，方便开发者快速测试"""
        current_time = QDateTime.currentDateTime()
        target_time = current_time.addSecs(10)
        self.first_upload_datetime.setDateTime(target_time)
        self._log(f"已设置首次上传时间为当前时间+10秒: {target_time.toString('yyyy年MM月dd日 HH:mm:ss')}")
    
    def _start_task(self):
        if not self.folder_input.text():
            QMessageBox.warning(self, "错误", "请先选择目标文件夹")
            return
        
        if not self.git_manager or not self.git_manager.is_initialized():
            QMessageBox.warning(self, "错误", "请先初始化仓库")
            return
        
        target_time = self.first_upload_datetime.dateTime().toPyDateTime()
        current_time = QDateTime.currentDateTime().toPyDateTime()
        
        if target_time <= current_time:
            QMessageBox.warning(self, "错误", "首次上传时间必须大于当前时间")
            return
        
        time_diff = (target_time - current_time).total_seconds()
        config = self.config_manager.config
        
        if not config.first_upload_time:
            config.first_upload_time = target_time.strftime("%Y年%m月%d日 %H:%M:%S")
            self.config_manager.save()
        
        self._log(f"任务已安排，将在 {target_time.strftime('%Y年%m月%d日 %H:%M:%S')} 开始首次上传")
        self._log(f"首次上传后，将每隔 {self.interval_spin.value()} 小时自动上传一次")
        self._log("已启动文件监控，检测到文件变化将触发上传")
        
        # 启动文件监控
        target_path = Path(self.folder_input.text())
        self.file_watcher.start(
            target_path,
            config.files_to_upload,
            self._on_file_changed
        )
        
        # 使用 QTimer 触发首次上传（不在调度器中执行首次上传）
        QTimer.singleShot(int(time_diff * 1000), self._perform_first_upload)
        
        # 更新UI状态
        self.start_task_btn.setEnabled(False)
        self.start_task_btn.setText("📅 任务运行中")
        self.stop_task_btn.setEnabled(True)
        self.status_label.setText("状态: 运行中")
        self.status_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")
        
        self._save_config()
    
    def _perform_first_upload(self):
        """执行首次上传"""
        self._log("开始执行首次上传...")
        self._perform_upload()
        
        # 首次上传完成后，启动周期性调度器
        self._log("首次上传完成，启动周期性调度...")
        self.scheduler.start(
            self.interval_spin.value(),
            self._scheduled_upload
        )
        self._log(f"已启动周期性调度，每隔 {self.interval_spin.value()} 小时自动上传")
    
    def _stop_task(self):
        """停止整个任务（文件监控 + 调度器）"""
        self.file_watcher.stop()
        self.scheduler.stop()
        
        self.start_task_btn.setEnabled(True)
        self.start_task_btn.setText("📅 开始任务")
        self.stop_task_btn.setEnabled(False)
        self.status_label.setText("状态: 已停止")
        self.status_label.setStyleSheet("font-size: 14px; color: #666;")
        self.next_upload_label.setText("下次上传: --")
        self._log("任务已停止")
    
    def _reset_task_button(self):
        """重置任务按钮状态"""
        self.start_task_btn.setEnabled(True)
        self.start_task_btn.setText("📅 开始任务")
    
    def _clear_log(self):
        self.log_text.clear()
    
    def _log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{timestamp}] {message}")
    
    def closeEvent(self, event):
        if self.minimize_tray_check.isChecked() and self.tray_icon:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "GitHub自动上传工具",
                "程序已最小化到系统托盘，双击图标可恢复窗口",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            self._quit_application()
    
    def _quit_application(self):
        self._stop_task()
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()
