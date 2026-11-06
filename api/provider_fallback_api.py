from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import override

from api.base_api import BaseApi
from api.retrying_api import (
    FailureHandler,
    FallbackEvent,
    ProviderFallbackEvent,
    ProviderFallbackOutcome,
)


@dataclass(frozen=True)
class ProviderFallbackEntry:
    provider_name: str
    client: BaseApi


class ProviderFallbackApi(BaseApi):
    """Try configured providers in priority order."""

    def __init__(
        self,
        entries: Sequence[ProviderFallbackEntry],
        failure_handlers: list[FailureHandler] | None = None,
    ) -> None:
        if not entries:
            raise ValueError("provider fallback chain cannot be empty")
        self.provider_name: str = "provider-chain"
        self.entries: list[ProviderFallbackEntry] = list(entries)
        self.failure_handlers: list[FailureHandler] = failure_handlers or []

    @override
    def reason(self, messages: list[dict[str, str]]) -> str:
        providers: list[str] = []
        exceptions: list[Exception] = []
        for entry in self.entries:
            providers.append(entry.provider_name)
            try:
                result = entry.client.reason(messages)
            except Exception as exception:
                exceptions.append(exception)
            else:
                if exceptions:
                    self._report_result(providers, exceptions, outcome="success")
                return result

        self._report_result(providers, exceptions, outcome="failed")
        raise exceptions[-1]

    @override
    def reason_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        providers: list[str] = []
        exceptions: list[Exception] = []
        outcome: ProviderFallbackOutcome = "failed"

        try:
            for entry in self.entries:
                providers.append(entry.provider_name)
                yielded_content = False
                stream = None
                try:
                    stream = entry.client.reason_stream(messages)
                    for chunk in stream:
                        if not chunk:
                            continue
                        yielded_content = True
                        yield chunk
                except Exception as exception:
                    exceptions.append(exception)
                    if yielded_content:
                        outcome = "interrupted"
                        break
                    continue
                finally:
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                outcome = "success"
                return
            raise exceptions[-1]
        except GeneratorExit:
            outcome = "cancelled"
            raise
        finally:
            if exceptions:
                self._report_result(providers, exceptions, outcome=outcome)

    def _report_result(
        self,
        providers: list[str],
        exceptions: list[Exception],
        *,
        outcome: ProviderFallbackOutcome,
    ) -> None:
        event = ProviderFallbackEvent(
            provider_name=self.provider_name,
            will_retry=False,
            providers=providers,
            exceptions=exceptions,
            secret_values=self._collect_secret_values(exceptions),
            outcome=outcome,
        )
        for handler in self.failure_handlers:
            try:
                handler(event)
            except Exception as exception:
                print(f"failure handler failed: {type(exception).__name__}")

    def _collect_secret_values(self, exceptions: list[Exception]) -> tuple[str, ...]:
        secrets: list[str] = []
        for exception in exceptions:
            fallback_event = getattr(exception, "fallback_event", None)
            if isinstance(fallback_event, FallbackEvent):
                secrets.extend(fallback_event.secret_values)
        return tuple(secrets)
