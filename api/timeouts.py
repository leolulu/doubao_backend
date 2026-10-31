"""上游请求的时间边界。

- 单次请求：连接 5 秒，等待响应 90 秒。
- 单个模型（一个 API Key + 一个模型的组合）：由 RetryingApi 施加 120 秒总时限，
  每次尝试的等待响应时间会按剩余预算收紧。
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

CONNECT_TIMEOUT_SECONDS: float = 5.0
RESPONSE_TIMEOUT_SECONDS: float = 90.0
MIN_TIMEOUT_SECONDS: float = 1.0

_attempt_deadline: ContextVar[float | None] = ContextVar("attempt_deadline", default=None)


def request_timeout() -> tuple[float, float]:
    """当前这次上游请求可用的 (连接超时, 等待响应超时)。"""
    return _timeout_for(_attempt_deadline.get())


def set_attempt_deadline(deadline: float | None) -> Token[float | None]:
    """设置当前尝试的绝对截止时间（单调时钟），返回供 reset 使用的 token。"""
    return _attempt_deadline.set(deadline)


def reset_attempt_deadline(token: Token[float | None]) -> None:
    _attempt_deadline.reset(token)


@contextmanager
def attempt_deadline(deadline: float | None) -> Iterator[None]:
    token = set_attempt_deadline(deadline)
    try:
        yield
    finally:
        reset_attempt_deadline(token)


def _timeout_for(deadline: float | None) -> tuple[float, float]:
    if deadline is None:
        return CONNECT_TIMEOUT_SECONDS, RESPONSE_TIMEOUT_SECONDS

    remaining = max(deadline - time.monotonic(), MIN_TIMEOUT_SECONDS)
    return (
        min(CONNECT_TIMEOUT_SECONDS, remaining),
        min(RESPONSE_TIMEOUT_SECONDS, remaining),
    )
