from collections.abc import Iterator
from typing import Dict, List

from volcenginesdkarkruntime import Ark

from api.base_api import BaseApi
from api.error_request_logger import log_llm_error_request, log_llm_success_request
from api.param_schema import ParamType, ProviderParam
from api.streaming import IncompleteStreamError


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
                description="访问点（模型标识，可用逗号按顺序配置多个回退访问点）"
            )
        ]
    
    def __init__(self, api_key: str, access_point: str) -> None:
        self.access_point = access_point
        self.client = Ark(api_key=api_key)

    def reason(self, messages: List[Dict[str, str]]) -> str:
        request_body = {
            "model": self.access_point,
            "messages": messages,
        }
        try:
            completion = self.client.chat.completions.create(**request_body)
            response_content = completion.choices[0].message.content
        except Exception as exception:
            log_llm_error_request("doubao", "ark://chat/completions", request_body, exception=exception)
            raise
        log_llm_success_request(
            "doubao",
            "ark://chat/completions",
            request_body,
            response_body=response_content,
        )
        return response_content

    def reason_stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        request_body = {
            "model": self.access_point,
            "messages": messages,
            "stream": True,
        }
        completion = None
        chunks: list[str] = []
        completed = False

        try:
            completion = self.client.chat.completions.create(**request_body)
            for chunk in completion:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                choice = choices[0]
                if getattr(choice, "finish_reason", None) is not None:
                    completed = True
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    chunks.append(content)
                    yield content
            if not completed:
                raise IncompleteStreamError("上游流式响应在完成标记前结束")
        except Exception as exception:
            log_llm_error_request(
                "doubao",
                "ark://chat/completions",
                request_body,
                response_body="".join(chunks),
                exception=exception,
            )
            raise
        finally:
            close = getattr(completion, "close", None)
            if callable(close):
                close()

        if completed:
            log_llm_success_request(
                "doubao",
                "ark://chat/completions",
                request_body,
                response_body="".join(chunks),
            )
