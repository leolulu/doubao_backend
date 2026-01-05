from typing import Dict, List

import requests

from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam


class DeepSeek(BaseApi):
    """DeepSeek API 服务商实现"""
    
    BASE_URL = "https://api.deepseek.com"
    
    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        """获取 DeepSeek 需要的参数列表"""
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
                description="模型名称（如 deepseek-chat 或 deepseek-reasoner）"
            )
        ]
    
    def __init__(self, api_key: str, model: str) -> None:
        """
        初始化 DeepSeek 客户端
        
        Args:
            api_key: API 密钥
            model: 模型名称，如 "deepseek-chat" 或 "deepseek-reasoner"
        """
        self.api_key = api_key
        self.model = model
        self.base_url = self.BASE_URL

    def reason(self, messages: List[Dict[str, str]]) -> str:
        """
        调用 DeepSeek API 进行对话补全
        
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
            raise Exception(f"DeepSeek API 调用失败: {response.status_code}, {response.text}")
