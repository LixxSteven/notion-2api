import sys
import os
import signal
import json
import re
from typing import Dict
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                               QTextEdit, QSystemTrayIcon, QMenu, QMessageBox,
                               QGroupBox, QFormLayout, QStyle, QDialog, QCheckBox, 
                               QTabWidget, QFrame)
from PySide6.QtCore import QProcess, Qt, QSize, Slot, QThread, Signal, QTimer
from PySide6.QtGui import QIcon, QAction, QTextCursor, QClipboard, QTextCharFormat, QColor
from app.utils.cookie_extractor import try_all_browsers, CookieError
from app.utils.config_manager import ConfigManager
from app.utils.logger import get_logger
from app.utils.notifier import notify_service_started, notify_service_stopped

# 获取 logger
logger = get_logger(__name__)

# --- 手动引导对话框 ---
class ManualGuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动获取 Notion Cookie")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel("📋 手动获取步骤")
        title.setStyleSheet("font-size: 16px; font-weight: 600; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # 步骤说明
        steps = """
<ol style='line-height: 1.8;'>
<li>打开浏览器，访问 <b>notion.so</b> 并登录</li>
<li>按 <b>F12</b> 打开开发者工具</li>
<li>切换到 <b>Application</b> 标签（Chrome/Edge）或 <b>存储</b> 标签（Firefox）</li>
<li>左侧找到 <b>Cookies</b> → <b>https://www.notion.so</b></li>
<li>找到 <b>token_v2</b>，双击复制值（通常以 v02: 开头）</li>
</ol>
        """
        
        steps_label = QTextEdit()
        steps_label.setHtml(steps)
        steps_label.setReadOnly(True)
        steps_label.setMaximumHeight(250)
        layout.addWidget(steps_label)
        
        # 剪贴板粘贴按钮
        self.paste_btn = QPushButton("从剪贴板粘贴")
        self.paste_btn.clicked.connect(self.paste_from_clipboard)
        layout.addWidget(self.paste_btn)
        
        # 结果显示
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self.cookie_value = None
    
    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        
        if not text:
            self.result_label.setText("❌ 剪贴板为空")
            self.result_label.setStyleSheet("color: #f44336;")
            return
        
        # 验证是否像 token_v2
        if text.startswith("v02:") and len(text) > 100:
            self.cookie_value = text
            self.result_label.setText(f"✅ 已检测到有效 Cookie（长度: {len(text)}）")
            self.result_label.setStyleSheet("color: #4caf50;")
            QTimer.singleShot(1000, self.accept)
        else:
            self.result_label.setText("⚠️ 内容不像 token_v2（应以 v02: 开头且长度 > 100）")
            self.result_label.setStyleSheet("color: #ff9800;")

# --- 测试工作线程 ---
class TestWorker(QThread):
    response_signal = Signal(str)
    finished_signal = Signal()
    error_signal = Signal(str)

    def __init__(self, port, message):
        super().__init__()
        self.port = port
        self.message = message
        self._is_running = True

    def run(self):
        url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer 1"
        }
        data = {
            "model": "claude-opus-4.5", 
            "messages": [{"role": "user", "content": self.message}],
            "stream": True
        }
        
        try:
            import requests
            response = requests.post(url, headers=headers, json=data, stream=True, timeout=60)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not self._is_running: break
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith("data: "):
                        content = decoded[6:]
                        if content == "[DONE]":
                            break
                        try:
                            json_data = json.loads(content)
                            delta = json_data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                self.response_signal.emit(delta)
                        except:
                            pass
        except Exception as e:
            self.error_signal.emit(f"Error: {str(e)}")
        finally:
            self.finished_signal.emit()

    def stop(self):
        self._is_running = False


