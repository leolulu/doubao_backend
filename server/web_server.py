from flask import Flask, jsonify, request

from models.session_manager import SessionManager

app = Flask(__name__)
sm = SessionManager()


@app.route("/", methods=["GET"])
def home():
    return f"可接受请求参数:<br><br>id: 会话id, 不提供则自动生成<br>system_message: 系统消息, 不提供则不使用系统消息<br>user_message: 用户消息(必填)"


@app.route("/", methods=["POST"])
def submit():
    payload = request.get_json()
    id = payload.get("id")
    system_message = payload.get("system_message")
    user_message = payload["user_message"]

    session = sm.get_or_create_session(id)
    session.adjust_system_message(system_message)
    answer = session.chat_once(user_message)

    return str(answer)
