# 豆包 AI 网关服务

一个支持多 AI 服务商的对话 API 网关服务，基于 Flask 构建。

## 功能特性

- ✅ 支持多 AI 服务商（目前支持豆包）
- ✅ 会话管理和历史记录
- ✅ RESTful API 接口
- ✅ 可扩展架构，轻松添加新的 AI 服务商
- ✅ 支持系统消息设置
- ✅ 支持保留或清除对话历史

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API 凭证

首次运行时，程序会自动生成 `credentials.config` 文件，请填入你的凭证信息：

```
API KEY : "你的豆包API密钥"
ACCESS POINT : "你的豆包接入点"
DEFAULT PROVIDER : "doubao"
```

### 3. 启动服务

```bash
python main.py
```

服务将在 `http://0.0.0.0:11301` 启动。

## API 使用

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 否 | 会话 ID，不提供则自动生成 |
| `system_message` | string | 否 | 系统提示词 |
| `preserve` | string | 否 | 是否保留历史记录（true/false） |
| `provider` | string | 否 | AI 服务商名称，不提供则使用默认服务商 |
| `user_message` | string | 是 | 用户消息 |

### 示例请求

#### GET 请求

```bash
curl "http://localhost:11301/?user_message=你好&preserve=true"
```

#### POST 请求

```bash
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "你好",
    "preserve": true,
    "system_message": "你是一个友好的助手"
  }'
```

#### 指定服务商

```bash
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "你好",
    "provider": "doubao"
  }'
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET/POST | 发送聊天请求 |
| `/help` | GET | 查看帮助信息 |
| `/inspect` | GET | 查看所有会话的消息历史 |

## 架构说明

### 核心组件

```
┌─────────────────────────────────────────┐
│         Web Server (Flask)              │
│  - /help, /inspect, / (GET/POST)       │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      Session Manager                    │
│  - 管理多个会话 (Session pool)          │
│  - 创建/获取会话                         │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│         Session                         │
│  - chat_once()          单次对话         │
│  - chat_preserving_history()  保留历史   │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      Message (消息管理)                 │
│  - system/user/assistant 消息构建       │
│  - 历史记录管理                          │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      ApiFactory                        │
│  - 管理多个 AI 服务商                   │
│  - 动态获取服务商客户端                 │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      BaseApi (抽象基类)                 │
│  - reason()  抽象方法                   │
└──────────────┬──────────────────────────┘
               │
        ┌──────┴──────┐
        │             │
┌───────▼──────┐  ┌───▼────────┐
│   Doubao     │  │  DeepSeek  │
│  (已实现)     │  │  (待实现)   │
└──────────────┘  └────────────┘
```

## 扩展新的 AI 服务商

### 步骤 1: 创建服务商类

在 `api/` 目录下创建新的 Python 文件，例如 `api/new_provider.py`：

```python
from typing import Dict, List
from api.base_api import BaseApi

class NewProvider(BaseApi):
    def __init__(self) -> None:
        # 初始化客户端，例如设置 API Key 等
        self.client = ...  # 你的客户端初始化代码
    
    def reason(self, messages: List[Dict[str, str]]) -> str:
        """
        实现 AI 推理逻辑
        
        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
        
        Returns:
            AI 的回复内容
        """
        # 调用你的 AI 服务商 API
        response = self.client.chat(...)
        return response
```

### 步骤 2: 在 ApiFactory 中注册

编辑 `api/api_factory.py`，在 `_register_default_providers` 方法中添加注册：

```python
from api.new_provider import NewProvider

class ApiFactory:
    def _register_default_providers(self):
        """注册默认的服务商"""
        self.register_provider("doubao", Doubao())
        self.register_provider("new_provider", NewProvider())  # 添加这一行
```

### 步骤 3: 配置默认服务商（可选）

编辑 `credentials.config`，设置默认服务商：

```
API KEY : "your_api_key"
ACCESS POINT : "your_access_point"
DEFAULT PROVIDER : "new_provider"
```

### 步骤 4: 测试

```bash
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "你好",
    "provider": "new_provider"
  }'
```

## 配置说明

### credentials.config

配置文件格式：

```
API KEY : "你的API密钥"
ACCESS POINT : "你的接入点"
DEFAULT PROVIDER : "doubao"
```

- `API KEY`：豆包 API 的密钥
- `ACCESS POINT`：豆包 API 的接入点
- `DEFAULT PROVIDER`：默认使用的 AI 服务商名称

## 项目结构

```
doubao_backend/
├── main.py                    # 入口文件
├── requirements.txt           # 依赖包
├── credentials.config         # API 凭证配置（自动生成）
├── api/
│   ├── base_api.py           # AI 接口抽象基类
│   ├── api_factory.py        # API 工厂类（管理多个服务商）
│   ├── doubao.py             # 豆包 API 实现
│   └── deepseek.py           # DeepSeek 占位实现（待完善）
├── models/
│   ├── message.py            # 消息模型
│   └── session_manager.py    # 会话管理器
├── server/
│   └── web_server.py         # Flask Web 服务器
└── plans/
    └── architecture_design.md # 架构设计文档
```

## 依赖包

- **flask**：Web 框架
- **requests**：HTTP 请求库
- **volcengine-python-sdk[ark]**：火山引擎 SDK（调用豆包 API）

## 开发指南

### 添加新的 API 端点

编辑 `server/web_server.py`，添加新的路由：

```python
@app.route("/new_endpoint", methods=["GET"])
def new_endpoint():
    # 你的逻辑
    return jsonify({"result": "success"})
```

### 修改会话管理逻辑

编辑 `models/session_manager.py`，修改 `Session` 或 `SessionManager` 类。

### 添加新的消息类型

编辑 `models/message.py`，扩展 `Message` 类。

## 常见问题

### Q: 如何切换不同的 AI 服务商？

A: 在请求中添加 `provider` 参数，或者在 `credentials.config` 中设置 `DEFAULT PROVIDER`。

### Q: 如何清除会话历史？

A: 设置 `preserve` 参数为 `false`，或者创建新的会话 ID。

### Q: 支持哪些 AI 服务商？

A: 目前完整支持豆包（Doubao），DeepSeek 待实现。你可以按照扩展指南添加新的服务商。

### Q: 如何设置系统提示词？

A: 在请求中添加 `system_message` 参数，或者在创建会话时指定。

## 许可证

本项目仅供学习和研究使用。

## 贡献

欢迎提交 Issue 和 Pull Request！
