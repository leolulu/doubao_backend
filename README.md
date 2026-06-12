# 多 AI 服务商网关服务

一个支持多 AI 服务商的对话 API 网关服务，基于 Flask 构建。支持豆包、智谱、DeepSeek、MiniMax、Kimi Code 等多个 AI 服务商，提供统一的 RESTful API 接口。

## 功能特性

- ✅ 支持多 AI 服务商（豆包、智谱、DeepSeek、MiniMax、Kimi Code）
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
[designated_provider]
# 系统配置
# 指定使用的服务商名称
PROVIDER = doubao

[DOUBAO]
# API 密钥，可填单个密钥，也可用逗号配置备用密钥
API_KEY = 
# 访问点（模型标识），可填单个值，也可用逗号配置备用访问点
ACCESS_POINT = 

[ZHIPU]
# API 密钥，可填单个密钥，也可用逗号配置备用密钥
API_KEY = 
# 模型名称（如 glm-4.7），可填单个模型，也可用逗号配置备用模型
MODEL = 
# 是否使用 Coding 专用端点
USE_CODING_ENDPOINT = False

[DEEPSEEK]
# API 密钥，可填单个密钥，也可用逗号配置备用密钥
API_KEY =
# 模型名称（如 deepseek-chat 或 deepseek-reasoner），可填单个模型，也可用逗号配置备用模型
MODEL =

[MINIMAX]
# API 密钥，可填单个密钥，也可用逗号配置备用密钥
API_KEY =
# 模型名称（如 MiniMax-M2.5），可填单个模型，也可用逗号配置备用模型
MODEL =

[KIMI]
# Kimi Code API Key，可填单个密钥，也可用逗号配置备用密钥
API_KEY =
# 模型名称（如 kimi-for-coding 或 kimi-k2.6），可填单个模型，也可用逗号配置备用模型
MODEL = kimi-k2.6

[CHAT_COMPLETION:PROVIDER_NAME]
# Generic OpenAI-compatible Chat Completions endpoint.
# Enable it with: PROVIDER = chat_completion:provider_name
BASE_URL =
API_KEY =
MODEL =
```

### 3. 启动服务

```bash
python main.py
```

服务将在 `http://0.0.0.0:11301` 启动。

### 4. 运行测试

当前测试使用 Python 标准库 `unittest`，通过 `uv` 按 `requirements.txt` 准备依赖并运行：

```bash
uv run --with-requirements requirements.txt python -B -m unittest discover -s tests -v
```

当前测试重点覆盖配置校验、供应商回退、请求重试、飞书通知、消息与会话管理、HTTP 网关入口，以及各服务商请求适配层。

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

# 使用 MiniMax
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "你好",
    "provider": "minimax"
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

### MiniMax

使用 REST API 调用 MiniMax（OpenAI 兼容格式）。

**配置参数：**
- `API_KEY`: API 密钥（必填）
- `MODEL`: 模型名称，如 `MiniMax-M2.5`（必填）

**支持的模型：**
- `MiniMax-M2.5`（上下文 204,800）
- `MiniMax-M2.5-highspeed`
- `MiniMax-M2.1` / `MiniMax-M2.1-highspeed`
- `MiniMax-M2`

### Kimi Code

使用 Kimi Code API。配置文件只需要填写 API Key 和模型名，请求协议、Base URL、必要请求头和输出 token 上限等细节由服务商适配层内部处理。

**配置参数：**
- `API_KEY`: Kimi Code API Key（必填）
- `MODEL`: 模型名称，如 `kimi-k2.6` 或 `kimi-for-coding`（必填，默认 `kimi-k2.6`）

推荐优先配置 `kimi-k2.6`。如需使用官方稳定模型标识，可以配置 `kimi-for-coding`；也可以写成 `kimi-k2.6,kimi-for-coding` 做模型回退。

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
┌────────▼─────┐ ┌────▼──────┐ ┌─▼──────────┐ ┌──▼────────┐
│   Doubao     │ │  Zhipu    │ │  DeepSeek  │ │ MiniMax   │
│  (SDK 调用)   │ │  (REST)   │ │  (REST)    │ │  (REST)  │
└──────────────┘ └───────────┘ └─────────────┘ └──────────┘
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

编辑 `api/api_factory.py`，在 `_register_provider_classes` 方法中添加注册：

```python
from api.new_provider import NewProvider

class ApiFactory:
    def _register_provider_classes(self):
        """注册可用的服务商类"""
        self._provider_classes["doubao"] = Doubao
        self._provider_classes["zhipu"] = Zhipu
        self._provider_classes["deepseek"] = DeepSeek
        self._provider_classes["minimax"] = MiniMax
        self._provider_classes["new_provider"] = NewProvider  # 添加这一行
```

**注意**：现在系统只注册配置文件中指定的服务商，不需要手动注册所有服务商实例。

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

配置文件使用 INI 格式，包含以下部分。旧的单值写法仍然有效，也可以用逗号配置备用链：

#### [designated_provider] - 系统配置

```ini
PROVIDER = doubao,zhipu,deepseek  # 按从左到右的优先级配置供应商回退链
```

