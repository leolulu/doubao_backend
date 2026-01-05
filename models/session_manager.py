import uuid
from typing import Dict, Optional

from api.api_factory import ApiFactory
from api.base_api import BaseApi
from models.message import Message


class Session:
    def __init__(self, id, client: BaseApi, messages: Message) -> None:
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
    def __init__(self, api_factory: Optional[ApiFactory] = None) -> None:
        self.pool: Dict[str, Session] = dict()
        self.api_factory = api_factory or ApiFactory()

    def new_session(self, id=None, system_message=None, provider=None):
        """
        创建新会话
        
        Args:
            id: 会话 ID，如果不提供则自动生成
            system_message: 系统消息
            provider: AI 服务商名称，如果不提供则使用默认服务商
        
        Returns:
            Session 实例
        """
        if not id:
            id = str(uuid.uuid4())
        client = self.api_factory.get_client(provider)
        session = Session(id, client, Message(system_message))
        self.pool[id] = session
        return session

    def get_or_create_session(self, id=None, provider=None):
        """
        获取或创建会话
        
        Args:
            id: 会话 ID
            provider: AI 服务商名称，仅在创建新会话时使用
        
        Returns:
            Session 实例
        """
        if id not in self.pool:
            return self.new_session(id, provider=provider)
        else:
            return self.pool[id]
