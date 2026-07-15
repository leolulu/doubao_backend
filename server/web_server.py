import json

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from api.api_factory import ManualModelSelectionError
from models.session_manager import SessionManager

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
sm = SessionManager()


@app.route("/help", methods=["GET"])
def home():
    content_lines = [
        "可接受请求参数:",
        "",
        "id : 会话id, 不提供则自动生成",
        "system_message : 系统消息, 不提供则不使用系统消息",
        "preserve : 是否对于相同的会话id保留历史记录",
        "provider : AI服务商名称(可选)，不提供则使用默认服务商",
        "model : 模型名称(可选)，提供时必须同时提供 provider",
        "user_message : 用户消息(必填)",
    ]
    return "<br>".join(content_lines)


@app.route("/inspect", methods=["GET"])
def inspect_all_messages():
    return jsonify([
        {"id": session.id, "messages": session.snapshot_messages()}
        for session in sm.list_sessions()
    ])


def _should_preserve_history(preserve):
    if isinstance(preserve, bool):
        return preserve
    if isinstance(preserve, str):
        return preserve.strip().lower() in ["true", "1", "yes"]
    return False


def _validate_manual_selection_parameters(provider, model):
    if model is None:
        return None
    if provider is None:
        return "指定 model 时必须同时指定 provider"
    if not isinstance(provider, str):
        return "参数 'provider' 必须是字符串"
    if not isinstance(model, str):
        return "参数 'model' 必须是字符串"
    if not provider.strip():
        return "参数 'provider' 不能为空"
    if not model.strip():
        return "参数 'model' 不能为空"
    if "," in model:
        return "参数 'model' 只能指定一个模型"
    return None


def _chat_using_parameters(id, system_message, user_message, preserve, provider, model):
    if not user_message:
        return "缺少必填参数: user_message", 400

    validation_error = _validate_manual_selection_parameters(provider, model)
    if validation_error:
        return validation_error, 400

    preserve = _should_preserve_history(preserve)

    try:
        session = sm.get_or_create_session(id, provider=provider, model=model)
    except ManualModelSelectionError as exception:
        return str(exception), 400
    answer = session.chat(
        user_message,
        preserve=preserve,
        system_message=system_message,
    )

    return str(answer)


def _encode_sse_event(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_chat_using_parameters(id, system_message, user_message, preserve, provider, model):
    if not user_message:
        return "缺少必填参数: user_message", 400

    validation_error = _validate_manual_selection_parameters(provider, model)
    if validation_error:
        return validation_error, 400

    preserve = _should_preserve_history(preserve)
    try:
        session = sm.get_or_create_session(id, provider=provider, model=model)
    except ManualModelSelectionError as exception:
        return str(exception), 400
    stream = session.chat_stream(
        user_message,
        preserve=preserve,
        system_message=system_message,
    )

    try:
        first_chunk = next(stream)
    except StopIteration:
        first_chunk = None
    except Exception:
        return "模型流式调用失败", 502

    @stream_with_context
    def generate():
        try:
            yield _encode_sse_event({"type": "session", "id": session.id})
            if first_chunk is not None:
                yield _encode_sse_event({"type": "delta", "content": first_chunk})
            for chunk in stream:
                yield _encode_sse_event({"type": "delta", "content": chunk})
            yield _encode_sse_event({"type": "done", "preserved": preserve})
        except GeneratorExit:
            raise
        except Exception:
            yield _encode_sse_event({
                "type": "error",
                "code": "upstream_interrupted",
                "message": "模型流式响应中断",
            })
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

    response = Response(generate(), content_type="text/event-stream; charset=utf-8")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route("/", methods=["POST"])
def process_chat_request_port():
    payload = request.get_json()
    if not isinstance(payload, dict):
        return "请求体必须是 JSON 对象", 400
    id = payload.get("id")
    system_message = payload.get("system_message")
    user_message = payload.get("user_message")
    preserve = payload.get("preserve")
    provider = payload.get("provider")
    model = payload.get("model")

    return _chat_using_parameters(id, system_message, user_message, preserve, provider, model)


@app.route("/", methods=["GET"])
def process_chat_request_get():
    id = request.args.get("id")
    system_message = request.args.get("system_message")
    user_message = request.args.get("user_message")
    preserve = request.args.get("preserve")
    provider = request.args.get("provider")
    model = request.args.get("model")

    return _chat_using_parameters(id, system_message, user_message, preserve, provider, model)


@app.route("/stream", methods=["POST"])
def process_stream_chat_request_post():
    payload = request.get_json()
    if not isinstance(payload, dict):
        return "请求体必须是 JSON 对象", 400
    id = payload.get("id")
    system_message = payload.get("system_message")
    user_message = payload.get("user_message")
    preserve = payload.get("preserve")
    provider = payload.get("provider")
    model = payload.get("model")

    return _stream_chat_using_parameters(
        id,
        system_message,
        user_message,
        preserve,
        provider,
        model,
    )


@app.route("/stream", methods=["GET"])
def process_stream_chat_request_get():
    id = request.args.get("id")
    system_message = request.args.get("system_message")
    user_message = request.args.get("user_message")
    preserve = request.args.get("preserve")
    provider = request.args.get("provider")
    model = request.args.get("model")

    return _stream_chat_using_parameters(
        id,
        system_message,
        user_message,
        preserve,
        provider,
        model,
    )