`PROVIDER` 仍然支持旧的单供应商写法，例如 `PROVIDER = doubao`。如果写多个供应商，系统启动时会立即校验所有供应商名称和对应配置段，避免运行到回退时才发现后续供应商配置错误。

供应商回退顺序按逗号从左到右执行。例如 `PROVIDER = doubao,zhipu,deepseek` 时，会先尝试豆包；豆包内部所有 `API_KEY` 和 `ACCESS_POINT` 组合都失败后，会发送飞书供应商切换通知，然后切换到智谱；所有供应商都失败后，会发送最终失败通知。

请求参数 `provider` 会覆盖默认供应商链。传入 `provider=zhipu` 时，本次请求只使用智谱，不会走 `PROVIDER` 里的多供应商回退链。

#### [DOUBAO] - 豆包配置

```ini
API_KEY = "你的豆包API密钥"
ACCESS_POINT = "你的豆包接入点"
```

`API_KEY` 可以写单个密钥，也可以写逗号分隔的多个备用密钥。豆包使用 `ACCESS_POINT` 指定访问点，`ACCESS_POINT` 可以写单个值，也可以写逗号分隔的多个备用访问点。

```ini
[DOUBAO]
API_KEY = key-a,key-b
ACCESS_POINT = ep-a,ep-b
```

#### [ZHIPU] - 智谱配置

```ini
API_KEY = "你的智谱API密钥"
MODEL = "glm-4.7"
USE_CODING_ENDPOINT = False  # 是否使用 Coding 专用端点
```

普通服务商使用 `MODEL` 指定模型。`MODEL` 可以写单个模型，也可以写逗号分隔的多个备用模型。

```ini
[ZHIPU]
API_KEY = key-a,key-b
MODEL = model-a,model-b
USE_CODING_ENDPOINT = False
```

备用链的尝试顺序是先按 `API_KEY`，再按 `MODEL` 或 `ACCESS_POINT`。例如 `API_KEY = key-a,key-b` 且 `MODEL = model-a,model-b` 时，依次尝试 `key-a` + `model-a`、`key-a` + `model-b`、`key-b` + `model-a`、`key-b` + `model-b`。每个组合都会使用完整重试次数。单供应商模式下，所有组合失败后会发送飞书失败通知；多供应商模式下，当前供应商所有组合失败后会由外层供应商回退链发送切换通知，并继续尝试下一个供应商。

逗号两侧可以有空格，程序会自动去掉空白。不要留下空项，例如 `key-a,,key-b`、`model-a,`、`,model-a` 都是无效写法。

#### [DEEPSEEK] - DeepSeek 配置

```ini
API_KEY = "你的DeepSeek API密钥"
MODEL = "deepseek-chat"  # 或 deepseek-reasoner
```

#### [MINIMAX] - MiniMax 配置

```ini
API_KEY = "你的MiniMax API密钥"
MODEL = "MiniMax-M2.5"
```

#### [KIMI] - Kimi Code 配置

```ini
API_KEY = "你的Kimi Code API Key"
MODEL = "kimi-k2.6"  # 也可以配置 kimi-k2.6,kimi-for-coding 做模型回退
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
│   ├── deepseek.py           # DeepSeek API 实现
│   ├── minimax.py            # MiniMax API 实现
│   └── kimi.py               # Kimi Code API 实现
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

A: 在请求中添加 `provider` 参数可以强制本次请求使用某一个服务商；或者在 `credentials.config` 的 `[designated_provider]` 段中设置 `PROVIDER`。`PROVIDER` 支持逗号分隔的供应商回退链，例如 `PROVIDER = doubao,zhipu,deepseek`。

### Q: 如何清除会话历史？

A: 设置 `preserve` 参数为 `false`，或者创建新的会话 ID。

### Q: 支持哪些 AI 服务商？

A: 目前支持豆包（Doubao）、智谱 AI（Zhipu）、DeepSeek、MiniMax 和 Kimi Code。你可以按照扩展指南添加新的服务商。

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

## Generic Chat Completions

Use `chat_completion:<alias>` in `PROVIDER` for OpenAI-compatible Chat Completions services that do not need a custom provider adapter.

```ini
[designated_provider]
PROVIDER = chat_completion:provider_name,zhipu,chat_completion:another_provider

[CHAT_COMPLETION:PROVIDER_NAME]
BASE_URL = https://example.com/v1
API_KEY = your-api-key
MODEL = your-model

[CHAT_COMPLETION:ANOTHER_PROVIDER]
BASE_URL = https://another-example.com/v1
API_KEY = another-api-key
MODEL = another-model
```

`BASE_URL` should point to the OpenAI-compatible base path, usually ending with `/v1`; the provider appends `/chat/completions` automatically. `API_KEY` and `MODEL` keep the same comma-separated fallback syntax as the fixed providers. Failed HTTP responses and request exceptions are written to `logs/llm_error_requests.jsonl`, while successful requests are written to the rolling `logs/llm_success_requests.jsonl` file that keeps the latest 300 records. These request logs do not include the API key.
