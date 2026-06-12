import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


LOG_PATH = Path(os.environ.get("LLM_ERROR_REQUEST_LOG", "logs/llm_error_requests.jsonl"))
SUCCESS_LOG_PATH = Path(os.environ.get("LLM_SUCCESS_REQUEST_LOG", "logs/llm_success_requests.jsonl"))
SUCCESS_LOG_MAX_RECORDS = 300


def log_llm_error_request(
    provider: str,
    url: str,
    request_body: Any,
    response: requests.Response | None = None,
    exception: Exception | None = None,
) -> None:
    record = _build_record(provider, url, request_body, response=response, exception=exception)

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str))
            file.write("\n")
    except Exception as log_exception:
        print(f"错误请求日志写入失败: {type(log_exception).__name__}")


def log_llm_success_request(
    provider: str,
    url: str,
    request_body: Any,
    response: requests.Response | None = None,
    response_body: Any = None,
) -> None:
    record = _build_record(provider, url, request_body, response=response, response_body=response_body)

    try:
        SUCCESS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        records = _read_recent_success_records()
        records.append(record)
        records = records[-SUCCESS_LOG_MAX_RECORDS:]
        with SUCCESS_LOG_PATH.open("w", encoding="utf-8") as file:
            for item in records:
                file.write(json.dumps(item, ensure_ascii=False, default=str))
                file.write("\n")
    except Exception as log_exception:
        print(f"成功请求日志写入失败: {type(log_exception).__name__}")


def _build_record(
    provider: str,
    url: str,
    request_body: Any,
    response: requests.Response | None = None,
    response_body: Any = None,
    exception: Exception | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "provider": provider,
        "url": url,
        "request_body": request_body,
        "response_status_code": _response_status_code(response, exception),
        "response_body": _response_body(response, exception, response_body),
        "exception_type": type(exception).__name__ if exception is not None else None,
        "exception_message": str(exception) if exception is not None else None,
    }


def _read_recent_success_records() -> list[dict[str, Any]]:
    if not SUCCESS_LOG_PATH.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in SUCCESS_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if isinstance(record, dict):
            records.append(record)
    return records[-(SUCCESS_LOG_MAX_RECORDS - 1):]


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
    response_body: Any = None,
) -> Any:
    if response_body is not None:
        return response_body

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
