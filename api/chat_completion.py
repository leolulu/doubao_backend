from collections.abc import Iterator
from typing import Any, Dict, List

import requests

from api.base_api import BaseApi
from api.error_request_logger import log_llm_error_request, log_llm_success_request
from api.param_schema import ParamType, ProviderParam
from api.streaming import stream_chat_completion


class ChatCompletion(BaseApi):
    """Generic OpenAI-compatible chat completions provider."""

    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        return [
            ProviderParam(
                name="base_url",
                param_type=ParamType.STRING,
                required=True,
                description="OpenAI-compatible base URL, for example https://example.com/v1"
            ),
            ProviderParam(
                name="api_key",
                param_type=ParamType.STRING,
                required=True,
                description="API key"
            ),
            ProviderParam(
                name="model",
                param_type=ParamType.STRING,
                required=False,
                description="Model name, or 'auto' / 'auto:<pattern>' to discover models via /v1/models"
            ),
        ]

    @classmethod
    def validate_config(cls, config: Dict[str, Any]) -> tuple[bool, List[str]]:
        allowed_internal_config = {"provider_name"}
        public_config = {
            key: value
            for key, value in config.items()
            if key not in allowed_internal_config
        }
        is_valid, errors = super().validate_config(public_config)
        if not is_valid:
            # model is now optional; filter out the "缺少必填参数: model" error
            # since it's expected when using auto-discovery
            errors = [
                e for e in errors
                if e != "缺少必填参数: model"
            ]
            if not errors:
                is_valid = True
        return is_valid, errors

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        provider_name: str = "chat_completion",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider_name = provider_name

    def reason(self, messages: List[Dict[str, str]]) -> str:
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": self.model,
            "messages": messages,
        }

        try:
            response = requests.post(url, headers=headers, json=data)
        except requests.exceptions.RequestException as exception:
            log_llm_error_request(self.provider_name, url, data, exception=exception)
            raise

        if response.status_code == 200:
            try:
                result = response.json()
                response_content = result["choices"][0]["message"]["content"]
            except Exception as exception:
                log_llm_error_request(self.provider_name, url, data, response=response, exception=exception)
                raise
            log_llm_success_request(self.provider_name, url, data, response=response)
            return response_content

        log_llm_error_request(self.provider_name, url, data, response=response)
        raise Exception(
            f"Chat Completion API call failed: {response.status_code}, {response.text}"
        )

    def reason_stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": self.model,
            "messages": messages,
        }
        yield from stream_chat_completion(
            provider=self.provider_name,
            url=url,
            headers=headers,
            request_body=data,
            error_prefix="Chat Completion API call failed",
        )

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _models_url(self) -> str:
        if self.base_url.endswith("/models"):
            return self.base_url
        return f"{self.base_url}/models"

    def discover_models(self) -> List[str]:
        """Fetch available model IDs from the upstream /v1/models endpoint."""
        url = self._models_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            raise Exception(
                f"Model discovery failed: {response.status_code}, {response.text}"
            )
        result = response.json()
        data = result.get("data")
        if not isinstance(data, list):
            raise Exception("Model discovery failed: response missing 'data' array")
        models: List[str] = []
        for item in data:
            if isinstance(item, dict) and "id" in item:
                models.append(str(item["id"]))
        if not models:
            raise Exception("Model discovery failed: no models found in response")
        return models
