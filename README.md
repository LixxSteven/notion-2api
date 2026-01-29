# Notion AI 本地代理

> 个人工具：将 Notion AI 转换为 OpenAI 兼容 API，供本地开发使用

## 功能特性
- **协议转换**: 将 Notion AI 接口转换为标准 OpenAI `v1/chat/completions` 格式
- **流式响应**: 完整支持 SSE 流式输出
- **图形界面**: Antigravity 风格 GUI 控制面板，支持服务启停、实时日志
- **密钥管理**: 内置 API Key 生成与验证
- **系统集成**: 支持最小化到系统托盘，后台静默运行

## 使用方法

### 1. 启动程序
```bash
python gui_app.py
```

### 2. 配置凭证
- 在 GUI 左侧面板填入 **API Key**（点击刷新生成或使用默认）
- 在「设置」页填入 **Notion Cookie** (`token_v2`)
  > 可开启「剪贴板监听」并复制浏览器 Cookie 自动填充

### 3. API 调用
```python
from openai import OpenAI

# 获取 Base URL 和 API Key 请见 GUI 界面
client = OpenAI(
    base_url="http://127.0.0.1:8088/v1",
    api_key="你的sk-notion-密钥"
)

response = client.chat.completions.create(
    model="claude-sonnet-4.5",  # 推荐使用 claude 系列
    messages=[{"role": "user", "content": "你好，请自我介绍"}],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### 4. 支持的模型
（具体以 Notion 官方支持为准）
- `claude-opus-4.5`
- `claude-sonnet-4.5`
- `gpt-4o`
- `gemini-2.0-flash`
- `llama-3.3-70b` 

## 文件结构
```
notion-2api/
├── gui_app.py          # GUI 应用程序入口
├── main.py             # FastAPI 服务端入口 (被 GUI 调用)
├── assets/             # 图标资源文件
├── app/                # 核心逻辑代码
│   ├── providers/      # Notion API 交互层
│   └── utils/          # 工具函数 (Config, Logger等)
├── .env                # 配置文件 (由 GUI 自动管理)
└── requirements.txt    # 依赖库列表
```

## 致谢
本项目基于 [notion-2api](https://github.com/lzA6/notion-2api) 二次开发，感谢原作者。
（仅供个人学习研究使用）
