import uuid
from typing import Dict

from api.doubao import Doubao
from models.message import Message


class Session:
    def __init__(self, id, client: Doubao, messages: Message) -> None:
        self.id = id
        self.messages = messages
        self.client = client

    def chat_once(self, question: str):
        return self.client.reason(self.messages.generate_messages_jar(question))

    def chat_preserving_history(self, message: str):
        response_content = self.chat_once(message)
        self.messages.preserve_history(message, response_content)
        return response_content

    def clear_history(self):
        self.messages._messages_user_and_assistant_part = []

    def adjust_system_message(self, system_message: str):
        self.messages._messages_system_part = [self.messages.construct_system_message(system_message)]


class SessionManager:
    def __init__(self) -> None:
        self.pool: Dict[str, Session] = dict()
        self.doubao_client = Doubao()

    def new_session(self, id=None, system_message=None):
        if not id:
            id = str(uuid.uuid4())
        session = Session(id, self.doubao_client, Message(system_message))
        self.pool[id] = session
        return session

    def get_or_create_session(self, id=None):
        if id not in self.pool:
            return self.new_session(id)
        else:
            return self.pool[id]
