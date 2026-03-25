"""
Rebuild associative-memory embeddings for an existing simulation.

This script migrates a saved simulation into the currently configured
embedding provider/model defined in utils.py.
"""
import argparse
import datetime
import json
import os
from pathlib import Path

from utils import *
from persona.prompt_template.embedding_client import EmbeddingClient
from persona.prompt_template.gpt_structure import (
  get_ai_runtime_audit_metadata,
  get_embedding_runtime_metadata,
  get_saved_embedding_metadata,
)


def _resolve_storage_root():
  return os.path.abspath(os.path.join(os.path.dirname(__file__), fs_storage))


def _build_embedding_config():
  return {
    "provider": str(globals().get("embedding_provider", "openai")).lower(),
    "api_key": (globals().get("embedding_api_key", None)
                or globals().get("openai_api_key", "")),
    "base_url": globals().get("embedding_base_url", "https://api.openai.com/v1"),
    "model": globals().get("embedding_model", "text-embedding-ada-002"),
    "timeout_sec": int(globals().get("request_timeout_sec", 60)),
    "debug": bool(globals().get("debug_llm", globals().get("debug", False))),
  }


def _collect_embedding_keys(nodes_path, embeddings_path):
  keys = set()

  if os.path.exists(nodes_path):
    with open(nodes_path, "r", encoding="utf-8") as f:
      nodes = json.load(f)
    for node in nodes.values():
      embedding_key = node.get("embedding_key")
      if embedding_key:
        keys.add(embedding_key)

  if os.path.exists(embeddings_path):
    with open(embeddings_path, "r", encoding="utf-8") as f:
      existing = json.load(f)
    for embedding_key in existing.keys():
      if embedding_key:
        keys.add(embedding_key)

  return sorted(keys)


def _chunked(items, size):
  for start in range(0, len(items), size):
    yield items[start:start + size]


def _rebuild_persona_embeddings(client, assoc_dir, batch_size, dry_run):
  nodes_path = os.path.join(assoc_dir, "nodes.json")
  embeddings_path = os.path.join(assoc_dir, "embeddings.json")
  keys = _collect_embedding_keys(nodes_path, embeddings_path)
  backup_created = False

  if not keys:
    return {
      "key_count": 0,
      "backup_created": False,
    }

  if dry_run:
    return {
      "key_count": len(keys),
      "backup_created": False,
    }

  rebuilt = {}
  for batch in _chunked(keys, batch_size):
    vectors = client.embed_texts(batch)
    if len(vectors) != len(batch):
      raise RuntimeError(
        f"embedding batch size mismatch in {assoc_dir}: "
        f"requested {len(batch)} got {len(vectors)}"
      )
    for index, key in enumerate(batch):
      rebuilt[key] = vectors[index]

  backup_path = embeddings_path + ".bak"
  if os.path.exists(embeddings_path) and not os.path.exists(backup_path):
    Path(backup_path).write_bytes(Path(embeddings_path).read_bytes())
    backup_created = True

  with open(embeddings_path, "w", encoding="utf-8") as f:
    json.dump(rebuilt, f)

  return {
    "key_count": len(keys),
    "backup_created": backup_created,
  }


def _update_meta(sim_folder, dry_run):
  meta_path = os.path.join(sim_folder, "reverie", "meta.json")
  with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

  meta.update(get_embedding_runtime_metadata())
  meta["ai_runtime"] = get_ai_runtime_audit_metadata()

  if not dry_run:
    with open(meta_path, "w", encoding="utf-8") as f:
      json.dump(meta, f, indent=2)

  return meta


def _append_migration_log(sim_folder, source_embedding, target_embedding,
                          persona_stats, total_keys):
  log_path = os.path.join(sim_folder, "reverie", "embedding_migration_log.jsonl")
  payload = {
    "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "action": "rebuild_embeddings",
    "simulation": {
      "sim_code": os.path.basename(sim_folder),
      "sim_folder": sim_folder,
    },
    "source_embedding": source_embedding,
    "target_embedding": target_embedding,
    "total_keys": total_keys,
    "persona_stats": persona_stats,
    "ai_runtime": get_ai_runtime_audit_metadata(),
  }
  with open(log_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _resolve_sim_folder(sim_code, sim_path):
  if sim_path:
    return os.path.abspath(sim_path)
  if not sim_code:
    raise ValueError("either --sim-code or --sim-path is required")
  return os.path.abspath(os.path.join(_resolve_storage_root(), sim_code))


def main():
  parser = argparse.ArgumentParser(
    description="Rebuild saved simulation embeddings using the current embedding config."
  )
  parser.add_argument("--sim-code", default=None,
                      help="Simulation code under fs_storage")
  parser.add_argument("--sim-path", default=None,
                      help="Explicit path to a simulation folder")
  parser.add_argument("--batch-size", type=int, default=6,
                      help="Embedding batch size")
  parser.add_argument("--dry-run", action="store_true",
                      help="Report what would be rebuilt without writing files")
  args = parser.parse_args()

  sim_folder = _resolve_sim_folder(args.sim_code, args.sim_path)
  personas_root = os.path.join(sim_folder, "personas")
  if not os.path.isdir(personas_root):
    raise SystemExit(f"personas folder not found: {personas_root}")

  client = EmbeddingClient(_build_embedding_config())
  persona_dirs = sorted(
    path for path in os.listdir(personas_root)
    if os.path.isdir(os.path.join(personas_root, path))
  )

  print(f"[rebuild] simulation={sim_folder}")
  print(f"[rebuild] provider={client.provider} model={client.default_model}")
  print(f"[rebuild] personas={len(persona_dirs)} dry_run={args.dry_run}")

  total_keys = 0
  persona_stats = {}
  meta_path = os.path.join(sim_folder, "reverie", "meta.json")
  with open(meta_path, "r", encoding="utf-8") as f:
    original_meta = json.load(f)
  source_embedding = get_saved_embedding_metadata(original_meta, sim_folder)

  for persona_name in persona_dirs:
    assoc_dir = os.path.join(
      personas_root, persona_name, "bootstrap_memory", "associative_memory")
    if not os.path.isdir(assoc_dir):
      print(f"[rebuild] skip {persona_name}: associative_memory not found")
      continue

    result = _rebuild_persona_embeddings(
      client, assoc_dir, args.batch_size, args.dry_run)
    rebuilt_count = result["key_count"]
    total_keys += rebuilt_count
    persona_stats[persona_name] = result
    action = "would rebuild" if args.dry_run else "rebuilt"
    print(f"[rebuild] {persona_name}: {action} {rebuilt_count} embedding keys")

  meta = _update_meta(sim_folder, args.dry_run)
  print(
    "[rebuild] target meta embedding="
    f"{meta.get('embedding_provider')}/{meta.get('embedding_model')}"
  )
  print(f"[rebuild] total_keys={total_keys}")
  if args.dry_run:
    print("[rebuild] dry-run only: no files were modified")
  else:
    _append_migration_log(
      sim_folder,
      source_embedding,
      get_embedding_runtime_metadata(),
      persona_stats,
      total_keys,
    )
    print("[rebuild] migration log appended to reverie/embedding_migration_log.jsonl")
  print("[rebuild] done")


if __name__ == "__main__":
  main()
