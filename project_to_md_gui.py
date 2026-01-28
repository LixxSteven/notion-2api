#!/usr/bin/env python3
"""
项目源码 → Markdown 导出器 (PySide6 + Material Design)
选择文件夹，一键生成 Markdown，自动复制到剪贴板
"""

import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

# Material Design 主题
try:
    from qt_material import apply_stylesheet
    HAS_MATERIAL = True
except ImportError:
    HAS_MATERIAL = False
    print("提示: 未安装 qt-material，运行 pip install qt-material 安装")


# ==================== 配置 ====================

INCLUDE_EXTENSIONS = {
    '.py', '.java', '.kt', '.kts', '.scala', '.go', '.rs', '.rb', '.php',
    '.cs', '.fs', '.swift', '.dart', '.lua', '.pl', '.pm', '.r',
    '.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hxx',
    '.js', '.ts', '.jsx', '.tsx', '.mjs', '.cjs',
    '.vue', '.svelte', '.astro',
    '.html', '.css', '.scss', '.sass', '.less', '.styl',
    '.pug', '.ejs', '.hbs', '.j2', '.jinja2',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.env',
    '.xml', '.cfg', '.conf', '.properties',
    '.dockerfile', '.tf', '.hcl', '.nix',
    '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd',
    '.gradle', '.cmake',
    '.sql', '.graphql', '.gql', '.proto',
    '.md', '.txt', '.rst',
}

INCLUDE_FILENAMES = {
    'Makefile', 'Dockerfile', 'Jenkinsfile', 'Vagrantfile',
    '.gitignore', '.dockerignore', '.env.example',
    'requirements.txt', 'setup.py', 'pyproject.toml',
    'package.json', 'tsconfig.json', 'vite.config.js',
    'Cargo.toml', 'go.mod', 'go.sum',
}

EXCLUDE_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env',
    '.idea', '.vscode', '.vs', 'dist', 'build', 'out', 'target',
    '.next', '.nuxt', '.cache', '.parcel-cache',
    'egg-info', '.eggs', '.tox', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'coverage', '.coverage', 'htmlcov', 'bin', 'obj',
}

MAX_FILE_SIZE = 100 * 1024  # 100KB


# ==================== 核心逻辑 ====================

