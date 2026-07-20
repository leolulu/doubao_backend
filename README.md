# 多 AI 服务商网关服务

一个支持多 AI 服务商的对话 API 网关服务，基于 Flask 构建。支持豆包、智谱、DeepSeek、MiniMax、Kimi Code 等多个 AI 服务商，提供统一的 RESTful API 接口。

## 功能特性

- ✅ 支持多 AI 服务商（豆包、智谱、DeepSeek、MiniMax、Kimi Code）
- ✅ 会话管理和历史记录
- ✅ RESTful API 接口（GET/POST）
- ✅ 允许任意来源的浏览器跨域访问（CORS）
- ✅ 可扩展架构，轻松添加新的 AI 服务商
- ✅ 支持系统消息设置
- ✅ 支持按会话选择是否追加对话历史
- ✅ 自动配置文件生成和参数校验
- ✅ 智谱 AI 支持 Coding 专用端点
- ✅ `credentials.config` 热更新（基于 watchfiles，无需重启服务）

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

依赖声明在 `pyproject.toml` 中，并由 `uv.lock` 锁定版本。直接使用 `uv run` 启动程序或运行测试时，uv 也会自动创建或更新项目目录下的 `.venv` 并同步依赖，因此通常无需单独执行 `uv sync`。

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
# 通用OpenAI兼容接口。
# 启用方式: PROVIDER = chat_completion:provider_name
BASE_URL =
API_KEY =
MODEL =
```

### 3. 启动服务

```bash
uv run python main.py
```

服务将在 `http://0.0.0.0:11301` 启动。

### 4. 运行测试

当前测试使用 Python 标准库 `unittest`。`uv run` 会按 `pyproject.toml` 和 `uv.lock` 自动准备依赖并运行：

```bash
uv run python -B -m unittest discover -s tests -v
```

当前测试重点覆盖配置校验、供应商回退、请求重试、飞书通知、消息与会话管理、HTTP 网关入口，以及各服务商请求适配层。

## API 使用

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 否 | 会话 ID；连续多轮请求必须使用同一个值。不提供时服务端会自动生成；流式接口会在 `session` 事件中返回生成的 ID，非流式接口仍只返回模型回答 |
| `system_message` | string | 否 | 系统提示词；在同一会话中会持续生效，传入新的非空值会替换旧值 |
| `preserve` | boolean/string | 否 | 是否在模型成功回答后，将本轮 `user` 和 `assistant` 消息追加到会话历史；POST 推荐使用布尔值，字符串兼容 `true/1/yes`，默认 `false` |
| `provider` | string | 否 | AI 服务商名称，仅在创建新会话时使用；不提供则使用默认服务商 |
| `model` | string | 否 | 模型名称，仅在创建新会话时使用；提供时必须同时提供 `provider`，并且必须精确匹配该服务商在配置文件中的 `MODEL`（豆包匹配 `ACCESS_POINT`） |
| `user_message` | string | 是 | 用户消息 |

请求路由分为自动和手动两种模式：

| `provider` | `model` | 行为 |
|------------|---------|------|
| 不提供 | 不提供 | 使用配置中的默认供应商、模型、API Key 和完整回退链 |
| 提供 | 不提供 | 使用当前的指定供应商逻辑和该供应商配置的回退链 |
| 不提供 | 提供 | 返回 400；`model` 不能单独使用 |
| 提供 | 提供 | 手动模式；固定使用指定供应商和模型，不切换其他供应商或模型，继续保留 API Key 切换与原有重试机制 |

手动模式以 `credentials.config` 为唯一可用范围。服务商必须有对应配置段，模型名称区分大小写并且必须出现在该段的 `MODEL` 列表中；豆包将 `ACCESS_POINT` 视为模型列表。请求参数 `model` 只接受单个值，不能使用逗号指定临时模型回退链。

#### 手动模式响应

手动模式沿用现有 `/` 和 `/stream` 的响应格式。API Key 切换和请求重试都在服务端内部完成，只有成功返回或全部尝试失败后才会产生最终 HTTP/SSE 响应。

