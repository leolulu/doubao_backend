import uuid
from collections.abc import Iterator
from threading import Lock, RLock
from typing import Dict, Optional

from api.api_factory import ApiFactory
from api.base_api import BaseApi
from models.message import Message


class Session:
    def __init__(self, id, client: BaseApi, messages: Message) -> None:
        self.id = id
        self.messages = messages
        self.client = client
        self._conversation_lock = Lock()
        self._messages_lock = RLock()

    def chat_once(self, question: str):
        return self.chat(question)

    def chat_preserving_history(self, message: str):
        return self.chat(message, preserve=True)

    def chat(
        self,
        question: str,
        *,
        preserve: bool = False,
        system_message: str | None = None,
    ) -> str:
        with self._conversation_lock:
            if system_message:
                self._adjust_system_message(system_message)
            with self._messages_lock:
                request_messages = self.messages.generate_messages_jar(question)
            response_content = self.client.reason(
                request_messages
            )
            if preserve:
                with self._messages_lock:
                    self.messages.preserve_history(question, response_content)
            return response_content

    def chat_stream_once(self, question: str) -> Iterator[str]:
        yield from self.chat_stream(question)

    def chat_stream_preserving_history(self, message: str) -> Iterator[str]:
        yield from self.chat_stream(message, preserve=True)

    def chat_stream(
        self,
        question: str,
        *,
        preserve: bool = False,
        system_message: str | None = None,
    ) -> Iterator[str]:
        with self._conversation_lock:
            if system_message:
                self._adjust_system_message(system_message)

            chunks: list[str] = []
            with self._messages_lock:
                request_messages = self.messages.generate_messages_jar(question)
            stream = self.client.reason_stream(request_messages)
            try:
                for chunk in stream:
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    yield chunk
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

            if preserve:
                with self._messages_lock:
                    self.messages.preserve_history(question, "".join(chunks))

    def clear_history(self):
        with self._messages_lock:
            self.messages._messages_user_and_assistant_part = []

    def adjust_system_message(self, system_message: str):
        with self._messages_lock:
            self._adjust_system_message(system_message)

    def _adjust_system_message(self, system_message: str):
        with self._messages_lock:
            self.messages._messages_system_part = [
                self.messages.construct_system_message(system_message)
            ]

    def snapshot_messages(self):
        with self._messages_lock:
            return list(self.messages.messages)


class SessionManager:
    def __init__(self, api_factory: Optional[ApiFactory] = None) -> None:
        self.pool: Dict[str, Session] = dict()
        self.api_factory = api_factory or ApiFactory()
        self._lock = RLock()

    def new_session(self, id=None, system_message=None, provider=None, model=None):
        """
        创建新会话
        
        Args:
            id: 会话 ID，如果不提供则自动生成
            system_message: 系统消息
            provider: AI 服务商名称，如果不提供则使用默认服务商
            model: 模型名称，仅与 provider 同时提供时使用
        
        Returns:
            Session 实例
        """
        with self._lock:
            if not id:
                id = str(uuid.uuid4())
            if model is None:
                client = self.api_factory.get_client(provider)
            else:
                client = self.api_factory.get_client(provider, model)
            session = Session(id, client, Message(system_message))
            self.pool[id] = session
            return session

    def get_or_create_session(self, id=None, provider=None, model=None):
        """
        获取或创建会话
        
        Args:
            id: 会话 ID
            provider: AI 服务商名称，仅在创建新会话时使用
            model: 模型名称，仅在创建新会话时使用
        
        Returns:
            Session 实例
        """
        with self._lock:
            if id not in self.pool:
                return self.new_session(id, provider=provider, model=model)
            return self.pool[id]

    def list_sessions(self):
        with self._lock:
            return list(self.pool.values())
