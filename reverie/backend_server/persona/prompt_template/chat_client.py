"""
Provider-aware chat client for generative agents.
"""
import json
import time
import urllib.request
from typing import Any, Optional

from persona.prompt_template.ai_observability import (
  AIClientError,
  build_request_audit_payload,
  classify_transport_error,
  preview_text,
  wrap_parse_error,
  write_audit_event,
)


class ChatClient:
  def __init__(self, config: dict[str, Any]):
    self.provider = (config.get("provider") or "openai").lower()
    self.api_key = config.get("api_key") or ""
    self.base_url = config.get("base_url") or "https://api.openai.com/v1"
    self.default_model = config.get("model") or "gpt-3.5-turbo"
    self.advanced_model = config.get("advanced_model") or self.default_model
    self.timeout_sec = int(config.get("timeout_sec") or 60)
    self.debug = bool(config.get("debug"))

  def complete(self,
               prompt: str,
               *,
               model: Optional[str] = None,
               temperature: Optional[float] = None,
               max_tokens: Optional[int] = None,
               stop: Optional[list[str]] = None) -> str:
    request_model = model or self.default_model
    url = self._resolve_chat_url()
    started_at = time.time()
    request_meta = {
      "prompt_chars": len(prompt),
      "prompt_preview": preview_text(prompt),
      "temperature": temperature,
      "max_tokens": max_tokens,
      "stop_count": len(stop) if stop else 0,
    }

    if not self.api_key:
      error = AIClientError(
        "chat api key is not configured",
        category="missing_api_key",
        provider=self.provider,
        operation="chat_completion",
      )
      self._write_audit(
        request_model,
        url,
        started_at,
        request_meta,
        error=error,
      )
      raise error

    payload = {
      "model": request_model,
      "messages": [{"role": "user", "content": prompt}],
    }
    if temperature is not None:
      payload["temperature"] = temperature
    if max_tokens is not None:
      payload["max_tokens"] = max_tokens
    if stop:
      payload["stop"] = stop

    if self.debug:
      print(f"[ChatClient] provider={self.provider} model={request_model} url={url}")

    try:
      data = self._post_json(url, payload)
    except AIClientError as error:
      self._write_audit(
        request_model,
        url,
        started_at,
        request_meta,
        error=error,
      )
      raise

    try:
      message = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
      error = wrap_parse_error(
        "unexpected chat response shape",
        provider=self.provider,
        operation="chat_completion",
        category="unexpected_response_shape",
        response_excerpt=json.dumps(data)[:500],
        cause=exc,
      )
      self._write_audit(
        request_model,
        url,
        started_at,
        request_meta,
        error=error,
      )
      raise error from exc

    if isinstance(message, str):
      result = message
    elif isinstance(message, list):
      chunks = []
      for item in message:
        if isinstance(item, dict) and item.get("type") == "text":
          chunks.append(item.get("text", ""))
      result = "".join(chunks)
    else:
      result = str(message)

    self._write_audit(
      request_model,
      url,
      started_at,
      request_meta,
      response_meta={
        "response_chars": len(result),
        "response_preview": preview_text(result),
      },
    )
    return result

  def _build_headers(self) -> dict[str, str]:
    return {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {self.api_key}",
    }

  def _resolve_chat_url(self) -> str:
    normalized = self.base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
      return normalized
    return normalized + "/chat/completions"

  def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
      url,
      data=json.dumps(payload).encode("utf-8"),
      headers=self._build_headers(),
      method="POST",
    )
    try:
      with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
        raw_text = response.read().decode("utf-8")
        try:
          return json.loads(raw_text)
        except json.JSONDecodeError as exc:
          raise wrap_parse_error(
            "chat response was not valid JSON",
            provider=self.provider,
            operation="chat_completion",
            category="invalid_json_response",
            response_excerpt=raw_text,
            cause=exc,
          ) from exc
    except Exception as exc:
      raise classify_transport_error(
        exc,
        provider=self.provider,
        operation="chat_completion",
      ) from exc

  def _write_audit(self,
                   model: str,
                   url: str,
                   started_at: float,
                   request_meta: dict[str, Any],
                   *,
                   response_meta: Optional[dict[str, Any]] = None,
                   error: Optional[AIClientError] = None) -> None:
    duration_ms = int((time.time() - started_at) * 1000)
    write_audit_event(
      "chat_requests",
      build_request_audit_payload(
        provider=self.provider,
        operation="chat_completion",
        model=model,
        url=url,
        success=error is None,
        duration_ms=duration_ms,
        request_meta=request_meta,
        response_meta=response_meta,
        error=error,
      ),
    )
