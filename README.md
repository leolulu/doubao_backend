# 多 AI 服务商网关服务

一个支持多 AI 服务商的对话 API 网关服务，基于 Flask 构建。支持豆包、智谱、DeepSeek 等多个 AI 服务商，提供统一的 RESTful API 接口。

## 功能特性

- ✅ 支持多 AI 服务商（豆包、智谱、DeepSeek）
- ✅ 会话管理和历史记录
- ✅ RESTful API 接口（GET/POST）
- ✅ 可扩展架构，轻松添加新的 AI 服务商
- ✅ 支持系统消息设置
- ✅ 支持保留或清除对话历史
- ✅ 自动配置文件生成和参数校验
- ✅ 智谱 AI 支持 Coding 专用端点

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API 凭证

首次运行时，程序会自动生成 `credentials.config` 文件，请填入你的凭证信息：

```ini
[default_provider]
# 系统配置
# 默认使用的服务商名称
PROVIDER = doubao

[DOUBAO]
# API 密钥
API_KEY = 
# 访问点（模型标识）
ACCESS_POINT = 

[ZHIPU]
# API 密钥
API_KEY = 
# 模型名称（如 glm-4.7）
MODEL = 
# 是否使用 Coding 专用端点
USE_CODING_ENDPOINT = False

[DEEPSEEK]
# API 密钥
API_KEY = 
# 模型名称（如 deepseek-chat 或 deepseek-reasoner）
MODEL = 
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
# 使用智谱 AI
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "你好",
    "provider": "zhipu"
  }'

# 使用 DeepSeek
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "你好",
    "provider": "deepseek"
  }'
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET/POST | 发送聊天请求 |
| `/help` | GET | 查看帮助信息 |
| `/inspect` | GET | 查看所有会话的消息历史 |

## 支持的 AI 服务商

### 豆包 (Doubao)

使用火山引擎 SDK 调用豆包 API。

**配置参数：**
- `API_KEY`: API 密钥（必填）
- `ACCESS_POINT`: 访问点/模型标识（必填）

### 智谱 AI (Zhipu)

使用 REST API 调用智谱 AI，支持普通端点和 Coding 专用端点。

**配置参数：**
- `API_KEY`: API 密钥（必填）
- `MODEL`: 模型名称，如 `glm-4.7`（必填）
- `USE_CODING_ENDPOINT`: 是否使用 Coding 专用端点（可选，默认 False）

**端点说明：**
- 普通端点: `https://open.bigmodel.cn/api/paas/v4/`
- Coding 端点: `https://open.bigmodel.cn/api/coding/paas/v4`

### DeepSeek

使用 REST API 调用 DeepSeek。

**配置参数：**
- `API_KEY`: API 密钥（必填）
- `MODEL`: 模型名称，如 `deepseek-chat` 或 `deepseek-reasoner`（必填）

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
│  - clear_history()      清除历史         │
│  - adjust_system_message() 调整系统消息 │
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
│  - 自动配置文件生成和校验               │
└──────────────┬──────────────────────────┘
                │
┌──────────────▼──────────────────────────┐
│      BaseApi (抽象基类)                 │
│  - get_params()        参数定义          │
│  - validate_config()   配置校验          │
│  - reason()            抽象推理方法      │
└──────────────┬──────────────────────────┘
                │
         ┌──────┴──────┬──────────┐
         │             │          │
┌────────▼─────┐ ┌────▼──────┐ ┌─▼──────────┐
│   Doubao     │ │  Zhipu    │ │  DeepSeek  │
│  (SDK 调用)   │ │  (REST)   │ │  (REST)    │
└──────────────┘ └───────────┘ └────────────┘
```

### 参数系统

项目使用 `ProviderParam` 类定义每个服务商需要的参数，支持以下特性：

- **参数类型**: STRING, BOOLEAN, INTEGER, FLOAT
- **必填校验**: 自动检查必填参数
- **默认值**: 支持参数默认值
- **类型转换**: 自动将配置文件中的字符串值转换为正确类型
- **配置校验**: 启动时自动校验所有配置

## 扩展新的 AI 服务商

### 步骤 1: 创建服务商类

在 `api/` 目录下创建新的 Python 文件，例如 `api/new_provider.py`：

```python
from typing import Dict, List
from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam

