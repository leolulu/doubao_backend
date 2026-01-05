from typing import Dict, List

from volcenginesdkarkruntime import Ark

from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam


class Doubao(BaseApi):
    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        """获取豆包 AI 需要的参数列表"""
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
                description="访问点（模型标识）"
            )
        ]
    
    def __init__(self, api_key: str, access_point: str) -> None:
        self.access_point = access_point
        self.client = Ark(api_key=api_key)

    def reason(self, messages: List[Dict[str, str]]) -> str:
        completion = self.client.chat.completions.create(
            model=self.access_point,
            messages=messages,
        )
        response_content = completion.choices[0].message.content
        return response_content