# --- 主窗口 ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Notion AI 本地代理")
        self.resize(1000, 750)
        
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_all()
        self.process = None
        self.clipboard_monitoring = False
        self.last_clipboard_text = ""
        
        self.init_ui()
        self.init_tray()
        self.apply_modern_style()
        
        # 初始加载配置
        self.load_config_to_ui()
        
        # 剪贴板监听定时器
        self.clipboard_timer = QTimer()
        self.clipboard_timer.timeout.connect(self.check_clipboard)
        self.clipboard_timer.setInterval(1000)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 顶部栏
        header = self.create_header()
        layout.addWidget(header)
        
        # 标签页
        self.tabs = QTabWidget()
        self.tabs.setObjectName("main_tabs")
        
        # 主页
        main_page = self.create_main_page()
        self.tabs.addTab(main_page, "控制台")
        
        # 设置页
        settings_page = self.create_settings_page()
        self.tabs.addTab(settings_page, "设置")
        
        layout.addWidget(self.tabs)

    def create_header(self):
        """创建顶部栏"""
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(70)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(30, 15, 30, 15)
        
        # 标题
        title = QLabel("Notion AI 本地代理")
        title.setObjectName("app_title")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # 状态指示器
        self.status_badge = QLabel("已停止")
        self.status_badge.setObjectName("status_stopped")
        layout.addWidget(self.status_badge)
        
        return header

    def create_main_page(self):
        """创建主页"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(20)
        
        # Cookie 配置区
        cookie_group = QGroupBox("Notion Cookie")
        cookie_group.setObjectName("section")
        cookie_layout = QVBoxLayout()
        cookie_layout.setSpacing(12)
        
        # Cookie 输入行
        cookie_input_layout = QHBoxLayout()
        cookie_input_layout.setSpacing(10)
        
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("token_v2 (点击右侧按钮自动获取)")
        self.cookie_input.setObjectName("input")
        self.cookie_input.setMinimumHeight(40)
        
        self.btn_auto_cookie = QPushButton("自动获取")
        self.btn_auto_cookie.setObjectName("secondary_btn")
        self.btn_auto_cookie.setFixedWidth(100)
        self.btn_auto_cookie.setFixedHeight(40)
        self.btn_auto_cookie.clicked.connect(self.auto_load_cookie)
        
        self.btn_save_cookie = QPushButton("保存")
        self.btn_save_cookie.setObjectName("primary_btn")
        self.btn_save_cookie.setFixedWidth(80)
        self.btn_save_cookie.setFixedHeight(40)
        self.btn_save_cookie.clicked.connect(self.save_cookie_only)
        
        cookie_input_layout.addWidget(self.cookie_input)
        cookie_input_layout.addWidget(self.btn_auto_cookie)
        cookie_input_layout.addWidget(self.btn_save_cookie)
        cookie_layout.addLayout(cookie_input_layout)
        
        # 剪贴板监听
        self.clipboard_checkbox = QCheckBox("启用剪贴板监听（自动检测 v02: 开头的 token）")
        self.clipboard_checkbox.stateChanged.connect(self.toggle_clipboard_monitoring)
        cookie_layout.addWidget(self.clipboard_checkbox)
        
        cookie_group.setLayout(cookie_layout)
        layout.addWidget(cookie_group)
        
        # 服务控制区
        control_group = QGroupBox("服务控制")
        control_group.setObjectName("section")
        control_layout = QVBoxLayout()
        control_layout.setSpacing(15)
        
        # 端口设置
        port_layout = QHBoxLayout()
        port_label = QLabel("服务端口")
        port_label.setFixedWidth(80)
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("8088")
        self.port_input.setObjectName("input")
        self.port_input.setFixedWidth(150)
        self.port_input.setFixedHeight(40)
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_input)
        port_layout.addStretch()
        control_layout.addLayout(port_layout)
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        
        self.btn_start = QPushButton("启动服务")
        self.btn_start.setObjectName("primary_btn")
        self.btn_start.setMinimumHeight(45)
        self.btn_start.clicked.connect(self.toggle_service)
        
        self.btn_stop = QPushButton("停止服务")
        self.btn_stop.setObjectName("danger_btn")
        self.btn_stop.setMinimumHeight(45)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_service)
        
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        control_layout.addLayout(btn_layout)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # 日志区
        log_group = QGroupBox("运行日志")
        log_group.setObjectName("section")
        log_layout = QVBoxLayout()
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setObjectName("log_area")
        self.log_area.setMinimumHeight(200)
        log_layout.addWidget(self.log_area)
        
        # 日志按钮
        log_btn_layout = QHBoxLayout()
        log_btn_layout.addStretch()
        
        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setObjectName("text_btn")
        self.btn_clear_log.clicked.connect(lambda: self.log_area.clear())
        
        self.btn_copy_log = QPushButton("复制")
        self.btn_copy_log.setObjectName("text_btn")
        self.btn_copy_log.clicked.connect(lambda: self.log_area.selectAll() or self.log_area.copy())
        
        log_btn_layout.addWidget(self.btn_clear_log)
        log_btn_layout.addWidget(self.btn_copy_log)
        log_layout.addLayout(log_btn_layout)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # API 测试区
        test_group = QGroupBox("API 测试")
        test_group.setObjectName("section")
        test_layout = QVBoxLayout()
        
        test_input_layout = QHBoxLayout()
        test_input_layout.setSpacing(10)
        
        self.test_input = QLineEdit()
        self.test_input.setText("你是谁？我的邮箱是什么？")
        self.test_input.setObjectName("input")
        self.test_input.setMinimumHeight(40)
        self.test_input.returnPressed.connect(self.send_test_message)
        
        self.btn_test_send = QPushButton("发送测试")
        self.btn_test_send.setObjectName("secondary_btn")
        self.btn_test_send.clicked.connect(self.send_test_message)
        self.btn_test_send.setFixedWidth(100)
        self.btn_test_send.setFixedHeight(40)
        
        test_input_layout.addWidget(self.test_input)
        test_input_layout.addWidget(self.btn_test_send)
        test_layout.addLayout(test_input_layout)
        
        self.test_response = QTextEdit()
        self.test_response.setReadOnly(True)
        self.test_response.setPlaceholderText("AI 回复将显示在这里...")
        self.test_response.setObjectName("log_area")
        self.test_response.setMinimumHeight(120)
        test_layout.addWidget(self.test_response)
        
        test_group.setLayout(test_layout)
        layout.addWidget(test_group)
        
        layout.addStretch()
        
        return page

    def create_settings_page(self):
        """创建设置页"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(20)
        
        # Notion 配置
        notion_group = QGroupBox("Notion 配置")
        notion_group.setObjectName("section")
        form_layout = QFormLayout()
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        self.space_id_input = QLineEdit()
        self.space_id_input.setObjectName("input")
        self.space_id_input.setMinimumHeight(40)
        form_layout.addRow("Space ID:", self.space_id_input)
        
        self.user_id_input = QLineEdit()
        self.user_id_input.setObjectName("input")
        self.user_id_input.setMinimumHeight(40)
        form_layout.addRow("User ID:", self.user_id_input)
        
        notion_group.setLayout(form_layout)
        layout.addWidget(notion_group)
        
        # 保存按钮
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        
        self.btn_save = QPushButton("保存配置")
        self.btn_save.setObjectName("primary_btn")
        self.btn_save.setFixedWidth(150)
        self.btn_save.setMinimumHeight(45)
        self.btn_save.clicked.connect(self.save_config)
        
        save_layout.addWidget(self.btn_save)
        layout.addLayout(save_layout)
        
        layout.addStretch()
        
        return page

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        
        # 双击托盘图标显示窗口
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        tray_menu = QMenu()
        
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show)
        
        self.tray_service_action = QAction("启动服务", self)
        self.tray_service_action.triggered.connect(self.toggle_service_from_tray)
        
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close_app)
        
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self.tray_service_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()
    
    def toggle_service_from_tray(self):
        """从托盘切换服务状态"""
        if self.process is None:
            self.start_service()
            self.tray_service_action.setText("停止服务")
        else:
            self.stop_service()
            self.tray_service_action.setText("启动服务")

    def apply_modern_style(self):
        """应用现代专业主题样式"""
        style = """
        QMainWindow {
            background-color: #0f1419;
        }
        
        #header {
            background-color: #1a1f26;
            border-bottom: 1px solid #2d333b;
        }
        
        #app_title {
            font-size: 20px;
            font-weight: 600;
            color: #e6edf3;
        }
        
        #status_stopped {
            color: #ff6b6b;
            font-size: 13px;
            font-weight: 600;
            padding: 6px 16px;
            background-color: rgba(255, 107, 107, 0.15);
            border-radius: 12px;
            border: 1px solid rgba(255, 107, 107, 0.3);
        }
        
        #status_running {
            color: #51cf66;
            font-size: 13px;
            font-weight: 600;
            padding: 6px 16px;
            background-color: rgba(81, 207, 102, 0.15);
            border-radius: 12px;
            border: 1px solid rgba(81, 207, 102, 0.3);
        }
        
        QTabWidget#main_tabs {
            background-color: #0f1419;
            border: none;
        }
        
        QTabWidget#main_tabs::pane {
            border: none;
            background-color: #0f1419;
        }
        
        QTabWidget#main_tabs::tab-bar {
            left: 30px;
        }
        
        QTabBar::tab {
            background-color: transparent;
            color: #8b949e;
            padding: 12px 24px;
            margin-right: 8px;
            border: none;
            font-size: 14px;
            font-weight: 500;
        }
        
        QTabBar::tab:selected {
            color: #e6edf3;
            border-bottom: 2px solid #4493f8;
        }
        
        QTabBar::tab:hover {
            color: #c9d1d9;
        }
        
        QGroupBox#section {
            background-color: #1a1f26;
            border: 1px solid #2d333b;
            border-radius: 8px;
            padding: 20px;
            margin-top: 10px;
            font-size: 14px;
            font-weight: 600;
            color: #8b949e;
        }
        
        QGroupBox#section::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px;
        }
        
        QLineEdit#input {
            background-color: #0d1117;
            border: 1.5px solid #2d333b;
            border-radius: 6px;
            padding: 0 14px;
            color: #e6edf3;
            font-size: 13px;
        }
        
        QLineEdit#input:focus {
            border: 1.5px solid #4493f8;
            background-color: #161b22;
        }
        
        QLineEdit#input::placeholder {
            color: #6e7681;
        }
        
        QPushButton#primary_btn {
            background-color: #238636;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0 20px;
            font-weight: 600;
            font-size: 14px;
        }
        
        QPushButton#primary_btn:hover {
            background-color: #2ea043;
        }
        
        QPushButton#primary_btn:pressed {
            background-color: #1a7f37;
        }
        
        QPushButton#secondary_btn {
            background-color: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 0 20px;
            font-weight: 500;
            font-size: 13px;
        }
        
        QPushButton#secondary_btn:hover {
            background-color: #30363d;
            border-color: #484f58;
        }
        
        QPushButton#danger_btn {
            background-color: #da3633;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0 20px;
            font-weight: 600;
            font-size: 14px;
        }
        
        QPushButton#danger_btn:hover {
            background-color: #f85149;
        }
        
        QPushButton#danger_btn:disabled {
            background-color: #21262d;
            color: #484f58;
        }
        
        QPushButton#text_btn {
            background-color: transparent;
            color: #8b949e;
            border: none;
            padding: 6px 12px;
            font-size: 13px;
        }
        
        QPushButton#text_btn:hover {
            color: #c9d1d9;
            background-color: rgba(255, 255, 255, 0.05);
        }
        
        QTextEdit#log_area {
            background-color: #0d1117;
            border: 1.5px solid #2d333b;
            border-radius: 6px;
            padding: 12px;
            color: #8b949e;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.5;
        }
        
        QCheckBox {
            color: #8b949e;
            spacing: 8px;
            font-size: 13px;
        }
        
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1.5px solid #30363d;
            background-color: #0d1117;
        }
        
        QCheckBox::indicator:checked {
            background-color: #238636;
            border-color: #238636;
        }
        
        QCheckBox::indicator:hover {
            border-color: #4493f8;
        }
        
        QLabel {
            color: #c9d1d9;
        }
        
        QFormLayout QLabel {
            color: #8b949e;
            font-weight: 500;
            font-size: 13px;
        }
        
        QScrollBar:vertical {
            background-color: #0d1117;
            width: 10px;
            border-radius: 5px;
        }
        
        QScrollBar::handle:vertical {
            background-color: #30363d;
            border-radius: 5px;
            min-height: 30px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #484f58;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        """
        self.setStyleSheet(style)

    def load_config_to_ui(self):
        self.cookie_input.setText(self.config.get("token_v2", ""))
        self.space_id_input.setText(self.config.get("space_id", ""))
        self.user_id_input.setText(self.config.get("user_id", ""))
        self.port_input.setText(self.config.get("port", "8088"))

    def toggle_clipboard_monitoring(self, state):
        """切换剪贴板监听"""
        self.clipboard_monitoring = (state == Qt.Checked)
        if self.clipboard_monitoring:
            self.clipboard_timer.start()
            self.last_clipboard_text = QApplication.clipboard().text()
        else:
            self.clipboard_timer.stop()

    def check_clipboard(self):
        """检查剪贴板内容"""
        if not self.clipboard_monitoring:
            return
        
        clipboard = QApplication.clipboard()
        current_text = clipboard.text().strip()
        
        if current_text == self.last_clipboard_text:
            return
        
        self.last_clipboard_text = current_text
        
        if current_text.startswith("v02:") and len(current_text) > 100:
            self.cookie_input.setText(current_text)
            QMessageBox.information(self, "✅ 已检测到 Cookie", 
                                  f"已自动填入 token_v2（长度: {len(current_text)}）\n请记得点击'保存配置'。")

    def auto_load_cookie(self):
        """自动获取 Cookie"""
        cookie, error_type, error_msg = try_all_browsers()
        
        if cookie:
            self.cookie_input.setText(cookie)
            QMessageBox.information(self, "✅ 成功", "已成功读取 token_v2！\n请记得点击'保存配置'。")
        else:
            error_messages = {
                CookieError.DATABASE_LOCKED: "浏览器正在运行，请关闭所有浏览器窗口后重试",
                CookieError.PERMISSION_DENIED: "没有权限读取浏览器数据，请以管理员身份运行",
                CookieError.FILE_NOT_FOUND: "找不到浏览器 Cookie 文件，请确认已安装 Chrome/Edge/Firefox",
                CookieError.COOKIE_NOT_FOUND: "未找到 Notion Cookie，请确认已登录 notion.so",
            }
            
            msg = error_messages.get(error_type, f"自动获取失败：{error_msg}")
            
            reply = QMessageBox.question(
                self, "❌ 自动获取失败", 
                f"{msg}\n\n是否查看手动获取教程？",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.show_manual_guide()

    def show_manual_guide(self):
        """显示手动引导对话框"""
        dialog = ManualGuideDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.cookie_value:
            self.cookie_input.setText(dialog.cookie_value)
            QMessageBox.information(self, "✅ 成功", "Cookie 已填入，请记得点击'保存配置'。")

    def save_config(self):
        new_config = {
            "token_v2": self.cookie_input.text().strip(),
            "space_id": self.space_id_input.text().strip(),
            "user_id": self.user_id_input.text().strip(),
            "port": self.port_input.text().strip() or "8088"
        }
        self.config_manager.update(new_config)
        logger.info("配置已保存")
        
        # 如果服务正在运行，提示重启
        if self.process:
            reply = QMessageBox.question(
                self, "配置已更新", 
                "配置已保存。服务正在运行，需要重启以应用新配置。\n\n是否立即重启服务？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.restart_service()
        else:
            QMessageBox.information(self, "💾 保存成功", "配置已更新。")
    
    def save_cookie_only(self):
        """只保存 Cookie 配置"""
        cookie = self.cookie_input.text().strip()
        
        if not cookie:
            QMessageBox.warning(self, "⚠️ 警告", "Cookie 不能为空！")
            return
        
        # 验证 Token 格式
        if not (cookie.startswith("v02:") or cookie.startswith("v03:")):
            reply = QMessageBox.question(
                self, "⚠️ 格式警告",
                f"Cookie 格式可能不正确。\n\n标准格式应以 v02: 或 v03: 开头。\n当前值：{cookie[:30]}...\n\n是否仍要保存？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        # 保存到配置文件
        current_config = self.config_manager.get_all()
        current_config["token_v2"] = cookie
        self.config_manager.update(current_config)
        logger.info(f"Cookie 已保存，长度: {len(cookie)}")
        
        # 如果服务正在运行，提示重启
        if self.process:
            reply = QMessageBox.question(
                self, "💾 保存成功", 
                "Cookie 已保存。服务正在运行，需要重启以应用新配置。\n\n是否立即重启服务？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.restart_service()
        else:
            QMessageBox.information(self, "💾 保存成功", f"Cookie 已保存（长度: {len(cookie)}）")

    def toggle_service(self):
        if self.process is None:
            self.start_service()

    def start_service(self):
        # 获取虚拟环境 Python 路径
        venv_python = os.path.join(os.getcwd(), ".venv", "Scripts", "python.exe")
        if not os.path.exists(venv_python):
            QMessageBox.critical(self, "错误", f"找不到虚拟环境 Python:\n{venv_python}\n\n请确保已创建虚拟环境。")
            return
        
        # 打印日志文件路径
        from app.utils.logger import LOG_FILE
        log_msg = f"⏳ 正在启动服务 (Port: {self.port_input.text()})...\n📝 日志文件: {LOG_FILE}"
        self.log_area.append(log_msg)
        logger.info(f"启动服务，端口: {self.port_input.text().strip() or '8088'}")
        logger.info(f"日志文件: {LOG_FILE}")
        
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        
        port = self.port_input.text().strip() or "8088"
        cmd = venv_python
        args = ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", port]
        
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.finished.connect(self.process_finished)
        
        self.process.start(cmd, args)
        
        notify_service_started(port)
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_badge.setText("运行中")
        self.status_badge.setObjectName("status_running")
        self.status_badge.setStyleSheet(self.status_badge.styleSheet())

    def stop_service(self):
        if self.process:
            self.log_area.append("⏹️ 正在停止服务...")
            logger.info("停止服务")
            notify_service_stopped()
            self.process.terminate()
            if not self.process.waitForFinished(2000):
                self.process.kill()
    
    def restart_service(self):
        """重启服务"""
        self.log_area.append("🔄 正在重启服务...")
        logger.info("重启服务")
        if self.process:
            self.stop_service()
            # 等待进程完全停止后再启动
            QTimer.singleShot(1500, self.start_service)
        else:
            self.start_service()

    def process_finished(self):
        self.process = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_badge.setText("已停止")
        self.status_badge.setObjectName("status_stopped")
        self.status_badge.setStyleSheet(self.status_badge.styleSheet())
        self.log_area.append("✅ 服务已停止。")

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="ignore")
        
        # 去除 ANSI 颜色代码
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)
        
        # 检测 Token 失效错误
        if "TokenExpiredError" in text or "Token 已失效" in text:
            cursor = self.log_area.textCursor()
            cursor.movePosition(QTextCursor.End)
            
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#ff6b6b"))
            fmt.setFontWeight(700)
            
            cursor.insertText("\n❌ Token 已失效，请更新 token_v2\n", fmt)
            
            self.log_area.setTextCursor(cursor)
            self.log_area.moveCursor(QTextCursor.End)
            
            if self.process:
                self.stop_service()
            return
        
        logger.info(text.strip())
        
        self.log_area.moveCursor(QTextCursor.End)
        self.log_area.insertPlainText(text)
        self.log_area.moveCursor(QTextCursor.End)

    def closeEvent(self, event):
        # 关闭窗口时最小化到托盘
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Notion AI Proxy",
            "已最小化到系统托盘",
            QSystemTrayIcon.Information,
            2000
        )

    def close_app(self):
        """真正退出应用"""
        if self.process:
            reply = QMessageBox.question(self, '确认退出', "服务正在运行，退出将停止服务。确定要退出吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.stop_service()
                QApplication.quit()
        else:
            QApplication.quit()

    # --- 测试功能 ---
    def send_test_message(self):
        msg = self.test_input.text().strip()
        if not msg: return
        
        self.test_response.clear()
        self.test_response.append("⏳ 正在请求...")
        self.btn_test_send.setEnabled(False)
        self.test_input.setEnabled(False)
        
        port = self.port_input.text().strip() or "8088"
        self.test_worker = TestWorker(port, msg)
        self.test_worker.response_signal.connect(self.handle_test_response)
        self.test_worker.error_signal.connect(self.handle_test_error)
        self.test_worker.finished_signal.connect(self.handle_test_finished)
        self.test_worker.start()

    def handle_test_response(self, content):
        text = self.test_response.toPlainText()
        if "⏳ 正在请求..." in text:
             self.test_response.clear()
        self.test_response.moveCursor(QTextCursor.End)
        self.test_response.insertPlainText(content)
        self.test_response.moveCursor(QTextCursor.End)

    def handle_test_error(self, error):
        self.test_response.append(f"\n❌ {error}")

    def handle_test_finished(self):
        self.test_input.setEnabled(True)
        self.btn_test_send.setEnabled(True)
        self.test_input.setFocus()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())
