from typing import Dict, List

import requests

from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam


class ModelScope(BaseApi):
    """ModelScope API 服务商实现（OpenAI 兼容格式）"""

    BASE_URL = "https://api-inference.modelscope.cn/v1"

    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        """获取 ModelScope 需要的参数列表"""
        return [
            ProviderParam(
                name="api_key",
                param_type=ParamType.STRING,
                required=True,
                description="ModelScope Token"
            ),
            ProviderParam(
                name="model",
                param_type=ParamType.STRING,
                required=True,
                description="ModelScope Model-Id（如 deepseek-ai/DeepSeek-V4-Pro，可用逗号按顺序配置多个回退模型）"
            )
        ]

    def __init__(self, api_key: str, model: str) -> None:
        """
        初始化 ModelScope 客户端

        Args:
            api_key: ModelScope Token
            model: ModelScope Model-Id，如 "deepseek-ai/DeepSeek-V4-Pro"
        """
        self.api_key = api_key
        self.model = model
        self.base_url = self.BASE_URL

    def reason(self, messages: List[Dict[str, str]]) -> str:
        """
        调用 ModelScope API 进行对话补全（OpenAI 兼容格式）

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
            raise Exception(f"ModelScope API 调用失败: {response.status_code}, {response.text}")