| 端点 | 场景 | HTTP 状态 | 响应 |
|------|------|-----------|------|
| `/` | 指定的 provider/model 请求成功 | 200 | 响应体直接是模型回答文本，不是 JSON |
| `/` | 参数组合或配置匹配失败 | 400 | 响应体是错误文本，例如 `指定 model 时必须同时指定 provider` 或 `模型 'model-x' 未配置在服务商 'provider-x' 中` |
| `/` | provider/model 有效，但上游在 API Key 切换和重试后仍然失败，或上游响应无法解析 | 500 | 当前由 Flask 返回 Internal Server Error；详细上游状态和请求模型见 `logs/llm_error_requests.jsonl` |
| `/stream` | 指定的 provider/model 流式请求成功 | 200 | `text/event-stream`；依次返回 `session`、一个或多个 `delta`、`done` |
| `/stream` | 参数组合或配置匹配失败 | 400 | 流开始前返回错误文本，响应不是 SSE |
| `/stream` | 上游在首个可见文本前失败，API Key 切换和重试后仍未成功 | 502 | 响应体为 `模型流式调用失败`，响应不是 SSE |
| `/stream` | 已经输出可见文本后上游中断 | 200 | SSE 最后返回 `error` 事件，随后连接结束，不再返回 `done` |

非流式成功示例：

```text
HTTP/1.1 200 OK

模型返回的回答文本
```

参数或配置匹配失败示例：

```text
HTTP/1.1 400 BAD REQUEST

模型 'model-x' 未配置在服务商 'provider-x' 中
```

流式中途失败时的最后一个事件：

```text
data: {"type": "error", "code": "upstream_interrupted", "message": "模型流式响应中断"}
```

这里的 500 或 502 表示请求已经通过本地 provider/model 校验，但最终没有得到可用的完整上游回答。判断凭据失效、模型下线、限流、上游服务异常或响应格式不兼容时，应结合错误日志中的 `provider`、`request_body.model`、`response_status_code` 和异常类型，不应仅根据外层 HTTP 状态判断为本地路由错误。日志不会记录 API Key。

### 会话与历史记录

`id` 和 `preserve` 分别控制会话定位和历史写入：

- `id` 用于找到同一个内存会话。相同 `id` 会复用已有的历史、系统提示词和服务商客户端。`provider` 和 `model` 只在首次创建该会话时生效，后续传入不同值会继续使用原客户端。
- `preserve=true` 会在模型成功回答后，把本轮用户消息和模型回答追加到该会话的历史中。
- 无论本轮是否传入 `preserve=true`，请求都会读取该会话中已经保存的历史；`preserve` 只控制是否追加本轮问答。
- `preserve=false` 或省略 `preserve` 不会清除已有历史，只会让本轮问答不进入历史。

因此，连续且完整的多轮对话需要每一轮都使用相同的 `id`，并传入 `preserve=true`。POST JSON 使用布尔值 `true`，GET 查询参数使用字符串 `true`。如果某一轮省略 `preserve`，下一轮将看不到被省略保存的那一轮问答。

调用非流式 `/` 接口且不传 `id` 时，每次请求都会创建新的随机 ID。由于非流式响应只包含模型回答，客户端无法继续该自动创建的会话。调用 `/stream` 时，服务端会通过首个 `session` 事件返回实际 ID，客户端可以在后续请求中继续使用。

会话及其消息历史只保存在当前服务进程的内存中。服务重启后历史会丢失，目前没有持久化、自动过期或历史长度限制。

内部发送给模型的消息格式如下：

```json
[
  {"role": "system", "content": "你是一个友好的助手"},
  {"role": "user", "content": "我叫小明"},
  {"role": "assistant", "content": "你好，小明"},
  {"role": "user", "content": "我叫什么？"}
]
```

### 示例请求

#### GET 请求

```bash
curl "http://localhost:11301/?id=conversation-001&user_message=你好&preserve=true"
```

#### 使用 GET 连续多轮对话

