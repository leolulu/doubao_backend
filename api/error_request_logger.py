import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


LOG_PATH = Path(os.environ.get("LLM_ERROR_REQUEST_LOG", "logs/llm_error_requests.jsonl"))


def log_llm_error_request(
    provider: str,
    url: str,
    request_body: Any,
    response: requests.Response | None = None,
    exception: Exception | None = None,
) -> None:
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "provider": provider,
        "url": url,
        "request_body": request_body,
        "response_status_code": _response_status_code(response, exception),
        "response_body": _response_body(response, exception),
        "exception_type": type(exception).__name__ if exception is not None else None,
        "exception_message": str(exception) if exception is not None else None,
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str))
            file.write("\n")
    except Exception as log_exception:
        print(f"错误请求日志写入失败: {type(log_exception).__name__}")


def _response_status_code(
    response: requests.Response | None,
    exception: Exception | None,
) -> int | None:
    if response is not None:
        return response.status_code

    exception_response = getattr(exception, "response", None)
    status_code = getattr(exception_response, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    status_code = getattr(exception, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _response_body(
    response: requests.Response | None,
    exception: Exception | None,
) -> str | None:
    if response is not None:
        return response.text

    exception_response = getattr(exception, "response", None)
    text = getattr(exception_response, "text", None)
    if isinstance(text, str):
        return text

    body = getattr(exception, "body", None)
    if isinstance(body, str):
        return body
    if body is not None:
        return str(body)
    return None
