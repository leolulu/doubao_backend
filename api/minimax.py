from typing import Dict, List

import requests

from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam


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
                description=f"模型名称（如 {'/'.join(cls.SUPPORTED_MODELS[:3])}...）"
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

    def reason(self, messages: List[Dict[str, str]]) -> str:
        """
        调用 MiniMax API 进行对话补全（OpenAI 兼容格式）

        Args:
            messages: 对话消息列表，格式为 [{"role": "user", "content": "..."}]

        Returns:
            模型返回的回复内容

        Raises:
            Exception: 当 API 调用失败时抛出异常
        """
        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": messages
        }

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            raise Exception(f"MiniMax API 调用失败: {response.status_code}, {response.text}")
