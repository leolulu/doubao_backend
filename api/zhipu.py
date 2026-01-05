from typing import Dict, List

import requests

from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam


class Zhipu(BaseApi):
    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        """获取智谱 AI 需要的参数列表"""
        return [
            ProviderParam(
                name="api_key",
                param_type=ParamType.STRING,
                required=True,
                description="API 密钥"
            ),
            ProviderParam(
                name="access_point",
                param_type=ParamType.STRING,
                required=True,
                description="模型名称（如 glm-4.7）"
            ),
            ProviderParam(
                name="use_coding_endpoint",
                param_type=ParamType.BOOLEAN,
                required=False,
                default=False,
                description="是否使用 Coding 专用端点"
            )
        ]
    
    def __init__(self, api_key: str, access_point: str, use_coding_endpoint: bool = False) -> None:
        """
        初始化智谱AI客户端
        
        Args:
            api_key: API密钥
            access_point: 模型名称，如 "glm-4.7"
            use_coding_endpoint: 是否使用Coding专用端点，默认为False
                                如果为True，使用 https://open.bigmodel.cn/api/coding/paas/v4
                                如果为False，使用 https://open.bigmodel.cn/api/paas/v4/
        """
        self.api_key = api_key
        self.access_point = access_point
        self.use_coding_endpoint = use_coding_endpoint
        
        # 根据配置选择不同的端点
        if use_coding_endpoint:
            self.base_url = "https://open.bigmodel.cn/api/coding/paas/v4"
        else:
            self.base_url = "https://open.bigmodel.cn/api/paas/v4/"

    def reason(self, messages: List[Dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.access_point,
            "messages": messages,
            "temperature": 1.0
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            raise Exception(f"API调用失败: {response.status_code}, {response.text}")
