from dataclasses import dataclass
from collections.abc import Sequence
from typing import override

from api.base_api import BaseApi
from api.retrying_api import FailureHandler, FallbackEvent


@dataclass(frozen=True)
class FallbackEntry:
    """回退链中的一个模型或访问点。"""

    target: str
    client: BaseApi


class FallbackApi(BaseApi):
    """按顺序尝试同一服务商下的多个模型或访问点。"""

    def __init__(
        self,
        provider_name: str,
        entries: Sequence[FallbackEntry],
        failure_handlers: list[FailureHandler] | None = None,
    ) -> None:
        if not entries:
            raise ValueError("回退链不能为空")
        self.provider_name: str = provider_name
        self.entries: list[FallbackEntry] = list(entries)
        self.failure_handlers: list[FailureHandler] = failure_handlers or []

    @override
    def reason(self, messages: list[dict[str, str]]) -> str:
        exceptions: list[Exception] = []
        for entry in self.entries:
            try:
                return entry.client.reason(messages)
            except Exception as exception:
                exceptions.append(exception)

        event = FallbackEvent(
            provider_name=self.provider_name,
            will_retry=False,
            targets=[entry.target for entry in self.entries],
            exceptions=exceptions,
        )
        self._handle_failure(event)
        raise exceptions[-1]

    def _handle_failure(self, event: FallbackEvent) -> None:
        for handler in self.failure_handlers:
            try:
                handler(event)
            except Exception as exception:
                print(f"失败处理器执行失败: {type(exception).__name__}")
