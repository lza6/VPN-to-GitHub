import sys
import os

os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
# 抑制 libpng 的 ICC 警告
os.environ['QT_IMAGEIO_DISABLE_WARNING'] = '1'

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from main_window import MainWindow


def main():
    print("正在初始化应用程序...")
    
    # 启用高DPI支持
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
    # PyQt6 高DPI设置
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    print("创建应用程序实例...")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # 设置全局字体
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    
    print("创建主窗口...")
    window = MainWindow()
    print(f"窗口标题: {window.windowTitle()}")
    print(f"窗口大小: {window.size()}")
    
    print("显示窗口...")
    window.show()
    print("窗口已显示")
    
    print("将窗口提升到前台...")
    window.raise_()
    window.activateWindow()
    print("窗口已激活")
    
    print("开始事件循环...")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
