"""
Lightweight connectivity check for chat and embedding providers.

Example:
  python ai_self_check.py --chat-provider qwen --chat-model qwen-plus \
    --embedding-provider qwen --embedding-model text-embedding-v4

Keys are read from command line or environment variables:
  CHAT_API_KEY
  EMBEDDING_API_KEY
"""
import argparse
import json
import os
import sys

from persona.prompt_template.ai_observability import AIClientError
from persona.prompt_template.chat_client import ChatClient
from persona.prompt_template.embedding_client import EmbeddingClient


def _default_chat_base_url(provider):
  provider = (provider or "openai").lower()
  if provider in ("dashscope", "qwen", "aliyun"):
    return "https://dashscope.aliyuncs.com/compatible-mode/v1"
  if provider in ("moonshot", "kimi"):
    return "https://api.moonshot.cn/v1"
  return "https://api.openai.com/v1"


def _default_embedding_base_url(provider):
  provider = (provider or "openai").lower()
  if provider in ("dashscope", "qwen", "aliyun"):
    return ("https://dashscope.aliyuncs.com/api/v1/services/"
            "embeddings/text-embedding/text-embedding")
  return "https://api.openai.com/v1"


def _build_parser():
  parser = argparse.ArgumentParser(description="AI provider self-check")
  parser.add_argument("--chat-provider", default="qwen")
  parser.add_argument("--chat-base-url", default=None)
  parser.add_argument("--chat-model", default="qwen-plus")
  parser.add_argument("--chat-api-key", default=None)

  parser.add_argument("--embedding-provider", default="qwen")
  parser.add_argument("--embedding-base-url", default=None)
  parser.add_argument("--embedding-model", default="text-embedding-v4")
  parser.add_argument("--embedding-api-key", default=None)

  parser.add_argument("--timeout-sec", type=int, default=60)
  parser.add_argument("--debug", action="store_true")
  return parser


def _resolve_key(cli_value, env_name):
  return cli_value or os.environ.get(env_name, "")


def _check_chat(args):
  config = {
    "provider": args.chat_provider,
    "api_key": _resolve_key(args.chat_api_key, "CHAT_API_KEY"),
    "base_url": args.chat_base_url or _default_chat_base_url(args.chat_provider),
    "model": args.chat_model,
    "advanced_model": args.chat_model,
    "timeout_sec": args.timeout_sec,
    "debug": args.debug,
  }
  client = ChatClient(config)
  prompt = ('Reply with a short JSON object only: '
            '{"status":"ok","provider":"chat"}')
  response = client.complete(prompt, temperature=0, max_tokens=80)

  print("[chat] raw response:", response)

  try:
    parsed = json.loads(response)
  except json.JSONDecodeError as exc:
    raise RuntimeError("chat response was not valid JSON") from exc

  status = parsed.get("status")
  if status != "ok":
    raise RuntimeError(f"unexpected chat status: {parsed}")

  print("[chat] success")


def _check_embedding(args):
  config = {
    "provider": args.embedding_provider,
    "api_key": _resolve_key(args.embedding_api_key, "EMBEDDING_API_KEY"),
    "base_url": (args.embedding_base_url
                  or _default_embedding_base_url(args.embedding_provider)),
    "model": args.embedding_model,
    "timeout_sec": args.timeout_sec,
    "debug": args.debug,
  }
  client = EmbeddingClient(config)
  vector = client.embed_text("agent town embedding connectivity check")

  if not vector:
    raise RuntimeError("embedding response returned an empty vector")

  print(f"[embedding] success dimension={len(vector)}")


def main():
  parser = _build_parser()
  args = parser.parse_args()

  try:
    _check_chat(args)
    _check_embedding(args)
  except AIClientError as exc:
    print(
      f"[self-check] failed: category={exc.category} message={exc}",
      file=sys.stderr,
    )
    raise SystemExit(1) from exc
  except Exception as exc:
    print(f"[self-check] failed: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc

  print("[self-check] all checks passed")


if __name__ == "__main__":
  main()
