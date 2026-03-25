import json
import os


def _env(name, default=None):
  value = os.getenv(name)
  if value is None or value == "":
    return default
  return value


def _as_bool(value, default=False):
  if value is None:
    return default
  if isinstance(value, bool):
    return value
  if isinstance(value, (int, float)):
    return bool(value)
  return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value, default):
  if value is None or value == "":
    return default
  return int(value)


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, "..", ".."))
_DEFAULT_AI_CONFIG_PATH = os.path.join(_REPO_ROOT, "config", "ai_config.local.json")
_AI_CONFIG_CACHE = None


def _load_ai_config():
  global _AI_CONFIG_CACHE
  if _AI_CONFIG_CACHE is not None:
    return _AI_CONFIG_CACHE

  config_path = _env("GA_AI_CONFIG_PATH", _DEFAULT_AI_CONFIG_PATH)
  config_data = {}
  if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as config_file:
      loaded = json.load(config_file)
    if not isinstance(loaded, dict):
      raise RuntimeError(f"AI config must be a JSON object: {config_path}")
    config_data = loaded

  _AI_CONFIG_CACHE = {
    "path": config_path,
    "data": config_data,
  }
  return _AI_CONFIG_CACHE


def _config_section(name):
  section = _load_ai_config()["data"].get(name, {})
  if isinstance(section, dict):
    return section
  return {}


def _config_value(section, key, default=None):
  value = _config_section(section).get(key, default)
  if value is None or value == "":
    return default
  return value


ai_config_path = _load_ai_config()["path"]

# Legacy compatibility field. Older code may still read this directly.
openai_api_key = (
  _env("GA_OPENAI_API_KEY")
  or _env("OPENAI_API_KEY")
  or _env("GA_CHAT_API_KEY")
  or _config_value("chat", "api_key", "")
)

# Optional metadata from the original setup instructions.
key_owner = _config_value("meta", "key_owner", "local-json-config")

maze_assets_loc = "../../environment/frontend_server/static_dirs/assets"
env_matrix = f"{maze_assets_loc}/the_ville/matrix"
env_visuals = f"{maze_assets_loc}/the_ville/visuals"

fs_storage = "../../environment/frontend_server/storage"
fs_temp_storage = "../../environment/frontend_server/temp_storage"

collision_block_id = "32125"

# Provider-aware chat configuration.
chat_provider = _env("GA_CHAT_PROVIDER", _config_value("chat", "provider", "qwen"))
chat_api_key = (
  _env("GA_CHAT_API_KEY")
  or _env("DASHSCOPE_API_KEY")
  or _config_value("chat", "api_key", "")
)
chat_base_url = _env(
  "GA_CHAT_BASE_URL",
  _config_value("chat", "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
)
chat_model = _env("GA_CHAT_MODEL", _config_value("chat", "model", "qwen3.5-flash"))
chat_model_advanced = _env(
  "GA_CHAT_MODEL_ADVANCED",
  _config_value("chat", "advanced_model", chat_model)
)
chat_enable_thinking = _as_bool(
  _env("GA_QWEN_ENABLE_THINKING", _config_value("chat", "enable_thinking", False)),
  False,
)

# Provider-aware embedding configuration.
embedding_provider = _env(
  "GA_EMBEDDING_PROVIDER",
  _config_value("embedding", "provider", "qwen")
)
embedding_api_key = (
  _env("GA_EMBEDDING_API_KEY")
  or _env("DASHSCOPE_API_KEY")
  or _config_value("embedding", "api_key", "")
)
embedding_base_url = _env(
  "GA_EMBEDDING_BASE_URL",
  _config_value(
    "embedding",
    "base_url",
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
  )
)
embedding_model = _env(
  "GA_EMBEDDING_MODEL",
  _config_value("embedding", "model", "text-embedding-v4")
)
embedding_schema_version = _as_int(
  _config_value("embedding", "schema_version", 1),
  1,
)
embedding_mixing_policy = _config_value(
  "embedding",
  "mixing_policy",
  "forbid",
)

runtime_section = _config_section("runtime")
request_timeout_sec = _as_int(
  _env("GA_REQUEST_TIMEOUT_SEC", runtime_section.get("request_timeout_sec", 60)),
  60,
)
debug_llm = _as_bool(
  _env("GA_DEBUG_LLM", runtime_section.get("debug_llm", False)),
  False,
)
ai_audit_enabled = _as_bool(
  _env("GA_AI_AUDIT_ENABLED", runtime_section.get("ai_audit_enabled", True)),
  True,
)
ai_audit_dir = _env(
  "GA_AI_AUDIT_DIR",
  runtime_section.get("ai_audit_dir", "../../environment/frontend_server/storage/_ai_audit"),
)
ai_audit_preview_chars = _as_int(
  _env("GA_AI_AUDIT_PREVIEW_CHARS", runtime_section.get("ai_audit_preview_chars", 160)),
  160,
)

# Verbose project debug switch used by existing code.
debug = _as_bool(_env("GA_DEBUG", runtime_section.get("debug", False)), False)
