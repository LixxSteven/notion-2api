import sys
import os
import signal
import json
import re
from typing import Dict
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                               QTextEdit, QSystemTrayIcon, QMenu, QMessageBox,
                               QGroupBox, QFormLayout, QStyle, QDialog, QCheckBox, QScrollArea)
from PySide6.QtCore import QProcess, Qt, QSize, Slot, QThread, Signal, QTimer
from PySide6.QtGui import QIcon, QAction, QTextCursor, QClipboard
from app.utils.cookie_extractor import try_all_browsers, CookieError

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
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #26a69a; margin-bottom: 10px;")
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
        self.paste_btn = QPushButton("📋 从剪贴板粘贴")
        self.paste_btn.clicked.connect(self.paste_from_clipboard)
        self.paste_btn.setStyleSheet("""
            QPushButton {
                background-color: #00838f;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00acc1;
            }
        """)
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

# --- 配置管理 ---
class ConfigManager:
    def __init__(self, env_path=".env"):
        self.env_path = env_path

    def load(self) -> Dict[str, str]:
        config = {}
        if os.path.exists(self.env_path):
            try:
                with open(self.env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            parts = line.split("=", 1)
                            key = parts[0].strip()
                            value = parts[1].strip().strip('"').strip("'")
                            config[key] = value
            except Exception as e:
                print(f"配置文件读取错误: {e}")
        return config

    def save(self, config: Dict[str, str]):
        lines = []
        if os.path.exists(self.env_path):
            with open(self.env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        new_lines = []
        keys_written = set()
        
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in config:
                    new_lines.append(f'{key}="{config[key]}"\n')
                    keys_written.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        # 追加新配置
        for key, value in config.items():
            if key not in keys_written and value:
                new_lines.append(f'{key}="{value}"\n')
                
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

# --- 主窗口 ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Notion AI 本地代理控制面板")
        self.resize(950, 850)
        
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
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
        self.clipboard_timer.setInterval(1000)  # 每秒检查一次

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 1. 标题和状态
        header_layout = QHBoxLayout()
        title_label = QLabel("🚀 Notion AI Proxy")
        title_label.setObjectName("title")
        header_layout.addWidget(title_label)
        
        self.status_badge = QLabel("● 已停止")
        self.status_badge.setObjectName("status_stopped")
        self.status_badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(self.status_badge)
        layout.addLayout(header_layout)
        
        # 2. 配置区域
        config_group = QGroupBox("服务配置")
        config_group.setObjectName("card")
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # Cookie
        cookie_layout = QHBoxLayout()
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("token_v2 (点击右侧按钮自动获取)")
        self.cookie_input.setObjectName("input")
        
        self.btn_auto_cookie = QPushButton("🔍 自动获取")
        self.btn_auto_cookie.setObjectName("primary_btn")
        self.btn_auto_cookie.setFixedWidth(120)
        self.btn_auto_cookie.clicked.connect(self.auto_load_cookie)
        
        cookie_layout.addWidget(self.cookie_input)
        cookie_layout.addWidget(self.btn_auto_cookie)
        form_layout.addRow("Notion Cookie:", cookie_layout)
        
        # 剪贴板监听开关
        self.clipboard_checkbox = QCheckBox("启用剪贴板监听（自动检测 v02: 开头的 token）")
        self.clipboard_checkbox.stateChanged.connect(self.toggle_clipboard_monitoring)
        form_layout.addRow("", self.clipboard_checkbox)
        
        # IDs
        self.space_id_input = QLineEdit()
        self.space_id_input.setObjectName("input")
        self.user_id_input = QLineEdit()
        self.user_id_input.setObjectName("input")
        form_layout.addRow("Space ID:", self.space_id_input)
        form_layout.addRow("User ID:", self.user_id_input)
        
        # Port
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("8088")
        self.port_input.setObjectName("input")
        form_layout.addRow("服务端口:", self.port_input)
        
        # 保存按钮
        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setObjectName("success_btn")
        self.btn_save.clicked.connect(self.save_config)
        form_layout.addRow("", self.btn_save)
        
        config_group.setLayout(form_layout)
        layout.addWidget(config_group)
        
        # 3. 控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)
        
        self.btn_start = QPushButton("▶️ 启动服务")
        self.btn_start.setObjectName("start_btn")
        self.btn_start.setMinimumHeight(50)
        self.btn_start.clicked.connect(self.toggle_service)
        
        self.btn_stop = QPushButton("⏹️ 停止服务")
        self.btn_stop.setObjectName("stop_btn")
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_service)
        
        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        layout.addLayout(control_layout)
        
        # 4. 日志区域
        log_group = QGroupBox("运行日志")
        log_group.setObjectName("card")
        log_layout = QVBoxLayout()
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setObjectName("log_area")
        self.log_area.setMaximumHeight(200)
        log_layout.addWidget(self.log_area)
        
        log_btns_layout = QHBoxLayout()
        self.btn_clear_log = QPushButton("🗑️ 清空")
        self.btn_clear_log.setObjectName("secondary_btn")
        self.btn_clear_log.clicked.connect(lambda: self.log_area.clear())
        
        self.btn_copy_log = QPushButton("📋 复制")
        self.btn_copy_log.setObjectName("secondary_btn")
        self.btn_copy_log.clicked.connect(lambda: self.log_area.selectAll() or self.log_area.copy())
        
        log_btns_layout.addStretch()
        log_btns_layout.addWidget(self.btn_clear_log)
        log_btns_layout.addWidget(self.btn_copy_log)
        log_layout.addLayout(log_btns_layout)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # 5. 测试区域
        test_group = QGroupBox("API 测试")
        test_group.setObjectName("card")
        test_layout = QVBoxLayout()
        
        input_layout = QHBoxLayout()
        self.test_input = QLineEdit()
        self.test_input.setPlaceholderText("输入测试消息，例如：你好")
        self.test_input.setObjectName("input")
        self.test_input.returnPressed.connect(self.send_test_message)
        
        self.btn_test_send = QPushButton("🚀 发送测试")
        self.btn_test_send.setObjectName("primary_btn")
        self.btn_test_send.clicked.connect(self.send_test_message)
        self.btn_test_send.setFixedWidth(120)
        
        input_layout.addWidget(self.test_input)
        input_layout.addWidget(self.btn_test_send)
        test_layout.addLayout(input_layout)
        
        self.test_response = QTextEdit()
        self.test_response.setReadOnly(True)
        self.test_response.setPlaceholderText("AI 回复将显示在这里...")
        self.test_response.setObjectName("log_area")
        self.test_response.setMaximumHeight(150)
        test_layout.addWidget(self.test_response)
        
        test_group.setLayout(test_layout)
        layout.addWidget(test_group)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        
        tray_menu = QMenu()
        show_action = QAction("显示面板", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close_app)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def apply_modern_style(self):
        """应用现代深色主题样式 - 专业仪表盘风格"""
        style = """
        QMainWindow, QWidget {
            background-color: #0f1419;
            color: #c9d1d9;
            font-family: 'Segoe UI', 'Microsoft YaHei', Arial, sans-serif;
            font-size: 13px;
        }
        
        #title {
            font-size: 26px;
            font-weight: 600;
            color: #ffffff;
            padding: 5px 0;
            letter-spacing: 0.5px;
        }
        
        #status_stopped {
            color: #ff6b6b;
            font-size: 14px;
            font-weight: 600;
            padding: 6px 14px;
            background-color: rgba(255, 107, 107, 0.15);
            border-radius: 16px;
            border: 1px solid rgba(255, 107, 107, 0.3);
        }
        
        #status_running {
            color: #51cf66;
            font-size: 14px;
            font-weight: 600;
            padding: 6px 14px;
            background-color: rgba(81, 207, 102, 0.15);
            border-radius: 16px;
            border: 1px solid rgba(81, 207, 102, 0.3);
        }
        
        QGroupBox {
            font-weight: 600;
            font-size: 14px;
            border: none;
            margin-top: 12px;
            padding-top: 12px;
        }
        
        QGroupBox#card {
            background-color: #1a1f26;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #2d333b;
        }
        
        QGroupBox::title {
            color: #74c0fc;
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px;
            font-weight: 600;
        }
        
        QLineEdit#input {
            background-color: #0f1419;
            border: 1.5px solid #2d333b;
            border-radius: 8px;
            padding: 10px 14px;
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
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #4493f8, stop:1 #3b82f6);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 18px;
            font-weight: 600;
            font-size: 13px;
        }
        
        QPushButton#primary_btn:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #539bf5, stop:1 #4493f8);
        }
        
        QPushButton#primary_btn:pressed {
            background: #2f6fdb;
        }
        
        QPushButton#success_btn {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #26a641, stop:1 #238636);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 18px;
            font-weight: 600;
            font-size: 13px;
        }
        
        QPushButton#success_btn:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #2ea043, stop:1 #26a641);
        }
        
        QPushButton#start_btn {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #26a641, stop:1 #238636);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }
        
        QPushButton#start_btn:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #2ea043, stop:1 #26a641);
            transform: translateY(-1px);
        }
        
        QPushButton#start_btn:disabled {
            background-color: #21262d;
            color: #484f58;
        }
        
        QPushButton#stop_btn {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #f85149, stop:1 #da3633);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }
        
        QPushButton#stop_btn:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                       stop:0 #ff6b6b, stop:1 #f85149);
        }
        
        QPushButton#stop_btn:disabled {
            background-color: #21262d;
            color: #484f58;
        }
        
        QPushButton#secondary_btn {
            background-color: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 8px 14px;
            font-weight: 500;
        }
        
        QPushButton#secondary_btn:hover {
            background-color: #30363d;
            border-color: #484f58;
        }
        
        QTextEdit#log_area {
            background-color: #0d1117;
            border: 1.5px solid #2d333b;
            border-radius: 8px;
            padding: 12px;
            color: #8b949e;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.5;
        }
        
        QCheckBox {
            color: #8b949e;
            spacing: 10px;
            font-size: 13px;
        }
        
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
            border-radius: 5px;
            border: 1.5px solid #30363d;
            background-color: #0d1117;
        }
        
        QCheckBox::indicator:checked {
            background-color: #238636;
            border-color: #238636;
            image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEzLjc4IDQuMjJhLjc1Ljc1IDAgMDEwIDEuMDZsLTcuMjUgNy4yNWEuNzUuNzUgMCAwMS0xLjA2IDBMMi4yMiA5LjI4YS43NS43NSAwIDAxMS4wNi0xLjA2TDYgMTAuOTRsNi43Mi02LjcyYS43NS43NSAwIDAxMS4wNiAweiIgZmlsbD0iI2ZmZiIvPgo8L3N2Zz4=);
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
        }
        
        /* 滚动条样式 */
        QScrollBar:vertical {
            background-color: #0d1117;
            width: 12px;
            border-radius: 6px;
        }
        
        QScrollBar::handle:vertical {
            background-color: #30363d;
            border-radius: 6px;
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
        self.cookie_input.setText(self.config.get("NOTION_COOKIE", ""))
        self.space_id_input.setText(self.config.get("NOTION_SPACE_ID", ""))
        self.user_id_input.setText(self.config.get("NOTION_USER_ID", ""))
        self.port_input.setText(self.config.get("NGINX_PORT", "8088"))

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
        
        # 如果内容没变化，跳过
        if current_text == self.last_clipboard_text:
            return
        
        self.last_clipboard_text = current_text
        
        # 检测是否是 token_v2
        if current_text.startswith("v02:") and len(current_text) > 100:
            self.cookie_input.setText(current_text)
            QMessageBox.information(self, "✅ 已检测到 Cookie", 
                                  f"已自动填入 token_v2（长度: {len(current_text)}）\n请记得点击'保存配置'。")

    def auto_load_cookie(self):
        """自动获取 Cookie，带错误处理"""
        cookie, error_type, error_msg = try_all_browsers()
        
        if cookie:
            self.cookie_input.setText(cookie)
            QMessageBox.information(self, "✅ 成功", "已成功读取 token_v2！\n请记得点击'保存配置'。")
        else:
            # 根据错误类型显示不同消息
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
            "NOTION_COOKIE": self.cookie_input.text().strip(),
            "NOTION_SPACE_ID": self.space_id_input.text().strip(),
            "NOTION_USER_ID": self.user_id_input.text().strip(),
            "NGINX_PORT": self.port_input.text().strip() or "8088"
        }
        self.config_manager.save(new_config)
        self.config = new_config
        QMessageBox.information(self, "💾 保存成功", "配置已更新。\n如果服务正在运行，请重启服务以生效。")

    def toggle_service(self):
        if self.process is None:
            self.start_service()

    def start_service(self):
        self.log_area.append(f"⏳ 正在启动服务 (Port: {self.port_input.text()})...")
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        
        port = self.port_input.text().strip() or "8088"
        cmd = "python"
        args = ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", port]
        
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.finished.connect(self.process_finished)
        
        self.process.start(cmd, args)
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_badge.setText("● 运行中")
        self.status_badge.setObjectName("status_running")
        self.status_badge.setStyleSheet(self.status_badge.styleSheet())  # 重新应用样式

    def stop_service(self):
        if self.process:
            self.log_area.append("⏹️ 正在停止服务...")
            self.process.terminate()
            if not self.process.waitForFinished(2000):
                self.process.kill()

    def process_finished(self):
        self.process = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_badge.setText("● 已停止")
        self.status_badge.setObjectName("status_stopped")
        self.status_badge.setStyleSheet(self.status_badge.styleSheet())  # 重新应用样式
        self.log_area.append("✅ 服务已停止。")

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="ignore")
        
        # 去除 ANSI 颜色代码
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)
        
        self.log_area.moveCursor(QTextCursor.End)
        self.log_area.insertPlainText(text)
        self.log_area.moveCursor(QTextCursor.End)

    def closeEvent(self, event):
        if self.process:
            reply = QMessageBox.question(self, '确认退出', "服务正在运行，退出将停止服务。确定要退出吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.stop_service()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def close_app(self):
        self.close()

    # --- 测试功能逻辑 ---
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
