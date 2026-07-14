from flask import Flask, jsonify, request
from flask_cors import CORS

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
        "user_message : 用户消息(必填)",
    ]
    return "<br>".join(content_lines)


@app.route("/inspect", methods=["GET"])
def inspect_all_messages():
    return jsonify([m.messages.messages for m in sm.pool.values()])


def _should_preserve_history(preserve):
    if isinstance(preserve, bool):
        return preserve
    if isinstance(preserve, str):
        return preserve.strip().lower() in ["true", "1", "yes"]
    return False


def _chat_using_parameters(id, system_message, user_message, preserve, provider):
    if not user_message:
        return "缺少必填参数: user_message", 400

    preserve = _should_preserve_history(preserve)

    session = sm.get_or_create_session(id, provider=provider)
    if system_message:
        session.adjust_system_message(system_message)

    if preserve:
        answer = session.chat_preserving_history(user_message)
    else:
        answer = session.chat_once(user_message)

    return str(answer)


@app.route("/", methods=["POST"])
def process_chat_request_port():
    payload = request.get_json()
    id = payload.get("id")
    system_message = payload.get("system_message")
    user_message = payload["user_message"]
    preserve = payload.get("preserve")
    provider = payload.get("provider")

    return _chat_using_parameters(id, system_message, user_message, preserve, provider)


@app.route("/", methods=["GET"])
def process_chat_request_get():
    id = request.args.get("id")
    system_message = request.args.get("system_message")
    user_message = request.args.get("user_message")
    preserve = request.args.get("preserve")
    provider = request.args.get("provider")

    return _chat_using_parameters(id, system_message, user_message, preserve, provider)