GET 的所有参数都位于查询字符串中。包含中文或其他特殊字符时，建议使用 `curl --get --data-urlencode` 自动进行 URL 编码。

第一轮设置固定的会话 ID、开启历史追加，并按需设置系统提示词：

```bash
curl --get "http://localhost:11301/" \
  --data-urlencode "id=conversation-001" \
  --data-urlencode "preserve=true" \
  --data-urlencode "system_message=你是一个友好的助手" \
  --data-urlencode "user_message=我叫小明"
```

第二轮继续使用相同的 `id` 和 `preserve=true`，已经设置的 `system_message` 可以省略：

```bash
curl --get "http://localhost:11301/" \
  --data-urlencode "id=conversation-001" \
  --data-urlencode "preserve=true" \
  --data-urlencode "user_message=我叫什么？"
```

#### POST 请求

```bash
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "id": "conversation-001",
    "user_message": "你好",
    "preserve": true,
    "system_message": "你是一个友好的助手"
  }'
```

#### 使用 POST 连续多轮对话

第一轮设置固定的会话 ID、开启历史追加，并按需设置系统提示词：

```bash
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "id": "conversation-001",
    "preserve": true,
    "system_message": "你是一个友好的助手",
    "user_message": "我叫小明"
  }'
```

后续每一轮继续使用相同的 `id` 和 `preserve=true`。已经设置的 `system_message` 可以省略：

```bash
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "id": "conversation-001",
    "preserve": true,
    "user_message": "我叫什么？"
  }'
```

#### GET 和 POST 如何选择

- GET 适合短消息、浏览器直接访问或临时调试。查询参数需要进行 URL 编码，并可能出现在浏览器历史、服务器访问日志或代理日志中。
- POST 将参数放在 JSON 请求体中，更适合较长的用户消息和系统提示词，也能减少消息内容直接暴露在 URL 及常见访问日志中的情况。
- 正式调用推荐使用 POST；无论选择 GET 还是 POST，多轮对话都需要保持相同的 `id` 并持续传入 `preserve=true`。

### 流式接口

流式接口使用 `/stream`，支持 GET 和 POST，请求参数及多轮会话语义与非流式 `/` 完全相同。响应类型为 `text/event-stream`，每个 SSE 事件的 `data` 都是一个 JSON 对象。

推荐使用 POST。`curl` 增加 `-N` 可以关闭客户端输出缓冲，让内容到达后立即显示：

```bash
curl -N -X POST http://localhost:11301/stream \
  -H "Content-Type: application/json" \
  -d '{
    "id": "conversation-001",
    "preserve": true,
    "system_message": "你是一个友好的助手",
    "user_message": "请介绍一下你自己"
  }'
```

GET 的调用方式只需将路径改为 `/stream`：

```bash
curl -N --get "http://localhost:11301/stream" \
  --data-urlencode "id=conversation-001" \
  --data-urlencode "preserve=true" \
  --data-urlencode "user_message=请介绍一下你自己"
```

响应示例：

```text
data: {"type": "session", "id": "conversation-001"}

data: {"type": "delta", "content": "你"}

data: {"type": "delta", "content": "好"}

data: {"type": "done", "preserved": true}

```

事件类型：

| `type` | 说明 |
|--------|------|
| `session` | 本次请求实际使用的会话 ID；未传 `id` 时应保存这里返回的自动生成 ID |
| `delta` | 本次新增的回答文本，按到达顺序直接拼接 `content` 即可 |
| `done` | 流正常结束；`preserved` 表示本轮是否已写入会话历史 |
| `error` | 流开始后上游响应中断；该事件之后连接结束，不会出现 `done` |

请求参数无效时会在流开始前直接返回 HTTP 400；上游在首个可见文本前失败且重试、回退仍无法成功时直接返回 HTTP 502。此时响应不是 SSE 事件流。

Python 请求方只需在原有请求上增加 `stream=True` 并逐行解析：

