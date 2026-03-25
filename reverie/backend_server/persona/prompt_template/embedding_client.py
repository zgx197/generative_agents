"""
Provider-aware embedding client for generative agents.
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


class EmbeddingClient:
  def __init__(self, config: dict[str, Any]):
    self.provider = (config.get("provider") or "openai").lower()
    self.api_key = config.get("api_key") or ""
    self.base_url = config.get("base_url") or "https://api.openai.com/v1"
    self.default_model = config.get("model") or "text-embedding-ada-002"
    self.timeout_sec = int(config.get("timeout_sec") or 60)
    self.debug = bool(config.get("debug"))

  def embed_text(self, text: str, *, model: Optional[str] = None) -> list[float]:
    vectors = self.embed_texts([text], model=model)
    if not vectors:
      raise AIClientError(
        "embedding response did not include any vectors",
        category="empty_embedding_response",
        provider=self.provider,
        operation="embedding",
      )
    return vectors[0]

  def embed_texts(self,
                  texts: list[str],
                  *,
                  model: Optional[str] = None) -> list[list[float]]:
    request_model = model or self.default_model
    url = self._resolve_embedding_url()
    started_at = time.time()
    request_meta = {
      "text_count": len(texts),
      "total_chars": sum(len(text) for text in texts),
      "sample_preview": preview_text(texts[0]) if texts else None,
    }

    if not self.api_key:
      error = AIClientError(
        "embedding api key is not configured",
        category="missing_api_key",
        provider=self.provider,
        operation="embedding",
      )
      self._write_audit(
        request_model,
        url,
        started_at,
        request_meta,
        error=error,
      )
      raise error
    if not texts:
      return []

    payload = self._build_payload(request_model, texts)

    if self.debug:
      print(f"[EmbeddingClient] provider={self.provider} model={request_model} url={url} count={len(texts)}")

    try:
      data = self._post_json(url, payload)
      vectors = self._parse_vectors(data)
    except AIClientError as error:
      self._write_audit(
        request_model,
        url,
        started_at,
        request_meta,
        error=error,
      )
      raise

    response_meta = {
      "vector_count": len(vectors),
      "vector_dimensions": sorted({
        len(vector) for vector in vectors if isinstance(vector, list)
      }),
    }
    self._write_audit(
      request_model,
      url,
      started_at,
      request_meta,
      response_meta=response_meta,
    )
    return vectors

  def _build_headers(self) -> dict[str, str]:
    return {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {self.api_key}",
    }

  def _resolve_embedding_url(self) -> str:
    normalized = self.base_url.rstrip("/")
    if self.provider in ("dashscope", "qwen", "aliyun"):
      return normalized
    if normalized.endswith("/embeddings"):
      return normalized
    return normalized + "/embeddings"

  def _build_payload(self, model: str, texts: list[str]) -> dict[str, Any]:
    if self.provider in ("dashscope", "qwen", "aliyun"):
      return {
        "model": model,
        "input": {
          "texts": texts,
        }
      }
    return {
      "model": model,
      "input": texts,
    }

  def _parse_vectors(self, data: dict[str, Any]) -> list[list[float]]:
    if self.provider in ("dashscope", "qwen", "aliyun"):
      return self._parse_dashscope_vectors(data)
    return self._parse_openai_compatible_vectors(data)

  def _parse_openai_compatible_vectors(self, data: dict[str, Any]) -> list[list[float]]:
    try:
      return [item["embedding"] for item in data["data"]]
    except (KeyError, TypeError) as exc:
      raise wrap_parse_error(
        "unexpected embedding response shape",
        provider=self.provider,
        operation="embedding",
        category="unexpected_response_shape",
        response_excerpt=json.dumps(data)[:500],
        cause=exc,
      ) from exc

  def _parse_dashscope_vectors(self, data: dict[str, Any]) -> list[list[float]]:
    try:
      return [item["embedding"] for item in data["output"]["embeddings"]]
    except (KeyError, TypeError) as exc:
      raise wrap_parse_error(
        "unexpected dashscope embedding response shape",
        provider=self.provider,
        operation="embedding",
        category="unexpected_response_shape",
        response_excerpt=json.dumps(data)[:500],
        cause=exc,
      ) from exc

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
            "embedding response was not valid JSON",
            provider=self.provider,
            operation="embedding",
            category="invalid_json_response",
            response_excerpt=raw_text,
            cause=exc,
          ) from exc
    except Exception as exc:
      raise classify_transport_error(
        exc,
        provider=self.provider,
        operation="embedding",
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
      "embedding_requests",
      build_request_audit_payload(
        provider=self.provider,
        operation="embedding",
        model=model,
        url=url,
        success=error is None,
        duration_ms=duration_ms,
        request_meta=request_meta,
        response_meta=response_meta,
        error=error,
      ),
    )
