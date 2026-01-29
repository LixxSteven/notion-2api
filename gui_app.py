import sys
import os
import signal
import json
from typing import Dict
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                               QTextEdit, QSystemTrayIcon, QMenu, QMessageBox,
                               QGroupBox, QComboBox, QFormLayout, QStyle)
from PySide6.QtCore import QProcess, Qt, QSize, Slot, QThread, Signal
from PySide6.QtGui import QIcon, QAction, QTextCursor, QColor
from qt_material import apply_stylesheet
from app.utils.cookie_extractor import get_notion_cookie_from_browser

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
        self.resize(900, 700)
        
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        self.process = None
        
        self.init_ui()
        self.init_tray()
        
        # 初始加载配置
        self.load_config_to_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # 1. 标题和状态
        header_layout = QHBoxLayout()
        title_label = QLabel("Notion AI Proxy")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #26a69a;")
        header_layout.addWidget(title_label)
        
        self.status_label = QLabel("🔴 已停止")
        self.status_label.setStyleSheet("color: #ff5252; font-weight: bold; font-size: 16px;")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(self.status_label)
        layout.addLayout(header_layout)
        
        # 2. 配置区域
        config_group = QGroupBox("服务配置")
        form_layout = QFormLayout()
        
        # Cookie
        cookie_layout = QHBoxLayout()
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("token_v2 (点击右侧按钮自动获取 ->)")
        self.btn_auto_cookie = QPushButton("自动获取 Cookie")
        self.btn_auto_cookie.setFixedWidth(120)
        self.btn_auto_cookie.clicked.connect(self.auto_load_cookie)
        cookie_layout.addWidget(self.cookie_input)
        cookie_layout.addWidget(self.btn_auto_cookie)
        form_layout.addRow("Notion Cookie:", cookie_layout)
        
        # IDs
        self.space_id_input = QLineEdit()
        self.user_id_input = QLineEdit()
        form_layout.addRow("Space ID:", self.space_id_input)
        form_layout.addRow("User ID:", self.user_id_input)
        
        # Port
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("8088")
        form_layout.addRow("服务端口:", self.port_input)
        
        # 保存按钮
        self.btn_save = QPushButton("保存配置")
        self.btn_save.clicked.connect(self.save_config)
        self.btn_save.setStyleSheet("background-color: #00796b;")
        form_layout.addRow("", self.btn_save)
        
        config_group.setLayout(form_layout)
        layout.addWidget(config_group)
        
        # 3. 控制按钮
        control_layout = QHBoxLayout()
        self.btn_start = QPushButton("启动服务")
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet("font-size: 18px; font-weight: bold; background-color: #2e7d32;") # Green
        self.btn_start.clicked.connect(self.toggle_service)
        
        self.btn_stop = QPushButton("停止服务")
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet("font-size: 18px; font-weight: bold; background-color: #c62828;") # Red
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_service)
        
        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        layout.addLayout(control_layout)
        
        # 4. 日志区域
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        log_layout.addWidget(self.log_area)
        
        log_btns_layout = QHBoxLayout()
        self.btn_clear_log = QPushButton("清空日志")
        self.btn_clear_log.clicked.connect(lambda: self.log_area.clear())
        self.btn_copy_log = QPushButton("复制全部")
        self.btn_copy_log.clicked.connect(lambda: self.log_area.selectAll() or self.log_area.copy())
        
        log_btns_layout.addStretch()
        log_btns_layout.addWidget(self.btn_clear_log)
        log_btns_layout.addWidget(self.btn_copy_log)
        log_layout.addLayout(log_btns_layout)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # 5. 测试区域
        test_group = QGroupBox("API 测试")
        test_layout = QVBoxLayout()
        test_layout.setContentsMargins(5, 5, 5, 5) # Compact margins
        
        input_layout = QHBoxLayout()
        self.test_input = QLineEdit()
        self.test_input.setPlaceholderText("输入测试消息，例如：你好")
        self.test_input.returnPressed.connect(self.send_test_message)
        self.btn_test_send = QPushButton("发送测试")
        self.btn_test_send.clicked.connect(self.send_test_message)
        self.btn_test_send.setStyleSheet("background-color: #00838f; font-weight: bold;")
        self.btn_test_send.setFixedWidth(100)
        
        input_layout.addWidget(self.test_input)
        input_layout.addWidget(self.btn_test_send)
        test_layout.addLayout(input_layout)
        
        self.test_response = QTextEdit()
        self.test_response.setReadOnly(True)
        self.test_response.setPlaceholderText("AI 回复将显示在这里...")
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

    def load_config_to_ui(self):
        self.cookie_input.setText(self.config.get("NOTION_COOKIE", ""))
        self.space_id_input.setText(self.config.get("NOTION_SPACE_ID", ""))
        self.user_id_input.setText(self.config.get("NOTION_USER_ID", ""))
        self.port_input.setText(self.config.get("NGINX_PORT", "8088"))

    def auto_load_cookie(self):
        # 优先尝试 Edge，然后 Chrome
        cookie = get_notion_cookie_from_browser("edge") or get_notion_cookie_from_browser("chrome")
        if cookie:
            self.cookie_input.setText(cookie)
            QMessageBox.information(self, "成功", "已成功读取 token_v2！\n请记得点击'保存配置'。")
        else:
            QMessageBox.warning(self, "失败", "在 Edge/Chrome 中未找到 token_v2。\n请确保已登录 Notion 且浏览器未被管理员锁定。\n也可以尝试手动 F12 获取。")

    def save_config(self):
        new_config = {
            "NOTION_COOKIE": self.cookie_input.text().strip(),
            "NOTION_SPACE_ID": self.space_id_input.text().strip(),
            "NOTION_USER_ID": self.user_id_input.text().strip(),
            "NGINX_PORT": self.port_input.text().strip() or "8088"
        }
        self.config_manager.save(new_config)
        self.config = new_config
        QMessageBox.information(self, "保存成功", "配置已更新。\n如果服务正在运行，请重启服务以生效。")

    def toggle_service(self):
        if self.process is None:
            self.start_service()

    def start_service(self):
        self.log_area.append(f"正在启动服务 (Port: {self.port_input.text()})...")
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        
        # 启动命令
        port = self.port_input.text().strip() or "8088"
        cmd = "python"
        args = ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", port]
        
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.finished.connect(self.process_finished)
        
        self.process.start(cmd, args)
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("🟢 运行中")
        self.status_label.setStyleSheet("color: #69f0ae; font-weight: bold; font-size: 16px;")

    def stop_service(self):
        if self.process:
            self.log_area.append("正在停止服务...")
            self.process.terminate()
            # 给一点时间优雅退出
            if not self.process.waitForFinished(2000):
                self.process.kill()

    def process_finished(self):
        self.process = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("🔴 已停止")
        self.status_label.setStyleSheet("color: #ff5252; font-weight: bold; font-size: 16px;")
        self.log_area.append("服务已停止。")

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="ignore")
        
        # 简单的 ANSI 颜色去除 (如果有的话)
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
    
    # 应用 Material Theme
    apply_stylesheet(app, theme='dark_teal.xml')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())