```python
import json

import requests


with requests.post(
    "http://localhost:11301/stream",
    json={
        "id": "conversation-001",
        "preserve": True,
        "user_message": "你好",
    },
    stream=True,
) as response:
    response.raise_for_status()
    for line in response.iter_lines(decode_unicode=True):
        if not line.startswith("data: "):
            continue
        event = json.loads(line.removeprefix("data: "))
        if event["type"] == "delta":
            print(event["content"], end="", flush=True)
        elif event["type"] == "error":
            raise RuntimeError(event["message"])
```

流式输出只包含最终回答，不包含各服务商可能返回的 reasoning/thinking 内容。同一个会话 ID 的请求会串行执行，避免并发请求打乱历史顺序。

`preserve=true` 只在流正常完成后写入完整问答。客户端断开、上游中途失败或收到 `error` 时，残缺回答不会进入历史。首个可见文本到达前仍允许现有的重试和服务商回退；已经向客户端输出文本后不会再透明切换模型或服务商，避免把两份回答拼接在一起。

#### 指定服务商或模型

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

# 手动固定智谱和模型；glm-4.7 必须配置在 [ZHIPU] 的 MODEL 中
curl -X POST http://localhost:11301/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "你好",
    "provider": "zhipu",
    "model": "glm-4.7"
  }'
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET/POST | 发送聊天请求 |
| `/stream` | GET/POST | 发送流式聊天请求，返回 SSE 事件流 |
| `/help` | GET | 查看帮助信息 |
| `/inspect` | GET | 查看所有会话的 ID 和消息历史 |
| `/models` | GET | 查看当前配置中可手动选择的服务商和模型 |

`GET /models` 返回当前进程已加载配置中可手动选择的 provider/model：

```json
{
  "providers": [
    {
      "id": "zhipu",
      "models": ["glm-4.7", "glm-4-flash"]
    },
    {
      "id": "doubao",
      "models": ["ep-a", "ep-b"]
    }
  ]
}
```

`id` 是请求中的 `provider` 值，`models` 中的字符串是请求中的 `model` 值。普通服务商从 `MODEL` 读取模型，豆包从 `ACCESS_POINT` 读取并同样通过 `model` 参数提交。返回顺序与配置文件一致，模型名称保留配置中的大小写。默认供应商链之外、配置完整且项目支持的服务商也会返回。响应不会包含 API Key、Base URL 等其他配置内容，也不会连接上游服务检查模型或凭据状态。服务运行期间修改并成功热加载 `credentials.config` 后，该列表会立即更新，无需重启服务。

`GET /inspect` 返回当前进程内存中的全部会话，例如：

```json
[
  {
    "id": "conversation-001",
    "messages": [
      {"role": "user", "content": "你好"},
      {"role": "assistant", "content": "你好，有什么可以帮你？"}
    ]
  }
]
```

### 浏览器跨域访问

服务端已对所有路由启用全局 CORS，允许任意来源跨域访问。浏览器前端可以从不同的域名、主机或端口直接调用 `/`、`/stream`、`/help`、`/inspect` 和 `/models`；使用 `Content-Type: application/json` 的 POST 请求所需的 OPTIONS 预检也已支持。

当前跨域配置不限制来源，也没有启用跨域凭证。curl、PowerShell、Python 及服务端之间的 HTTP 请求不受浏览器 CORS 机制影响。

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

### 通用OpenAI兼容接口

适用于兼容 OpenAI Chat Completions 协议、但不需要单独适配层的服务商。在 `[designated_provider]` 的 `PROVIDER` 中写 `chat_completion:<别名>`，并提供对应的 `[CHAT_COMPLETION:<别名>]` 配置段即可。

**配置参数：**
- `BASE_URL`: OpenAI 兼容接口的基础地址，通常以 `/v1` 结尾（必填）
- `API_KEY`: API 密钥（必填）
- `MODEL`: 模型名称（必填）

```ini
[designated_provider]
PROVIDER = chat_completion:provider_name,zhipu,chat_completion:another_provider

[CHAT_COMPLETION:PROVIDER_NAME]
BASE_URL = https://example.com/v1
API_KEY = 你的API密钥
MODEL = 你的模型名称

[CHAT_COMPLETION:ANOTHER_PROVIDER]
BASE_URL = https://another-example.com/v1
API_KEY = 另一个API密钥
MODEL = 另一个模型名称
```

