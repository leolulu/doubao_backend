import json
from collections.abc import Iterator
from typing import Any

import requests

from api.error_request_logger import log_llm_error_request, log_llm_success_request


class IncompleteStreamError(RuntimeError):
    """上游连接在协议完成标记前结束。"""


def iter_sse_data(response: requests.Response) -> Iterator[str]:
    """解析 SSE 响应，只返回每个事件合并后的 data 字段。"""
    response.encoding = "utf-8"
    data_lines: list[str] = []

    for line in response.iter_lines(chunk_size=1, decode_unicode=True):
        if line is None:
            continue
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue

        field, separator, value = line.partition(":")
        if field != "data":
            continue
        if separator and value.startswith(" "):
            value = value[1:]
        data_lines.append(value)

    if data_lines:
        yield "\n".join(data_lines)


def iter_openai_content(
    response: requests.Response,
    *,
    cumulative_content: bool = False,
) -> Iterator[str]:
    """将 OpenAI-compatible SSE 统一成真正的可见文本增量。"""
    accumulated_content = ""
    completed = False

    for data in iter_sse_data(response):
        if data == "[DONE]":
            return

        payload = json.loads(data)
        if payload.get("error") is not None:
            raise RuntimeError(f"上游流式响应错误: {payload['error']}")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            continue

        choice = choices[0]
        if not isinstance(choice, dict):
            continue
        if choice.get("finish_reason") is not None:
            completed = True

        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if not isinstance(content, str) or not content:
            continue

        if not cumulative_content:
            yield content
            continue

        if content.startswith(accumulated_content):
            new_content = content[len(accumulated_content):]
            accumulated_content = content
        else:
            new_content = content
            accumulated_content += content
        if new_content:
            yield new_content

    if not completed:
        raise IncompleteStreamError("上游流式响应在完成标记前结束")


def iter_anthropic_content(response: requests.Response) -> Iterator[str]:
    """将 Anthropic Messages SSE 统一成可见文本增量。"""
    for data in iter_sse_data(response):
        payload = json.loads(data)
        event_type = payload.get("type")
        if event_type == "message_stop":
            return
        if event_type == "error":
            raise RuntimeError(f"上游流式响应错误: {payload.get('error')}")

        if event_type == "content_block_start":
            content_block = payload.get("content_block")
            if isinstance(content_block, dict) and content_block.get("type") == "text":
                text = content_block.get("text")
                if isinstance(text, str) and text:
                    yield text
            continue

        if event_type != "content_block_delta":
            continue
        delta = payload.get("delta")
        if not isinstance(delta, dict) or delta.get("type") != "text_delta":
            continue
        text = delta.get("text")
        if isinstance(text, str) and text:
            yield text

    raise IncompleteStreamError("上游流式响应在 message_stop 前结束")


def stream_chat_completion(
    *,
    provider: str,
    url: str,
    headers: dict[str, str],
    request_body: dict[str, Any],
    error_prefix: str,
    protocol: str = "openai",
    cumulative_content: bool = False,
) -> Iterator[str]:
    """发送流式请求、统一解析、关闭连接并记录完整的可见回答。"""
    body = dict(request_body)
    body["stream"] = True
    response: requests.Response | None = None
    chunks: list[str] = []
    completed = False

    try:
        try:
            response = requests.post(url, headers=headers, json=body, stream=True)
        except requests.exceptions.RequestException as exception:
            log_llm_error_request(provider, url, body, exception=exception)
            raise

        if response.status_code != 200:
            log_llm_error_request(provider, url, body, response=response)
            raise Exception(f"{error_prefix}: {response.status_code}, {response.text}")

        if protocol == "anthropic":
            content_iterator = iter_anthropic_content(response)
        else:
            content_iterator = iter_openai_content(
                response,
                cumulative_content=cumulative_content,
            )

        try:
            for chunk in content_iterator:
                chunks.append(chunk)
                yield chunk
        except Exception as exception:
            log_llm_error_request(
                provider,
                url,
                body,
                response=response,
                response_body="".join(chunks),
                exception=exception,
            )
            raise

        completed = True
    finally:
        if response is not None:
            response.close()

    if completed:
        log_llm_success_request(
            provider,
            url,
            body,
            response=response,
            response_body="".join(chunks),
        )
