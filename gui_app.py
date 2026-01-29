import sys
import os
import signal
import json
import re
import ctypes
from typing import Dict
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                               QTextEdit, QSystemTrayIcon, QMenu, QMessageBox,
                               QGroupBox, QFormLayout, QStyle, QDialog, QCheckBox, 
                               QTabWidget, QFrame, QStackedWidget, QButtonGroup,
                               QScrollArea, QSizePolicy, QSpacerItem)
from PySide6.QtCore import QProcess, Qt, QSize, Slot, QThread, Signal, QTimer
from PySide6.QtGui import QIcon, QAction, QTextCursor, QClipboard, QTextCharFormat, QColor, QPixmap, QImage, QPainter
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
        self.setWindowTitle("Notion AI Proxy")  # Renamed
        self.resize(1000, 750)
        
        # Load Application Icon
        self.setWindowIcon(self.load_transparent_icon("assets/app_icon.png"))
        
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
        
        # 顶部导航栏（包含药丸 Tab）
        header = self.create_header()
        layout.addWidget(header)
        
        # 内容区域使用 QStackedWidget
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("content_stack")
        
        # 控制台页
        console_page = self.create_console_page()
        self.content_stack.addWidget(console_page)
        
        # 设置页
        settings_page = self.create_settings_page()
        self.content_stack.addWidget(settings_page)
        
        layout.addWidget(self.content_stack)

    def create_header(self):
        """创建顶部导航栏"""
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(70)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(16)
        
        # 标题
        title = QLabel("Notion AI 本地代理")
        title.setObjectName("app_title")
        layout.addWidget(title)
        
        layout.addSpacing(24)
        
        # 药丸型 Tab 容器
        tab_container = QFrame()
        tab_container.setObjectName("tab_container")
        tab_layout = QHBoxLayout(tab_container)
        tab_layout.setContentsMargins(4, 4, 4, 4)
        tab_layout.setSpacing(4)
        
        # Tab 按钮组
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        
        self.tab_console = QPushButton("控制台")
        self.tab_console.setObjectName("tab_btn")
        self.tab_console.setCheckable(True)
        self.tab_console.setChecked(True)
        self.tab_console.clicked.connect(lambda: self.switch_page(0))
        
        self.tab_settings = QPushButton("设置")
        self.tab_settings.setObjectName("tab_btn")
        self.tab_settings.setCheckable(True)
        self.tab_settings.clicked.connect(lambda: self.switch_page(1))
        
        self.tab_group.addButton(self.tab_console, 0)
        self.tab_group.addButton(self.tab_settings, 1)
        
        tab_layout.addWidget(self.tab_console)
        tab_layout.addWidget(self.tab_settings)
        
        layout.addWidget(tab_container)
        layout.addStretch()
        
        # 右上角状态指示器
        status_container = QFrame()
        status_container.setObjectName("status_container")
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(12, 6, 12, 6)
        status_layout.setSpacing(8)
        
        self.header_status_dot = QLabel("●")
        self.header_status_dot.setObjectName("status_dot_stopped")
        
        self.header_status_text = QLabel("已停止")
        self.header_status_text.setObjectName("status_text")
        
        status_layout.addWidget(self.header_status_dot)
        status_layout.addWidget(self.header_status_text)
        
        layout.addWidget(status_container)
        
        return header
    
    def switch_page(self, index):
        """切换页面"""
        self.content_stack.setCurrentIndex(index)

    def create_console_page(self):
        """创建控制台页 - 水平双列布局"""
        page = QWidget()
        page.setObjectName("console_page")
        main_layout = QVBoxLayout(page)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)
        
        # 上半部分：水平双列布局
        top_layout = QHBoxLayout()
        top_layout.setSpacing(16)
        
        # 左列（60%）
        left_column = QVBoxLayout()
        left_column.setSpacing(16)
        
        # 服务配置卡片
        service_card = self.create_service_card()
        left_column.addWidget(service_card)
        
        # API 密钥卡片
        api_key_card = self.create_api_key_card()
        left_column.addWidget(api_key_card)
        
        left_column.addStretch()
        
        # 右列（40%）
        right_column = QVBoxLayout()
        right_column.setSpacing(16)
        
        # API 端点卡片
        api_endpoints_card = self.create_api_endpoints_card()
        right_column.addWidget(api_endpoints_card)
        
        right_column.addStretch()
        
        # 添加到水平布局
        left_widget = QWidget()
        left_widget.setLayout(left_column)
        left_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        right_widget = QWidget()
        right_widget.setLayout(right_column)
        right_widget.setFixedWidth(350)
        
        top_layout.addWidget(left_widget, 3)
        top_layout.addWidget(right_widget, 2)
        
        main_layout.addLayout(top_layout)
        
        # 下半部分：快速测试 + 日志
        test_card = self.create_quick_test_card()
        main_layout.addWidget(test_card)
        
        log_card = self.create_log_card()
        main_layout.addWidget(log_card)
        
        return page
    
    def create_service_card(self):
        """创建服务配置卡片"""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)
        
        # 标题行
        title_layout = QHBoxLayout()
        title_icon = QLabel("⚙️")
        title_icon.setStyleSheet("font-size: 18px;")
        title_label = QLabel("服务配置")
        title_label.setObjectName("card_title")
        
        # 状态指示
        self.status_indicator = QLabel("●")
        self.status_indicator.setObjectName("status_dot_stopped")
        self.status_text = QLabel("已停止")
        self.status_text.setObjectName("status_text_small")
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_label)
        title_layout.addSpacing(12)
        title_layout.addWidget(self.status_indicator)
        title_layout.addWidget(self.status_text)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 端口输入行
        port_layout = QHBoxLayout()
        port_label = QLabel("监听端口")
        port_label.setObjectName("field_label")
        port_label.setFixedWidth(80)
        
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("8088")
        self.port_input.setObjectName("input")
        self.port_input.setFixedWidth(120)
        self.port_input.setFixedHeight(36)
        self.port_input.textChanged.connect(self.update_port_display)
        
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_input)
        port_layout.addStretch()
        
        layout.addLayout(port_layout)
        
        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.btn_start = QPushButton("启动服务")
        self.btn_start.setObjectName("primary_btn")
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self.toggle_service)
        
        self.btn_stop = QPushButton("停止服务")
        self.btn_stop.setObjectName("danger_btn")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_service)
        
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        
        layout.addLayout(btn_layout)
        
        return card
    
    def load_transparent_icon(self, path):
        """加载图标并将黑色背景转为透明"""
        if not os.path.exists(path):
            return QIcon()
            
        image = QImage(path)
        image = image.convertToFormat(QImage.Format_RGBA8888)
        
        width = image.width()
        height = image.height()
        
        for y in range(height):
            for x in range(width):
                pixel = image.pixelColor(x, y)
                # 如果是深色背景 (阈值 30)，则设为全透明
                if pixel.red() < 30 and pixel.green() < 30 and pixel.blue() < 30:
                    pixel.setAlpha(0)
                    image.setPixelColor(x, y, pixel)
                    
        return QIcon(QPixmap.fromImage(image))

    def create_api_key_card(self):
        """创建 API 密钥卡片"""
        import secrets
        
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        
        # 标题行
        title_layout = QHBoxLayout()
        title_icon = QLabel("🔑")
        title_icon.setStyleSheet("font-size: 18px;")
        title_label = QLabel("API 密钥")
        title_label.setObjectName("card_title")
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 密钥输入框 + 按钮
        key_layout = QHBoxLayout()
        key_layout.setSpacing(8)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setObjectName("input")
        self.api_key_input.setReadOnly(True)
        self.api_key_input.setFixedHeight(36)
        
        # 加载或生成密钥
        saved_key = self.config.get("api_key", "")
        if not saved_key:
            saved_key = f"sk-notion-{secrets.token_hex(16)}"
        self.api_key_input.setText(saved_key)
        
        btn_refresh = QPushButton("")
        btn_refresh.setObjectName("icon_btn")
        btn_refresh.setFixedSize(36, 36)
        btn_refresh.setIcon(self.load_transparent_icon("assets/refresh_icon.png"))
        btn_refresh.setIconSize(QSize(20, 20))
        btn_refresh.setToolTip("生成新密钥")
        btn_refresh.clicked.connect(self.generate_new_api_key)
        
        btn_copy_key = QPushButton("")
        btn_copy_key.setObjectName("icon_btn")
        btn_copy_key.setFixedSize(36, 36)
        btn_copy_key.setIcon(self.load_transparent_icon("assets/copy_icon.png"))
        btn_copy_key.setIconSize(QSize(20, 20))
        btn_copy_key.setToolTip("复制密钥")
        btn_copy_key.clicked.connect(self.copy_api_key)
        
        key_layout.addWidget(self.api_key_input)
        key_layout.addWidget(btn_refresh)
        key_layout.addWidget(btn_copy_key)
        
        layout.addLayout(key_layout)
        
        # 提示文字
        hint_label = QLabel("⚠️ 注意: 请妥善保管您的 API 密钥")
        hint_label.setObjectName("hint_text")
        hint_label.setStyleSheet("color: #f0883e; font-size: 11px;")
        layout.addWidget(hint_label)
        
        return card
    
    def generate_new_api_key(self):
        """生成新的 API 密钥"""
        import secrets
        new_key = f"sk-notion-{secrets.token_hex(16)}"
        self.api_key_input.setText(new_key)
        self.save_api_key()
        self.log_area.append(f"✅ 已生成新的 API 密钥")
    
    def copy_api_key(self):
        """复制 API 密钥"""
        QApplication.clipboard().setText(self.api_key_input.text())
        self.log_area.append("✅ API 密钥已复制到剪贴板")
    
    def save_api_key(self):
        """保存 API 密钥到配置"""
        current_config = self.config_manager.get_all()
        current_config["api_key"] = self.api_key_input.text()
        self.config_manager.update(current_config)
    
    def create_api_endpoints_card(self):
        """创建 API 端点卡片"""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        
        # 标题行
        title_layout = QHBoxLayout()
        title_icon = QLabel("📡")
        title_icon.setStyleSheet("font-size: 18px;")
        title_label = QLabel("API 端点")
        title_label.setObjectName("card_title")
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # Base URL
        url_label = QLabel("Base URL:")
        url_label.setObjectName("field_label")
        layout.addWidget(url_label)
        
        url_layout = QHBoxLayout()
        url_layout.setSpacing(8)
        
        self.base_url_label = QLabel("http://127.0.0.1:8088")
        self.base_url_label.setObjectName("url_text")
        self.base_url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        btn_copy_url = QPushButton("")
        btn_copy_url.setObjectName("icon_btn")
        btn_copy_url.setFixedSize(36, 36)
        btn_copy_url.setIcon(self.load_transparent_icon("assets/copy_icon.png"))
        btn_copy_url.setIconSize(QSize(20, 20))
        btn_copy_url.setToolTip("复制 URL")
        btn_copy_url.clicked.connect(self.copy_base_url)
        
        url_layout.addWidget(self.base_url_label)
        url_layout.addWidget(btn_copy_url)
        url_layout.addStretch()
        
        layout.addLayout(url_layout)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setObjectName("separator")
        layout.addWidget(separator)
        
        # 端点列表
        endpoints = [
            ("/v1/models", "模型列表"),
            ("/v1/chat/completions", "对话接口"),
        ]
        
        for endpoint, desc in endpoints:
            ep_layout = QHBoxLayout()
            ep_text = QLabel(endpoint)
            ep_text.setObjectName("endpoint_text")
            ep_desc = QLabel(desc)
            ep_desc.setObjectName("endpoint_desc")
            ep_layout.addWidget(ep_text)
            ep_layout.addStretch()
            ep_layout.addWidget(ep_desc)
            layout.addLayout(ep_layout)
        
        return card
    
    def create_quick_test_card(self):
        """创建快速测试卡片"""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        
        # 标题行
        title_layout = QHBoxLayout()
        title_icon = QLabel("🧪")
        title_icon.setStyleSheet("font-size: 18px;")
        title_label = QLabel("快速测试")
        title_label.setObjectName("card_title")
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 输入行
        test_input_layout = QHBoxLayout()
        test_input_layout.setSpacing(10)
        
        self.test_input = QLineEdit()
        self.test_input.setText("你是谁？我的邮箱是什么？")
        self.test_input.setObjectName("input")
        self.test_input.setFixedHeight(40)
        self.test_input.returnPressed.connect(self.send_test_message)
        
        self.btn_test_send = QPushButton("发送")
        self.btn_test_send.setObjectName("primary_btn")
        self.btn_test_send.clicked.connect(self.send_test_message)
        self.btn_test_send.setFixedWidth(80)
        self.btn_test_send.setFixedHeight(40)
        
        test_input_layout.addWidget(self.test_input)
        test_input_layout.addWidget(self.btn_test_send)
        
        layout.addLayout(test_input_layout)
        
        # 响应区
        self.test_response = QTextEdit()
        self.test_response.setReadOnly(True)
        self.test_response.setPlaceholderText("AI 回复将显示在这里...")
        self.test_response.setObjectName("response_area")
        self.test_response.setFixedHeight(100)
        
        layout.addWidget(self.test_response)
        
        return card
    
    def create_log_card(self):
        """创建运行日志卡片"""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        
        # 标题行
        title_layout = QHBoxLayout()
        title_icon = QLabel("📜")
        title_icon.setStyleSheet("font-size: 18px;")
        title_label = QLabel("运行日志")
        title_label.setObjectName("card_title")
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        # 日志按钮
        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setObjectName("text_btn")
        self.btn_clear_log.clicked.connect(lambda: self.log_area.clear())
        
        self.btn_copy_log = QPushButton("")
        self.btn_copy_log.setObjectName("icon_btn")
        self.btn_copy_log.setFixedSize(36, 36)
        self.btn_copy_log.setIcon(self.load_transparent_icon("assets/copy_icon.png"))
        self.btn_copy_log.setIconSize(QSize(20, 20))
        self.btn_copy_log.setToolTip("复制日志")
        self.btn_copy_log.clicked.connect(lambda: self.log_area.selectAll() or self.log_area.copy())
        
        title_layout.addWidget(self.btn_clear_log)
        title_layout.addWidget(self.btn_copy_log)
        
        layout.addLayout(title_layout)
        
        # 日志区域
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setObjectName("log_area")
        self.log_area.setFixedHeight(150)
        
        layout.addWidget(self.log_area)
        
        return card
    
    def copy_base_url(self):
        """复制 Base URL 到剪贴板"""
        port = self.port_input.text().strip() or "8088"
        base_url = f"http://127.0.0.1:{port}"
        QApplication.clipboard().setText(base_url)
        self.log_area.append(f"✅ Base URL 已复制: {base_url}")


    def create_settings_page(self):
        """创建设置页"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Notion Cookie 配置卡片
        cookie_card = QGroupBox("Notion Cookie")
        cookie_card.setObjectName("section")
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
        
        cookie_card.setLayout(cookie_layout)
        layout.addWidget(cookie_card)
        
        # 服务配置卡片
        service_card = QGroupBox("服务配置")
        service_card.setObjectName("section")
        service_layout = QVBoxLayout()
        service_layout.setSpacing(12)
        
        # 端口设置
        port_layout = QHBoxLayout()
        port_label = QLabel("服务端口:")
        port_label.setStyleSheet("color: #8b949e; font-size: 13px;")
        port_label.setFixedWidth(100)
        
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("8088")
        self.port_input.setObjectName("input")
        self.port_input.setFixedWidth(150)
        self.port_input.setFixedHeight(40)
        self.port_input.textChanged.connect(self.update_port_display)
        
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_input)
        port_layout.addStretch()
        service_layout.addLayout(port_layout)
        
        service_card.setLayout(service_layout)
        layout.addWidget(service_card)
        
        # Notion 信息卡片（只读）
        info_card = QGroupBox("Notion 信息（只读）")
        info_card.setObjectName("section")
        info_layout = QVBoxLayout()
        info_layout.setSpacing(12)
        
        # Space ID
        space_layout = QHBoxLayout()
        space_label = QLabel("Space ID:")
        space_label.setStyleSheet("color: #8b949e; font-size: 13px;")
        space_label.setFixedWidth(100)
        
        self.space_id_input = QLineEdit()
        self.space_id_input.setObjectName("input")
        self.space_id_input.setMinimumHeight(40)
        self.space_id_input.setReadOnly(True)
        self.space_id_input.setStyleSheet(
            self.space_id_input.styleSheet() + 
            "QLineEdit#input:read-only { background-color: #0a0e1a; color: #6e7681; }"
        )
        
        space_layout.addWidget(space_label)
        space_layout.addWidget(self.space_id_input)
        info_layout.addLayout(space_layout)
        
        # User ID
        user_layout = QHBoxLayout()
        user_label = QLabel("User ID:")
        user_label.setStyleSheet("color: #8b949e; font-size: 13px;")
        user_label.setFixedWidth(100)
        
        self.user_id_input = QLineEdit()
        self.user_id_input.setObjectName("input")
        self.user_id_input.setMinimumHeight(40)
        self.user_id_input.setReadOnly(True)
        self.user_id_input.setStyleSheet(
            self.user_id_input.styleSheet() + 
            "QLineEdit#input:read-only { background-color: #0a0e1a; color: #6e7681; }"
        )
        
        user_layout.addWidget(user_label)
        user_layout.addWidget(self.user_id_input)
        info_layout.addLayout(user_layout)
        
        info_card.setLayout(info_layout)
        layout.addWidget(info_card)
        
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
    
    def update_port_display(self):
        """更新端口显示"""
        port = self.port_input.text().strip() or "8088"
        self.base_url_label.setText(f"http://127.0.0.1:{port}")

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.load_transparent_icon("assets/app_icon.png"))
        
        # 双击托盘图标显示窗口
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        tray_menu = QMenu()
        
        # 显示主窗口
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show_window)
        tray_menu.addAction(show_action)
        
        tray_menu.addSeparator()
        
        # 启动服务
        self.tray_start_action = QAction("启动服务", self)
        self.tray_start_action.triggered.connect(self.start_service)
        tray_menu.addAction(self.tray_start_action)
        
        # 停止服务
        self.tray_stop_action = QAction("停止服务", self)
        self.tray_stop_action.triggered.connect(self.stop_service)
        self.tray_stop_action.setEnabled(False)  # 初始禁用
        tray_menu.addAction(self.tray_stop_action)
        
        tray_menu.addSeparator()
        
        # 退出
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
    
    def show_window(self):
        """显示并激活窗口"""
        self.show()
        self.activateWindow()
        self.raise_()
    
    def tray_icon_activated(self, reason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_window()

    def apply_modern_style(self):
        """应用 Antigravity 风格主题"""
        style = """
        /* === 全局样式 === */
        QMainWindow {
            background-color: #0d1117;
        }
        
        QWidget {
            font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
        }
        
        /* === 顶部导航栏 === */
        #header {
            background-color: #0d1117;
            border-bottom: 1px solid #21262d;
        }
        
        #app_title {
            font-size: 18px;
            font-weight: 700;
            color: #e6edf3;
        }
        
        /* === 药丸型 Tab 容器 === */
        #tab_container {
            background-color: #161b22;
            border-radius: 20px;
            border: 1px solid #30363d;
        }
        
        /* === 药丸型 Tab 按钮 === */
        QPushButton#tab_btn {
            border: none;
            border-radius: 16px;
            padding: 8px 20px;
            background: transparent;
            color: #8b949e;
            font-size: 13px;
            font-weight: 500;
        }
        
        QPushButton#tab_btn:checked {
            background-color: #2f81f7;
            color: white;
        }
        
        QPushButton#tab_btn:hover:!checked {
            color: #c9d1d9;
            background-color: rgba(255, 255, 255, 0.05);
        }
        
        /* === 状态容器 === */
        #status_container {
            background-color: #161b22;
            border-radius: 16px;
            border: 1px solid #30363d;
        }
        
        #status_dot_running {
            color: #238636;
            font-size: 14px;
        }
        
        #status_dot_stopped {
            color: #da3633;
            font-size: 14px;
        }
        
        #status_text {
            color: #8b949e;
            font-size: 12px;
        }
        
        #status_text_small {
            color: #238636;
            font-size: 12px;
            font-weight: 500;
        }
        
        /* === 内容区域 === */
        #content_stack {
            background-color: #0d1117;
        }
        
        #console_page {
            background-color: #0d1117;
        }
        
        /* === 卡片样式 === */
        QFrame#card {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
        }
        
        #card_title {
            font-size: 14px;
            font-weight: 600;
            color: #e6edf3;
        }
        
        #field_label {
            font-size: 12px;
            color: #8b949e;
        }
        
        /* === 输入框 === */
        QLineEdit#input {
            background-color: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 0 12px;
            color: #e6edf3;
            font-size: 13px;
        }
        
        QLineEdit#input:focus {
            border-color: #2f81f7;
        }
        
        QLineEdit#input:read-only {
            background-color: #0d1117;
            color: #8b949e;
        }
        
        /* === 主按钮（蓝色） === */
        QPushButton#primary_btn {
            background-color: #238636;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0 16px;
            font-weight: 600;
            font-size: 13px;
        }
        
        QPushButton#primary_btn:hover {
            background-color: #2ea043;
        }
        
        QPushButton#primary_btn:pressed {
            background-color: #1a7f37;
        }
        
        /* === 危险按钮（红色） === */
        QPushButton#danger_btn {
            background-color: #21262d;
            color: #f85149;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 0 16px;
            font-weight: 600;
            font-size: 13px;
        }
        
        QPushButton#danger_btn:hover {
            background-color: #da3633;
            color: white;
            border-color: #da3633;
        }
        
        QPushButton#danger_btn:disabled {
            background-color: #21262d;
            color: #484f58;
            border-color: #30363d;
        }
        
        /* === 次要按钮 === */
        QPushButton#secondary_btn {
            background-color: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 0 16px;
            font-weight: 500;
            font-size: 13px;
        }
        
        QPushButton#secondary_btn:hover {
            background-color: #30363d;
            border-color: #484f58;
        }
        
        /* === 小按钮 === */
        QPushButton#small_btn {
            background-color: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            border-radius: 4px;
            padding: 4px 12px;
            font-size: 11px;
        }
        
        QPushButton#small_btn:hover {
            background-color: #30363d;
        }
        
        /* === 图标按钮 === */
        QPushButton#icon_btn {
            background-color: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            border-radius: 6px;
            font-size: 14px;
        }
        
        QPushButton#icon_btn:hover {
            background-color: #30363d;
            border-color: #484f58;
        }
        
        /* === 文字按钮 === */
        QPushButton#text_btn {
            background-color: transparent;
            color: #8b949e;
            border: none;
            padding: 4px 8px;
            font-size: 12px;
        }
        
        QPushButton#text_btn:hover {
            color: #c9d1d9;
        }
        
        /* === URL 文本 === */
        #url_text {
            color: #e6edf3;
            font-family: 'Consolas', 'JetBrains Mono', monospace;
            font-size: 13px;
        }
        
        /* === 端点文本 === */
        #endpoint_text {
            color: #e6edf3;
            font-family: 'Consolas', 'JetBrains Mono', monospace;
            font-size: 12px;
        }
        
        #endpoint_desc {
            color: #8b949e;
            font-size: 11px;
        }
        
        /* === 分隔线 === */
        QFrame#separator {
            background-color: #30363d;
            max-height: 1px;
        }
        
        /* === 日志区域 === */
        QTextEdit#log_area {
            background-color: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 12px;
            color: #8b949e;
            font-family: 'Consolas', 'JetBrains Mono', monospace;
            font-size: 12px;
        }
        
        /* === 响应区域 === */
        QTextEdit#response_area {
            background-color: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 12px;
            color: #e6edf3;
            font-family: 'Microsoft YaHei UI', sans-serif;
            font-size: 13px;
        }
        
        /* === 复选框（Toggle 风格） === */
        QCheckBox {
            color: #8b949e;
            spacing: 8px;
            font-size: 13px;
        }
        
        QCheckBox::indicator {
            width: 40px;
            height: 22px;
            border-radius: 11px;
            border: none;
            background-color: #30363d;
        }
        
        QCheckBox::indicator:checked {
            background-color: #238636;
        }
        
        QCheckBox::indicator:hover {
            background-color: #484f58;
        }
        
        QCheckBox::indicator:checked:hover {
            background-color: #2ea043;
        }
        
        /* === 标签 === */
        QLabel {
            color: #c9d1d9;
        }
        
        /* === 滚动条 === */
        QScrollBar:vertical {
            background-color: transparent;
            width: 8px;
            border-radius: 4px;
        }
        
        QScrollBar::handle:vertical {
            background-color: #30363d;
            border-radius: 4px;
            min-height: 30px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #484f58;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
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
        
        # 更新服务卡片状态指示器
        self.status_indicator.setObjectName("status_dot_running")
        self.status_indicator.setStyleSheet("")  # 触发样式刷新
        self.status_text.setText("运行中")
        self.status_text.setStyleSheet("color: #238636; font-size: 12px; font-weight: 500;")
        
        # 更新顶部导航栏状态
        self.header_status_dot.setObjectName("status_dot_running")
        self.header_status_dot.setStyleSheet("")
        self.header_status_text.setText("运行中")
        
        # 更新托盘菜单状态
        self.tray_start_action.setEnabled(False)
        self.tray_stop_action.setEnabled(True)

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
        
        # 更新服务卡片状态指示器
        self.status_indicator.setObjectName("status_dot_stopped")
        self.status_indicator.setStyleSheet("")  # 触发样式刷新
        self.status_text.setText("已停止")
        self.status_text.setStyleSheet("color: #da3633; font-size: 12px; font-weight: 500;")
        
        # 更新顶部导航栏状态
        self.header_status_dot.setObjectName("status_dot_stopped")
        self.header_status_dot.setStyleSheet("")
        self.header_status_text.setText("已停止")
        
        self.log_area.append("✅ 服务已停止。")
        
        # 更新托盘菜单状态
        self.tray_start_action.setEnabled(True)
        self.tray_stop_action.setEnabled(False)

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
    # 设置 AppUserModelID 以便 Windows 任务栏识别图标
    try:
        myappid = 'antigravity.notion_ai_proxy.gui.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())