class NewProvider(BaseApi):
    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        """定义该服务商需要的参数"""
        return [
            ProviderParam(
                name="api_key",
                param_type=ParamType.STRING,
                required=True,
                description="API 密钥"
            ),
            ProviderParam(
                name="model",
                param_type=ParamType.STRING,
                required=True,
                description="模型名称"
            ),
            ProviderParam(
                name="timeout",
                param_type=ParamType.INTEGER,
                required=False,
                default=30,
                description="请求超时时间（秒）"
            )
        ]
    
    def __init__(self, api_key: str, model: str, timeout: int = 30) -> None:
        """初始化客户端"""
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # 你的客户端初始化代码
    
    def reason(self, messages: List[Dict[str, str]]) -> str:
        """
        实现 AI 推理逻辑
        
        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
        
        Returns:
            AI 的回复内容
        """
        # 调用你的 AI 服务商 API
        response = self._call_api(messages)
        return response
```

### 步骤 2: 在 ApiFactory 中注册

编辑 `api/api_factory.py`，在 `_register_default_provider_classes` 方法中添加注册：

```python
from api.new_provider import NewProvider

class ApiFactory:
    def _register_default_provider_classes(self):
        """注册默认的服务商类"""
        self._provider_classes["doubao"] = Doubao
        self._provider_classes["zhipu"] = Zhipu
        self._provider_classes["deepseek"] = DeepSeek
        self._provider_classes["new_provider"] = NewProvider  # 添加这一行
```

同时在 `_register_default_providers` 方法中注册：

```python
def _register_default_providers(self):
    """注册默认的服务商"""
    self._register_provider("doubao", Doubao)
    self._register_provider("zhipu", Zhipu)
    self._register_provider("deepseek", DeepSeek)
    self._register_provider("new_provider", NewProvider)  # 添加这一行
```

### 步骤 3: 配置服务商（自动生成）

重新启动服务，程序会自动在 `credentials.config` 中添加新服务商的配置段：

```ini
[NEW_PROVIDER]
# API 密钥
API_KEY = 
# 模型名称
MODEL = 
# 请求超时时间（秒）
TIMEOUT = 30
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

配置文件使用 INI 格式，包含以下部分：

#### [default_provider] - 系统配置

```ini
PROVIDER = doubao  # 默认使用的服务商名称
```

#### [DOUBAO] - 豆包配置

```ini
API_KEY = "你的豆包API密钥"
ACCESS_POINT = "你的豆包接入点"
```

#### [ZHIPU] - 智谱配置

```ini
API_KEY = "你的智谱API密钥"
MODEL = "glm-4.7"
USE_CODING_ENDPOINT = False  # 是否使用 Coding 专用端点
```

#### [DEEPSEEK] - DeepSeek 配置

```ini
API_KEY = "你的DeepSeek API密钥"
MODEL = "deepseek-chat"  # 或 deepseek-reasoner
```

## 项目结构

```
doubao_backend/
├── main.py                    # 入口文件
├── requirements.txt           # 依赖包
├── credentials.config         # API 凭证配置（自动生成）
├── api/
│   ├── base_api.py           # AI 接口抽象基类
│   ├── api_factory.py        # API 工厂类（管理多个服务商）
│   ├── param_schema.py       # 参数定义和校验模块
│   ├── doubao.py             # 豆包 API 实现
│   ├── zhipu.py              # 智谱 AI API 实现
│   └── deepseek.py           # DeepSeek API 实现
├── models/
│   ├── message.py            # 消息模型
│   └── session_manager.py    # 会话管理器
└── server/
    └── web_server.py         # Flask Web 服务器
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

### 添加新的参数类型

编辑 `api/param_schema.py`，在 `ParamType` 枚举中添加新类型，并在 `ProviderParam.validate()` 方法中添加对应的校验逻辑。

## 常见问题

### Q: 如何切换不同的 AI 服务商？

A: 在请求中添加 `provider` 参数，或者在 `credentials.config` 的 `[default_provider]` 段中设置 `PROVIDER`。

### Q: 如何清除会话历史？

A: 设置 `preserve` 参数为 `false`，或者创建新的会话 ID。

### Q: 支持哪些 AI 服务商？

A: 目前支持豆包（Doubao）、智谱 AI（Zhipu）和 DeepSeek。你可以按照扩展指南添加新的服务商。

### Q: 如何设置系统提示词？

A: 在请求中添加 `system_message` 参数，或者在创建会话时指定。

### Q: 智谱 AI 的 Coding 端点有什么用？

A: Coding 端点是智谱 AI 专门为编程任务优化的端点，适合代码生成、代码审查等场景。在配置中设置 `USE_CODING_ENDPOINT = True` 即可启用。

### Q: 配置文件格式错误怎么办？

A: 程序启动时会自动校验配置文件，如果格式错误或缺少必填参数，会抛出详细的错误信息。请根据错误提示修正配置。

## 许可证

本项目仅供学习和研究使用。

## 贡献

欢迎提交 Issue 和 Pull Request！
