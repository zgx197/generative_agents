"""
Inspect AI runtime and embedding-storage state for a saved simulation.
"""
import argparse
import json
import os

from utils import *
from persona.prompt_template.gpt_structure import (
  get_ai_runtime_audit_metadata,
  get_embedding_compatibility_report,
  get_saved_embedding_metadata,
)


def _resolve_storage_root():
  return os.path.abspath(os.path.join(os.path.dirname(__file__), fs_storage))


def _resolve_sim_folder(sim_code, sim_path):
  if sim_path:
    return os.path.abspath(sim_path)
  if not sim_code:
    raise ValueError("either --sim-code or --sim-path is required")
  return os.path.abspath(os.path.join(_resolve_storage_root(), sim_code))


def _load_json(path, default):
  if not os.path.exists(path):
    return default
  with open(path, "r", encoding="utf-8") as f:
    return json.load(f)


def _read_migration_log_summary(sim_folder):
  log_path = os.path.join(sim_folder, "reverie", "embedding_migration_log.jsonl")
  if not os.path.exists(log_path):
    return {
      "exists": False,
      "entries": 0,
      "latest": None,
    }

  latest = None
  entries = 0
  with open(log_path, "r", encoding="utf-8") as f:
    for line in f:
      line = line.strip()
      if not line:
        continue
      latest = json.loads(line)
      entries += 1

  return {
    "exists": True,
    "entries": entries,
    "latest": latest,
  }


def _inspect_persona(persona_name, assoc_dir):
  nodes_path = os.path.join(assoc_dir, "nodes.json")
  embeddings_path = os.path.join(assoc_dir, "embeddings.json")
  backup_path = embeddings_path + ".bak"

  nodes = _load_json(nodes_path, {})
  embeddings = _load_json(embeddings_path, {})

  node_keys = sorted({
    node.get("embedding_key")
    for node in nodes.values()
    if node.get("embedding_key")
  })
  embedding_keys = sorted(key for key in embeddings.keys() if key)

  missing_keys = sorted(set(node_keys) - set(embedding_keys))
  extra_keys = sorted(set(embedding_keys) - set(node_keys))

  vector_dimensions = sorted({
    len(value) for value in embeddings.values() if isinstance(value, list)
  })

  status = "ok"
  if missing_keys:
    status = "missing_embedding_vectors"
  elif not embeddings:
    status = "empty_embeddings"
  elif len(vector_dimensions) > 1:
    status = "mixed_vector_dimensions"

  return {
    "persona_name": persona_name,
    "status": status,
    "node_embedding_keys": len(node_keys),
    "stored_embeddings": len(embedding_keys),
    "missing_key_count": len(missing_keys),
    "extra_key_count": len(extra_keys),
    "vector_dimensions": vector_dimensions,
    "backup_exists": os.path.exists(backup_path),
    "sample_missing_keys": missing_keys[:3],
    "sample_extra_keys": extra_keys[:3],
  }


def build_report(sim_folder):
  if not os.path.isdir(sim_folder):
    raise SystemExit(f"simulation folder not found: {sim_folder}")

  meta_path = os.path.join(sim_folder, "reverie", "meta.json")
  meta = _load_json(meta_path, {})
  compatibility = get_embedding_compatibility_report(meta, sim_folder)
  migration_log = _read_migration_log_summary(sim_folder)

  personas_root = os.path.join(sim_folder, "personas")
  persona_reports = []
  if os.path.isdir(personas_root):
    for persona_name in sorted(os.listdir(personas_root)):
      assoc_dir = os.path.join(
        personas_root, persona_name, "bootstrap_memory", "associative_memory")
      if not os.path.isdir(assoc_dir):
        continue
      persona_reports.append(_inspect_persona(persona_name, assoc_dir))

  total_missing = sum(item["missing_key_count"] for item in persona_reports)
  total_extra = sum(item["extra_key_count"] for item in persona_reports)
  backup_personas = sum(1 for item in persona_reports if item["backup_exists"])

  return {
    "simulation": {
      "sim_code": os.path.basename(sim_folder),
      "sim_folder": sim_folder,
    },
    "saved_embedding": get_saved_embedding_metadata(meta, sim_folder),
    "runtime_ai": get_ai_runtime_audit_metadata(),
    "meta": meta,
    "embedding_compatibility": compatibility,
    "migration_log": migration_log,
    "summary": {
      "persona_count": len(persona_reports),
      "backup_persona_count": backup_personas,
      "total_missing_key_count": total_missing,
      "total_extra_key_count": total_extra,
    },
    "personas": persona_reports,
  }


def _print_text_report(report):
  simulation = report["simulation"]
  compatibility = report["embedding_compatibility"]
  runtime_ai = report["runtime_ai"]
  summary = report["summary"]
  migration_log = report["migration_log"]

  print(f"[inspect] simulation={simulation['sim_folder']}")
  print(
    "[inspect] runtime chat="
    f"{runtime_ai['chat']['chat_provider']}/{runtime_ai['chat']['chat_model']}"
  )
  print(
    "[inspect] runtime embedding="
    f"{runtime_ai['embedding']['embedding_provider']}/"
    f"{runtime_ai['embedding']['embedding_model']}"
  )
  print(
    "[inspect] compatibility="
    f"{compatibility['status']} policy={compatibility['mixing_policy']}"
  )
  print(
    "[inspect] saved embedding="
    f"{compatibility['saved_embedding']}"
  )
  print(
    "[inspect] personas="
    f"{summary['persona_count']} backups={summary['backup_persona_count']}"
  )
  print(
    "[inspect] missing_keys="
    f"{summary['total_missing_key_count']} extra_keys={summary['total_extra_key_count']}"
  )
  if migration_log["exists"]:
    latest = migration_log["latest"]
    print(
      "[inspect] migration_log="
      f"{migration_log['entries']} entries latest={latest.get('timestamp')}"
    )
  else:
    print("[inspect] migration_log=not found")

  for persona in report["personas"]:
    print(
      "[inspect] persona="
      f"{persona['persona_name']} status={persona['status']} "
      f"stored={persona['stored_embeddings']} "
      f"node_keys={persona['node_embedding_keys']} "
      f"dims={persona['vector_dimensions']} "
      f"backup={persona['backup_exists']}"
    )


def main():
  parser = argparse.ArgumentParser(
    description="Inspect AI metadata, embedding compatibility, and vector files."
  )
  parser.add_argument("--sim-code", default=None,
                      help="Simulation code under fs_storage")
  parser.add_argument("--sim-path", default=None,
                      help="Explicit path to a simulation folder")
  parser.add_argument("--json", action="store_true",
                      help="Print the full report as JSON")
  args = parser.parse_args()

  sim_folder = _resolve_sim_folder(args.sim_code, args.sim_path)
  report = build_report(sim_folder)

  if args.json:
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return

  _print_text_report(report)


if __name__ == "__main__":
  main()