def get_language(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    name = Path(filename).name.lower()
    
    name_map = {'dockerfile': 'dockerfile', 'makefile': 'makefile', 'jenkinsfile': 'groovy', 'vagrantfile': 'ruby'}
    if name in name_map:
        return name_map[name]
    
    ext_map = {
        '.py': 'python', '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
        '.ts': 'typescript', '.jsx': 'jsx', '.tsx': 'tsx',
        '.vue': 'vue', '.svelte': 'svelte', '.astro': 'astro',
        '.java': 'java', '.kt': 'kotlin', '.kts': 'kotlin', '.scala': 'scala',
        '.go': 'go', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
        '.cs': 'csharp', '.fs': 'fsharp', '.swift': 'swift', '.dart': 'dart',
        '.lua': 'lua', '.pl': 'perl', '.pm': 'perl', '.r': 'r',
        '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.hxx': 'cpp',
        '.css': 'css', '.scss': 'scss', '.sass': 'sass', '.less': 'less', '.styl': 'stylus',
        '.html': 'html', '.pug': 'pug', '.ejs': 'ejs', '.hbs': 'handlebars',
        '.j2': 'jinja2', '.jinja2': 'jinja2', '.xml': 'xml',
        '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml',
        '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini', '.properties': 'properties',
        '.env': 'bash', '.sh': 'bash', '.bash': 'bash', '.zsh': 'zsh',
        '.ps1': 'powershell', '.bat': 'batch', '.cmd': 'batch',
        '.sql': 'sql', '.graphql': 'graphql', '.gql': 'graphql', '.proto': 'protobuf',
        '.tf': 'hcl', '.hcl': 'hcl', '.nix': 'nix',
        '.gradle': 'gradle', '.cmake': 'cmake',
        '.md': 'markdown', '.rst': 'rst', '.txt': 'text', '.dockerfile': 'dockerfile',
    }
    return ext_map.get(ext, '')


def should_include(path: Path) -> bool:
    return path.name in INCLUDE_FILENAMES or path.suffix.lower() in INCLUDE_EXTENSIONS


def generate_tree(root: Path, prefix: str = '') -> list[str]:
    lines = []
    try:
        items = sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except PermissionError:
        return lines
    
    visible = [i for i in items if (i.is_dir() and i.name not in EXCLUDE_DIRS) or (i.is_file() and should_include(i))]
    
    for i, item in enumerate(visible):
        is_last = i == len(visible) - 1
        conn = '└── ' if is_last else '├── '
        if item.is_dir():
            lines.append(f'{prefix}{conn}{item.name}/')
            lines.extend(generate_tree(item, prefix + ('    ' if is_last else '│   ')))
        else:
            lines.append(f'{prefix}{conn}{item.name}')
    return lines


def collect_files(root: Path, progress_cb=None) -> list[tuple[Path, str]]:
    files = []
    all_files = list(root.rglob('*'))
    total = len(all_files)
    
    for idx, item in enumerate(sorted(all_files)):
        if progress_cb:
            progress_cb(idx + 1, total)
        if item.is_dir():
            continue
        if any(ex in item.parts for ex in EXCLUDE_DIRS):
            continue
        if not should_include(item):
            continue
        try:
            if item.stat().st_size > MAX_FILE_SIZE:
                continue
            content = item.read_text(encoding='utf-8')
            files.append((item.relative_to(root), content))
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
    return files


def generate_markdown(project_path: Path, progress_cb=None) -> str:
    name = project_path.name
    lines = [
        f'# 📁 {name} 源码导出', '',
        f'> 导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'> 项目路径：`{project_path}`',
        '', '---', '', '## 📂 项目结构', '', '```', f'{name}/',
    ]
    lines.extend(generate_tree(project_path))
    lines.extend(['```', '', '---', '', '## 📄 源码文件', ''])
    
    files = collect_files(project_path, progress_cb)
    for rel_path, content in files:
        lang = get_language(str(rel_path))
        lines.extend([f'### `{rel_path}`', '', f'```{lang}', content.rstrip(), '```', ''])
    
    lines.extend(['---', '', '## 📊 统计', '', f'- 文件数量：{len(files)}'])
    total_lines = sum(c.count('\n') + 1 for _, c in files)
    total_chars = sum(len(c) for _, c in files)
    lines.append(f'- 总行数：{total_lines:,}')
    lines.append(f'- 总字符数：{total_chars:,}')
    return '\n'.join(lines)


# ==================== 后台线程 ====================

class ExportWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(bool, str, int)  # success, message, char_count
    
    def __init__(self, project_path: Path, save_path: str = None):
        super().__init__()
        self.project_path = project_path
        self.save_path = save_path
        self.markdown = ""
    
    def run(self):
        try:
            self.markdown = generate_markdown(
                self.project_path,
                lambda cur, tot: self.progress.emit(cur, tot)
            )
            if self.save_path:
                Path(self.save_path).write_text(self.markdown, encoding='utf-8')
                self.finished.emit(True, f"已保存到：\n{self.save_path}", len(self.markdown))
            else:
                self.finished.emit(True, "", len(self.markdown))
        except Exception as e:
            self.finished.emit(False, str(e), 0)


# ==================== GUI ====================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📦 项目源码导出器")
        self.setFixedSize(520, 380)
        self.worker = None
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        title = QLabel("项目源码 → Markdown 导出器")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        desc = QLabel("选择项目文件夹，生成包含所有源码的 Markdown 文件")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color: gray;")
        layout.addWidget(desc)
        
        layout.addSpacing(10)
        
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("请选择项目文件夹...")
        path_layout.addWidget(self.path_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_folder)
        browse_btn.setFixedWidth(80)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("请选择项目文件夹")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)
        
        layout.addSpacing(10)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.clipboard_btn = QPushButton("📋 生成并复制到剪贴板")
        self.clipboard_btn.clicked.connect(self.export_to_clipboard)
        self.clipboard_btn.setFixedHeight(36)
        btn_layout.addWidget(self.clipboard_btn)
        
        self.save_btn = QPushButton("💾 生成并保存文件")
        self.save_btn.clicked.connect(self.export_to_file)
        self.save_btn.setFixedHeight(36)
        btn_layout.addWidget(self.save_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择项目文件夹")
        if folder:
            self.path_input.setText(folder)
            self.status_label.setText(f"已选择：{Path(folder).name}")
    
    def export_to_clipboard(self):
        self._start_export(to_clipboard=True)
    
    def export_to_file(self):
        self._start_export(to_clipboard=False)
    
    def _start_export(self, to_clipboard=True):
        path = self.path_input.text()
        if not path:
            QMessageBox.warning(self, "提示", "请先选择项目文件夹")
            return
        
        project_path = Path(path)
        if not project_path.exists() or not project_path.is_dir():
            QMessageBox.critical(self, "错误", "选择的路径不存在或不是文件夹")
            return
        
        save_path = None
        if not to_clipboard:
            save_path, _ = QFileDialog.getSaveFileName(
                self, "保存文件", f"{project_path.name}_source.md",
                "Markdown (*.md);;所有文件 (*.*)"
            )
            if not save_path:
                return
        
        self.clipboard_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.status_label.setText("正在扫描文件...")
        self.progress_bar.setValue(0)
        
        self.worker = ExportWorker(project_path, save_path)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(lambda ok, msg, cnt: self._on_finished(ok, msg, cnt, to_clipboard))
        self.worker.start()
    
    def _on_progress(self, current, total):
        if total > 0:
            self.progress_bar.setValue(int(current / total * 100))
    
    def _on_finished(self, success, message, char_count, to_clipboard):
        self.clipboard_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        
        if success:
            if to_clipboard and self.worker:
                QApplication.clipboard().setText(self.worker.markdown)
                QMessageBox.information(
                    self, "完成",
                    f"已复制到剪贴板！\n\n字符数：{char_count:,}\n\n现在可以粘贴到 Notion 页面或聊天窗口。"
                )
            elif message:
                QMessageBox.information(self, "完成", message)
            self.status_label.setText("完成！")
        else:
            QMessageBox.critical(self, "错误", f"导出失败：{message}")
            self.status_label.setText("导出失败")


def main():
    app = QApplication(sys.argv)
    if HAS_MATERIAL:
        apply_stylesheet(app, theme='dark_teal.xml')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()