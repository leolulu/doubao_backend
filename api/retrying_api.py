import re
import time
from dataclasses import dataclass
from typing import Callable, override

import requests

from api.base_api import BaseApi


@dataclass(frozen=True)
class RetryEvent:
    """统一失败事件，后续可用于接入通知、日志或监控。"""

    provider_name: str
    attempt_number: int
    max_retries: int
    delay_seconds: float
    exception: Exception
    will_retry: bool


FailureHandler = Callable[[RetryEvent], None]
Sleeper = Callable[[float], None]


class RetryingApi(BaseApi):
    """为所有服务商统一提供重试能力的透明代理。"""

    DEFAULT_MAX_RETRIES: int = 5
    DEFAULT_RETRY_DELAY_SECONDS: float = 5.0
    RETRYABLE_STATUS_CODES: set[int] = {408, 409, 425, 429, 500, 502, 503, 504}
    STATUS_CODE_PATTERN: re.Pattern[str] = re.compile(r"(?<!\d)(\d{3})(?!\d)")

    def __init__(
        self,
        provider_name: str,
        client: BaseApi,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        failure_handlers: list[FailureHandler] | None = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self.provider_name: str = provider_name
        self.client: BaseApi = client
        self.max_retries: int = max_retries
        self.retry_delay_seconds: float = retry_delay_seconds
        self.failure_handlers: list[FailureHandler] = failure_handlers or []
        self.sleeper: Sleeper = sleeper

    @override
    def reason(self, messages: list[dict[str, str]]) -> str:
        for retry_count in range(self.max_retries + 1):
            try:
                return self.client.reason(messages)
            except Exception as exception:
                will_retry = retry_count < self.max_retries and self._should_retry(exception)
                self._handle_failure(
                    RetryEvent(
                        provider_name=self.provider_name,
                        attempt_number=retry_count + 1,
                        max_retries=self.max_retries,
                        delay_seconds=self.retry_delay_seconds if will_retry else 0,
                        exception=exception,
                        will_retry=will_retry,
                    )
                )
                if not will_retry:
                    raise
                self.sleeper(self.retry_delay_seconds)

        raise RuntimeError("重试流程异常结束")

    def _should_retry(self, exception: Exception) -> bool:
        if isinstance(exception, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True

        if isinstance(exception, requests.exceptions.RequestException):
            response = exception.response
            if response is not None:
                return response.status_code in self.RETRYABLE_STATUS_CODES
            return False

        status_code = self._extract_status_code(exception)
        return status_code in self.RETRYABLE_STATUS_CODES

    def _extract_status_code(self, exception: Exception) -> int | None:
        for match in self.STATUS_CODE_PATTERN.finditer(str(exception)):
            status_code = int(match.group(1))
            if 400 <= status_code <= 599:
                return status_code
        return None

    def _handle_failure(self, event: RetryEvent) -> None:
        for handler in self.failure_handlers:
            handler(event)
