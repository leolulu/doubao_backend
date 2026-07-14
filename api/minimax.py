import re
from collections.abc import Iterator
from typing import Dict, List, Tuple

import requests

from api.base_api import BaseApi
from api.error_request_logger import log_llm_error_request, log_llm_success_request
from api.param_schema import ParamType, ProviderParam
from api.streaming import stream_chat_completion


class MiniMax(BaseApi):
    """MiniMax API 服务商实现（OpenAI 兼容格式）"""

    BASE_URL = "https://api.minimaxi.com/v1"

    # 支持的模型列表
    SUPPORTED_MODELS = [
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ]

    # think 标签正则表达式
    THINK_PATTERN = re.compile(r'<think>.*?</think>', re.DOTALL)

    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        """获取 MiniMax 需要的参数列表"""
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
                description=f"模型名称（如 {'/'.join(cls.SUPPORTED_MODELS[:3])}...，可用逗号按顺序配置多个回退模型）"
            )
        ]

    def __init__(self, api_key: str, model: str) -> None:
        """
        初始化 MiniMax 客户端

        Args:
            api_key: API 密钥
            model: 模型名称，如 "MiniMax-M2.5"
        """
        self.api_key = api_key
        self.model = model
        self.base_url = self.BASE_URL
        self._last_raw_content: str = ""  # 保存最后一次原始响应（用于历史记录）

    def _call_api(self, messages: List[Dict[str, str]], reasoning_split: bool = True) -> Dict:
        """
        调用 MiniMax API

        Args:
            messages: 对话消息列表
            reasoning_split: 是否分离思维内容

        Returns:
            API 响应结果
        """
        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": messages,
            "reasoning_split": reasoning_split
        }

        try:
            response = requests.post(url, headers=headers, json=data)
        except requests.exceptions.RequestException as exception:
            log_llm_error_request("minimax", url, data, exception=exception)
            raise

        if response.status_code == 200:
            try:
                result = response.json()
            except Exception as exception:
                log_llm_error_request("minimax", url, data, response=response, exception=exception)
                raise
            log_llm_success_request("minimax", url, data, response=response)
            return result
        else:
            log_llm_error_request("minimax", url, data, response=response)
            raise Exception(f"MiniMax API 调用失败: {response.status_code}, {response.text}")

    @staticmethod
    def _strip_think_tags(content: str) -> str:
        """移除 content 中的 think 标签"""
        return MiniMax.THINK_PATTERN.sub('', content).strip()

    def reason(self, messages: List[Dict[str, str]]) -> str:
        """
        调用 MiniMax API 进行对话补全（OpenAI 兼容格式）

        Args:
            messages: 对话消息列表，格式为 [{"role": "user", "content": "..."}]

        Returns:
            模型返回的回复内容（不含 think 标签）

        Raises:
            Exception: 当 API 调用失败时抛出异常
        """
        result = self._call_api(messages, reasoning_split=True)
        content = result['choices'][0]['message']['content']
        # 保存原始内容到属性，供 session_manager 获取用于历史记录
        self._last_raw_content = content
        return self._strip_think_tags(content)

    def reason_stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": self.model,
            "messages": messages,
            "reasoning_split": True,
        }
        yield from stream_chat_completion(
            provider="minimax",
            url=url,
            headers=headers,
            request_body=data,
            error_prefix="MiniMax API 调用失败",
            cumulative_content=True,
        )

    def reason_with_raw_response(self, messages: List[Dict[str, str]]) -> Tuple[str, str]:
        """
        调用 MiniMax API，返回原始内容和清理后的内容

        用于保存对话历史时保留完整的思维链内容。

        Args:
            messages: 对话消息列表

        Returns:
            (原始内容, 清理后的内容) 元组
            原始内容包含 think 标签，用于保持思维链连续性
            清理后的内容不包含 think 标签，用于返回给用户

        Raises:
            Exception: 当 API 调用失败时抛出异常
        """
        result = self._call_api(messages, reasoning_split=True)
        content = result['choices'][0]['message']['content']
        cleaned_content = self._strip_think_tags(content)
        return content, cleaned_content