`BASE_URL` 只需要写到 OpenAI 兼容接口的基础路径，程序会自动追加 `/chat/completions`。`API_KEY` 和 `MODEL` 继续支持逗号分隔的回退语法。HTTP 失败响应和请求异常会写入 `logs/llm_error_requests.jsonl`；成功请求会写入滚动日志 `logs/llm_success_requests.jsonl`，最多保留最近 300 条记录。请求日志不会记录 API 密钥。

## 架构说明

### 核心组件

```
┌─────────────────────────────────────────┐
│         Web Server (Flask)              │
│  - /help, /inspect, /, /stream         │
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

配置文件固定位于项目根目录下的 `credentials.config`，使用 INI 格式。旧的单值写法仍然有效，也可以用逗号配置备用链。

#### 热更新（Hot Reload）

通过 `uv run python main.py` 启动服务时，进程会用 `watchfiles` 监控根目录下的 `credentials.config`。保存该文件后，服务会在不重启的情况下重新加载配置。

热更新会立即影响：

- 默认供应商回退链（`[designated_provider] PROVIDER`）
- 各服务商的 API Key / 模型 / 访问点等运行时客户端配置
- `GET /models` 返回的可用 provider/model 列表
- **之后新建**的会话，以及新建会话时的手动 `provider` + `model` 选择

热更新**不会**影响：

- 已经创建并保存在内存中的会话（`Session`）
- 这些旧会话已经绑定的客户端、历史消息和系统提示词

设计原因：会话在创建时绑定客户端。如果热更新时强行改掉正在使用中的会话客户端，其他用户会感觉“对话中途模型/密钥莫名变了”。因此旧会话继续按创建时的客户端运行；新能力（例如新增模型）通过 `/models` 和新会话暴露。

其他约定：

- 本版只监控固定文件名 `credentials.config`，不监控目录、也不处理改名后的其它路径。
- 内容未变化时（例如编辑器重复保存同一内容）会按文件哈希跳过重载。
- 配置解析或校验失败时，**保留上一份可用配置**，服务继续运行，并打印详细错误日志；日志会汇总 provider 链、可用模型等变更信息，但会脱敏，不会输出 API Key 明文。
- 仅 import 模块或运行单元测试时不会启动文件监控；监控只在 `main.py` 入口启动。

#### [designated_provider] - 系统配置

```ini
PROVIDER = doubao,zhipu,deepseek  # 按从左到右的优先级配置供应商回退链
```

`PROVIDER` 仍然支持旧的单供应商写法，例如 `PROVIDER = doubao`。如果写多个供应商，系统启动时会立即校验所有供应商名称和对应配置段，避免运行到回退时才发现后续供应商配置错误。热更新时也会按同样规则校验整条链。

供应商回退顺序按逗号从左到右执行。例如 `PROVIDER = doubao,zhipu,deepseek` 时，会先尝试豆包；豆包内部所有 `API_KEY` 和 `ACCESS_POINT` 组合都失败后，会发送飞书供应商切换通知，然后切换到智谱；所有供应商都失败后，会发送最终失败通知。

创建新会话时，请求参数 `provider` 会覆盖默认供应商链。传入 `provider=zhipu` 时，该会话只使用智谱，不会走 `PROVIDER` 里的多供应商回退链。同一 `id` 的会话创建后会复用原有客户端，后续请求传入不同的 `provider` 不会切换服务商；热更新后也是如此，旧会话不会自动改绑。

同时传入 `provider` 和 `model` 时进入手动模式。程序会从该服务商配置段的 `MODEL` 中精确匹配请求模型；豆包改为匹配 `ACCESS_POINT`。匹配成功后只使用指定的供应商和模型，配置中的其他供应商和模型不会参与回退，多个 `API_KEY` 仍按配置顺序切换，每个请求仍使用统一重试机制。配置段或模型不存在、单独传入 `model`、传入空模型或逗号分隔的多个模型时返回 400。手动模式可以使用配置文件中存在且项目支持的服务商配置段，该服务商不需要位于默认 `PROVIDER` 回退链中。手动模式的可用范围以**当前已加载配置**为准，因此热更新成功后，新建会话可以使用新写入的模型。

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
├── main.py                    # 入口文件（启动 credentials 热更新监控）
├── pyproject.toml             # Python 版本与依赖声明
├── uv.lock                    # uv 依赖锁定文件
├── credentials.config         # API 凭证配置（自动生成，支持热更新）
├── api/
│   ├── base_api.py           # AI 接口抽象基类
│   ├── api_factory.py        # API 工厂类（管理多个服务商，支持 reload）
│   ├── credentials_watcher.py # credentials.config 文件监控
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
- **flask-cors**：跨域支持
- **requests**：HTTP 请求库
- **volcengine-python-sdk[ark]**：火山引擎 SDK（调用豆包 API）
- **watchfiles**：`credentials.config` 热更新文件监控

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

A: 创建新会话时，在请求中添加 `provider` 参数可以指定该会话使用某一个服务商；也可以在 `credentials.config` 的 `[designated_provider]` 段中设置默认的 `PROVIDER`。`PROVIDER` 支持逗号分隔的供应商回退链，例如 `PROVIDER = doubao,zhipu,deepseek`。同一 `id` 创建后会继续使用最初选定的客户端，后续请求无法通过修改 `provider` 切换服务商；需要切换时请使用新的会话 ID。

### Q: 如何手动指定模型？

A: 创建新会话时同时传入 `provider` 和 `model`。模型必须精确配置在该服务商的 `MODEL` 中，豆包则匹配 `ACCESS_POINT`。手动模式固定供应商和模型，不执行供应商或模型回退，但保留 API Key 切换和请求重试。`model` 不能单独使用，同一会话后续传入不同的 `provider` 或 `model` 不会切换客户端。

### Q: 如何清除会话历史？

A: 当前 HTTP API 没有提供清除已有会话历史的端点。需要开始空白对话时，请使用一个新的会话 ID。`preserve=false` 只会阻止本轮问答追加到历史，不会删除该会话中已经保存的消息。

### Q: 支持哪些 AI 服务商？

A: 目前支持豆包（Doubao）、智谱 AI（Zhipu）、DeepSeek、MiniMax 和 Kimi Code。你可以按照扩展指南添加新的服务商。

### Q: 如何设置系统提示词？

A: 在请求中添加非空的 `system_message` 参数。同一会话后续省略该参数时会继续沿用原值；再次传入新的非空值会替换原值。当前 HTTP API 无法通过空字符串清除已经设置的系统提示词。

### Q: 智谱 AI 的 Coding 端点有什么用？

A: Coding 端点是智谱 AI 专门为编程任务优化的端点，适合代码生成、代码审查等场景。在配置中设置 `USE_CODING_ENDPOINT = True` 即可启用。

### Q: 配置文件格式错误怎么办？

A: 程序启动时会自动校验配置文件，如果格式错误或缺少必填参数，会抛出详细的错误信息。请根据错误提示修正配置。服务运行中热更新失败时，会保留上一份可用配置并打印错误日志，不会把错误配置应用到运行时。

### Q: 修改 credentials.config 后需要重启吗？

A: 通过 `uv run python main.py` 启动时不需要。保存 `credentials.config` 后，服务会热加载默认供应商链、provider 客户端和 `/models` 列表。已经存在的会话不会改绑客户端；若要让某个对话用上新配置，请使用新的会话 ID。

### Q: 热更新会不会把正在聊天的会话切到别的模型？

A: 不会。已有会话继续使用创建时绑定的客户端。热更新只影响新会话、默认回退链，以及 `/models` 的发现结果。

## 许可证

本项目仅供学习和研究使用。

## 贡献

欢迎提交 Issue 和 Pull Request！
