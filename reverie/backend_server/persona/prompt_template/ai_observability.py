"""
Shared audit logging and error classification for AI client calls.
"""
import datetime
import json
import os
import socket
import urllib.error
from pathlib import Path
from typing import Any, Optional

from utils import *


class AIClientError(RuntimeError):
  def __init__(self,
               message: str,
               *,
               category: str,
               provider: str,
               operation: str,
               status_code: Optional[int] = None,
               cause_type: Optional[str] = None,
               response_excerpt: Optional[str] = None):
    super().__init__(message)
    self.category = category
    self.provider = provider
    self.operation = operation
    self.status_code = status_code
    self.cause_type = cause_type
    self.response_excerpt = response_excerpt

  def to_dict(self) -> dict[str, Any]:
    return {
      "message": str(self),
      "category": self.category,
      "provider": self.provider,
      "operation": self.operation,
      "status_code": self.status_code,
      "cause_type": self.cause_type,
      "response_excerpt": self.response_excerpt,
    }


def _resolve_backend_server_root() -> Path:
  return Path(__file__).resolve().parents[2]


def _resolve_audit_dir() -> Path:
  configured = globals().get("ai_audit_dir", "../../environment/frontend_server/storage/_ai_audit")
  path = Path(configured)
  if not path.is_absolute():
    path = (_resolve_backend_server_root() / path).resolve()
  path.mkdir(parents=True, exist_ok=True)
  return path


def _audit_enabled() -> bool:
  return bool(globals().get("ai_audit_enabled", True))


def _preview_limit() -> int:
  return int(globals().get("ai_audit_preview_chars", 160))


def _truncate_text(value: Any, limit: Optional[int] = None) -> Optional[str]:
  if value is None:
    return None
  limit = _preview_limit() if limit is None else limit
  text = str(value).replace("\r", " ").replace("\n", " ").strip()
  if len(text) <= limit:
    return text
  return text[:limit] + "..."


def write_audit_event(kind: str, payload: dict[str, Any]) -> None:
  if not _audit_enabled():
    return

  log_path = _resolve_audit_dir() / f"{kind}.jsonl"
  event = {
    "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    **payload,
  }
  with open(log_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _extract_http_body(exc: urllib.error.HTTPError) -> Optional[str]:
  try:
    body = exc.read()
  except Exception:
    return None
  if not body:
    return None
  try:
    return body.decode("utf-8", errors="replace")
  except Exception:
    return repr(body[:200])


def _http_error_category(status_code: int) -> str:
  if status_code == 400:
    return "http_bad_request"
  if status_code == 401:
    return "http_unauthorized"
  if status_code == 403:
    return "http_forbidden"
  if status_code == 404:
    return "http_not_found"
  if status_code == 408:
    return "http_timeout"
  if status_code == 409:
    return "http_conflict"
  if status_code == 422:
    return "http_unprocessable_entity"
  if status_code == 429:
    return "http_rate_limited"
  if 500 <= status_code <= 599:
    return "http_server_error"
  return "http_error"


def classify_transport_error(exc: Exception,
                             *,
                             provider: str,
                             operation: str) -> AIClientError:
  if isinstance(exc, AIClientError):
    return exc

  if isinstance(exc, urllib.error.HTTPError):
    body = _extract_http_body(exc)
    category = _http_error_category(exc.code)
    message = (
      f"{operation} request failed with HTTP {exc.code} for provider "
      f"{provider}: {exc.reason}"
    )
    return AIClientError(
      message,
      category=category,
      provider=provider,
      operation=operation,
      status_code=exc.code,
      cause_type=type(exc).__name__,
      response_excerpt=_truncate_text(body, 300),
    )

  if isinstance(exc, urllib.error.URLError):
    reason = exc.reason
    if isinstance(reason, socket.timeout):
      category = "network_timeout"
    elif isinstance(reason, PermissionError):
      category = "network_permission_denied"
    elif isinstance(reason, ConnectionRefusedError):
      category = "network_connection_refused"
    else:
      category = "network_error"
    message = f"{operation} request failed for provider {provider}: {reason}"
    return AIClientError(
      message,
      category=category,
      provider=provider,
      operation=operation,
      cause_type=type(reason).__name__ if reason is not None else type(exc).__name__,
    )

  if isinstance(exc, socket.timeout) or isinstance(exc, TimeoutError):
    return AIClientError(
      f"{operation} request timed out for provider {provider}",
      category="network_timeout",
      provider=provider,
      operation=operation,
      cause_type=type(exc).__name__,
    )

  if isinstance(exc, PermissionError):
    return AIClientError(
      f"{operation} request was blocked for provider {provider}: {exc}",
      category="network_permission_denied",
      provider=provider,
      operation=operation,
      cause_type=type(exc).__name__,
    )

  return AIClientError(
    f"{operation} request failed for provider {provider}: {exc}",
    category="request_error",
    provider=provider,
    operation=operation,
    cause_type=type(exc).__name__,
  )


def wrap_parse_error(message: str,
                     *,
                     provider: str,
                     operation: str,
                     category: str,
                     response_excerpt: Optional[str] = None,
                     cause: Optional[Exception] = None) -> AIClientError:
  return AIClientError(
    message,
    category=category,
    provider=provider,
    operation=operation,
    cause_type=type(cause).__name__ if cause else None,
    response_excerpt=_truncate_text(response_excerpt, 300),
  )


def build_request_audit_payload(*,
                                provider: str,
                                operation: str,
                                model: Optional[str],
                                url: str,
                                success: bool,
                                duration_ms: int,
                                request_meta: dict[str, Any],
                                response_meta: Optional[dict[str, Any]] = None,
                                error: Optional[AIClientError] = None) -> dict[str, Any]:
  payload = {
    "provider": provider,
    "operation": operation,
    "model": model,
    "url": url,
    "success": success,
    "duration_ms": duration_ms,
    "request": request_meta,
  }
  if response_meta is not None:
    payload["response"] = response_meta
  if error is not None:
    payload["error"] = error.to_dict()
  return payload


def preview_text(value: Any, limit: Optional[int] = None) -> Optional[str]:
  return _truncate_text(value, limit)
