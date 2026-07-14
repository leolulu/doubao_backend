from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import override

from api.base_api import BaseApi
from api.retrying_api import FailureHandler, FallbackEvent


@dataclass(frozen=True)
class FallbackEntry:
    """One target in a fallback chain."""

    target: str
    client: BaseApi
    secrets: tuple[str, ...] = ()


class FallbackApi(BaseApi):
    """Try multiple clients in order and report only after the whole chain fails."""

    def __init__(
        self,
        provider_name: str,
        entries: Sequence[FallbackEntry],
        failure_handlers: list[FailureHandler] | None = None,
    ) -> None:
        if not entries:
            raise ValueError("fallback chain cannot be empty")
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
            secret_values=tuple(secret for entry in self.entries for secret in entry.secrets),
        )
        self._handle_failure(event)
        self._attach_fallback_event(exceptions[-1], event)
        raise exceptions[-1]

    @override
    def reason_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        exceptions: list[Exception] = []
        attempted_entries: list[FallbackEntry] = []

        for entry in self.entries:
            attempted_entries.append(entry)
            yielded_content = False
            stream = None
            try:
                stream = entry.client.reason_stream(messages)
                for chunk in stream:
                    if not chunk:
                        continue
                    yielded_content = True
                    yield chunk
                return
            except Exception as exception:
                exceptions.append(exception)
                if yielded_content:
                    break
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

        event = FallbackEvent(
            provider_name=self.provider_name,
            will_retry=False,
            targets=[entry.target for entry in attempted_entries],
            exceptions=exceptions,
            secret_values=tuple(
                secret
                for entry in attempted_entries
                for secret in entry.secrets
            ),
        )
        self._handle_failure(event)
        self._attach_fallback_event(exceptions[-1], event)
        raise exceptions[-1]

    def _handle_failure(self, event: FallbackEvent) -> None:
        for handler in self.failure_handlers:
            try:
                handler(event)
            except Exception as exception:
                print(f"failure handler failed: {type(exception).__name__}")

    def _attach_fallback_event(self, exception: Exception, event: FallbackEvent) -> None:
        try:
            setattr(exception, "fallback_event", event)
        except Exception:
            pass
