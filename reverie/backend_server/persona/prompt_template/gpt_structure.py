"""
Author: Joon Sung Park (joonspk@stanford.edu)

File: gpt_structure.py
Description: Compatibility wrapper for chat and embedding providers.
"""
import json
import os
import time 

from utils import *
from persona.prompt_template.ai_observability import AIClientError
from persona.prompt_template.chat_client import *
from persona.prompt_template.embedding_client import *

_chat_client = None
_embedding_client = None
_client_signature = None

def temp_sleep(seconds=0.1):
  time.sleep(seconds)


def _setting(name, default=None):
  return globals().get(name, default)


def _build_ai_config():
  chat_provider = str(_setting("chat_provider", "openai")).lower()
  chat_api_key = (_setting("chat_api_key", None)
                  or _setting("openai_api_key", ""))
  chat_base_url = _setting("chat_base_url", None)
  if not chat_base_url:
    if chat_provider in ("dashscope", "qwen", "aliyun"):
      chat_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    elif chat_provider in ("moonshot", "kimi"):
      chat_base_url = "https://api.moonshot.cn/v1"
    else:
      chat_base_url = "https://api.openai.com/v1"

  default_chat_model = _setting("chat_model", None)
  if not default_chat_model:
    if chat_provider in ("dashscope", "qwen", "aliyun"):
      default_chat_model = "qwen-plus"
    else:
      default_chat_model = "gpt-3.5-turbo"

  advanced_chat_model = (_setting("chat_model_advanced", None)
                         or _setting("chat_advanced_model", None))
  if not advanced_chat_model:
    if chat_provider in ("dashscope", "qwen", "aliyun"):
      advanced_chat_model = default_chat_model
    else:
      advanced_chat_model = "gpt-4"

  embedding_provider = str(_setting("embedding_provider", chat_provider)).lower()
  embedding_api_key = (_setting("embedding_api_key", None)
                       or chat_api_key)
  embedding_base_url = _setting("embedding_base_url", None)
  if not embedding_base_url:
    if embedding_provider in ("dashscope", "qwen", "aliyun"):
      embedding_base_url = ("https://dashscope.aliyuncs.com/api/v1/services/"
                            "embeddings/text-embedding/text-embedding")
    else:
      embedding_base_url = "https://api.openai.com/v1"

  embedding_model = _setting("embedding_model", None)
  if not embedding_model:
    if embedding_provider in ("dashscope", "qwen", "aliyun"):
      embedding_model = "text-embedding-v4"
    else:
      embedding_model = "text-embedding-ada-002"

  timeout_sec = int(_setting("request_timeout_sec", 60))
  debug_llm = bool(_setting("debug_llm", _setting("debug", False)))

  return {
    "chat": {
      "provider": chat_provider,
      "api_key": chat_api_key,
      "base_url": chat_base_url,
      "model": default_chat_model,
      "advanced_model": advanced_chat_model,
      "timeout_sec": timeout_sec,
      "debug": debug_llm,
    },
    "embedding": {
      "provider": embedding_provider,
      "api_key": embedding_api_key,
      "base_url": embedding_base_url,
      "model": embedding_model,
      "timeout_sec": timeout_sec,
      "debug": debug_llm,
    }
  }


def get_embedding_runtime_metadata():
  config = _build_ai_config()["embedding"]
  return {
    "embedding_provider": config["provider"],
    "embedding_model": config["model"],
    "embedding_schema_version": int(_setting("embedding_schema_version", 1)),
  }


def get_chat_runtime_metadata():
  config = _build_ai_config()["chat"]
  return {
    "chat_provider": config["provider"],
    "chat_model": config["model"],
    "chat_model_advanced": config["advanced_model"],
  }


def get_ai_runtime_audit_metadata():
  return {
    "chat": get_chat_runtime_metadata(),
    "embedding": get_embedding_runtime_metadata(),
    "policy": {
      "embedding_mixing_policy": get_embedding_mixing_policy(),
    }
  }


def get_embedding_mixing_policy():
  return str(_setting("embedding_mixing_policy", "forbid")).lower()


def _simulation_has_saved_embeddings(sim_folder):
  personas_root = os.path.join(sim_folder, "personas")
  if not os.path.isdir(personas_root):
    return False

  for root, _, files in os.walk(personas_root):
    if "embeddings.json" not in files:
      continue
    embeddings_path = os.path.join(root, "embeddings.json")
    try:
      if os.path.getsize(embeddings_path) > 2:
        return True
    except OSError:
      pass
  return False


def _infer_saved_embedding_metadata(reverie_meta, sim_folder):
  provider = reverie_meta.get("embedding_provider")
  model = reverie_meta.get("embedding_model")
  if provider and model:
    return {
      "embedding_provider": provider,
      "embedding_model": model,
      "embedding_schema_version": int(
        reverie_meta.get("embedding_schema_version",
                         _setting("embedding_schema_version", 1))),
    }

  if _simulation_has_saved_embeddings(sim_folder):
    return {
      "embedding_provider": "openai",
      "embedding_model": "text-embedding-ada-002",
      "embedding_schema_version": 1,
    }

  return None


def get_saved_embedding_metadata(reverie_meta, sim_folder):
  saved_meta = _infer_saved_embedding_metadata(reverie_meta, sim_folder)
  if saved_meta is None:
    return None
  return dict(saved_meta)


def get_embedding_compatibility_report(reverie_meta, sim_folder):
  current_meta = get_embedding_runtime_metadata()
  saved_meta = _infer_saved_embedding_metadata(reverie_meta, sim_folder)
  has_saved_embeddings = _simulation_has_saved_embeddings(sim_folder)
  metadata_explicit = bool(
    reverie_meta.get("embedding_provider") and reverie_meta.get("embedding_model")
  )

  mismatch = False
  if saved_meta is not None:
    mismatch = (
      saved_meta["embedding_provider"] != current_meta["embedding_provider"]
      or saved_meta["embedding_model"] != current_meta["embedding_model"]
    )

  if saved_meta is None:
    status = "missing_saved_embedding_metadata"
  elif mismatch:
    status = "mismatch"
  else:
    status = "compatible"

  return {
    "status": status,
    "mixing_policy": get_embedding_mixing_policy(),
    "has_saved_embeddings": has_saved_embeddings,
    "saved_embedding": dict(saved_meta) if saved_meta else None,
    "current_embedding": current_meta,
    "metadata_explicit": metadata_explicit,
    "inferred_legacy_metadata": (
      saved_meta is not None and has_saved_embeddings and not metadata_explicit
    ),
  }


def ensure_embedding_metadata_compatible(reverie_meta, sim_folder):
  current_meta = get_embedding_runtime_metadata()
  saved_meta = _infer_saved_embedding_metadata(reverie_meta, sim_folder)

  if saved_meta is None:
    changed = False
    for key, value in current_meta.items():
      if reverie_meta.get(key) != value:
        reverie_meta[key] = value
        changed = True
    return changed

  mismatch = (
    saved_meta["embedding_provider"] != current_meta["embedding_provider"]
    or saved_meta["embedding_model"] != current_meta["embedding_model"]
  )

  if mismatch:
    message = (
      "Embedding configuration mismatch detected. "
      f"Simulation expects {saved_meta['embedding_provider']}/"
      f"{saved_meta['embedding_model']}, but current config is "
      f"{current_meta['embedding_provider']}/"
      f"{current_meta['embedding_model']}."
    )
    if get_embedding_mixing_policy() == "forbid":
      raise RuntimeError(
        message
        + " Refusing to continue to avoid mixing vector spaces. "
        + "Update utils.py to match the simulation, or rebuild the saved "
        + "embeddings before using a new embedding model."
      )
    print("[Embedding WARNING]", message)

  changed = False
  for key, value in saved_meta.items():
    if reverie_meta.get(key) != value:
      reverie_meta[key] = value
      changed = True
  return changed


def _ensure_clients():
  global _chat_client
  global _embedding_client
  global _client_signature

  config = _build_ai_config()
  signature = json.dumps(config, sort_keys=True)
  if signature == _client_signature and _chat_client and _embedding_client:
    return

  _chat_client = ChatClient(config["chat"])
  _embedding_client = EmbeddingClient(config["embedding"])
  _client_signature = signature


def _get_chat_client():
  _ensure_clients()
  return _chat_client


def _get_embedding_client():
  _ensure_clients()
  return _embedding_client


def _resolve_default_chat_model():
  _ensure_clients()
  return _chat_client.default_model


def _resolve_advanced_chat_model():
  _ensure_clients()
  return _chat_client.advanced_model


def _map_legacy_engine(engine):
  if not engine:
    return _resolve_default_chat_model()

  lowered = str(engine).lower()
  if lowered in ("gpt-4", "gpt-4o", "gpt-4-turbo"):
    return _resolve_advanced_chat_model()
  if lowered.startswith("gpt-"):
    return engine
  return _resolve_default_chat_model()


def _describe_ai_error(exc):
  if isinstance(exc, AIClientError):
    return f"{exc.category}: {exc}"
  return str(exc)


def ChatGPT_single_request(prompt): 
  temp_sleep()
  return _get_chat_client().complete(prompt, model=_resolve_default_chat_model())


# ============================================================================
# #####################[SECTION 1: CHATGPT-3 STRUCTURE] ######################
# ============================================================================

def GPT4_request(prompt): 
  """
  Given a prompt and a dictionary of GPT parameters, make a request to OpenAI
  server and returns the response. 
  ARGS:
    prompt: a str prompt
    gpt_parameter: a python dictionary with the keys indicating the names of  
                   the parameter and the values indicating the parameter 
                   values.   
  RETURNS: 
    a str of GPT-3's response. 
  """
  temp_sleep()

  try: 
    return _get_chat_client().complete(prompt, model=_resolve_advanced_chat_model())
  except Exception as exc: 
    print ("ChatGPT ERROR", _describe_ai_error(exc))
    return "ChatGPT ERROR"


def ChatGPT_request(prompt): 
  """
  Given a prompt and a dictionary of GPT parameters, make a request to OpenAI
  server and returns the response. 
  ARGS:
    prompt: a str prompt
    gpt_parameter: a python dictionary with the keys indicating the names of  
                   the parameter and the values indicating the parameter 
                   values.   
  RETURNS: 
    a str of GPT-3's response. 
  """
  # temp_sleep()
  try: 
    return _get_chat_client().complete(prompt, model=_resolve_default_chat_model())
  except Exception as exc: 
    print ("ChatGPT ERROR", _describe_ai_error(exc))
    return "ChatGPT ERROR"


def GPT4_safe_generate_response(prompt, 
                                   example_output,
                                   special_instruction,
                                   repeat=3,
                                   fail_safe_response="error",
                                   func_validate=None,
                                   func_clean_up=None,
                                   verbose=False): 
  prompt = 'GPT-3 Prompt:\n"""\n' + prompt + '\n"""\n'
  prompt += f"Output the response to the prompt above in json. {special_instruction}\n"
  prompt += "Example output json:\n"
  prompt += '{"output": "' + str(example_output) + '"}'

  if verbose: 
    print ("CHAT GPT PROMPT")
    print (prompt)

  for i in range(repeat): 

    try: 
      curr_gpt_response = GPT4_request(prompt).strip()
      end_index = curr_gpt_response.rfind('}') + 1
      curr_gpt_response = curr_gpt_response[:end_index]
      curr_gpt_response = json.loads(curr_gpt_response)["output"]
      
      if func_validate(curr_gpt_response, prompt=prompt): 
        return func_clean_up(curr_gpt_response, prompt=prompt)
      
      if verbose: 
        print ("---- repeat count: \n", i, curr_gpt_response)
        print (curr_gpt_response)
        print ("~~~~")

    except: 
      pass

  return False


def ChatGPT_safe_generate_response(prompt, 
                                   example_output,
                                   special_instruction,
                                   repeat=3,
                                   fail_safe_response="error",
                                   func_validate=None,
                                   func_clean_up=None,
                                   verbose=False): 
  # prompt = 'GPT-3 Prompt:\n"""\n' + prompt + '\n"""\n'
  prompt = '"""\n' + prompt + '\n"""\n'
  prompt += f"Output the response to the prompt above in json. {special_instruction}\n"
  prompt += "Example output json:\n"
  prompt += '{"output": "' + str(example_output) + '"}'

  if verbose: 
    print ("CHAT GPT PROMPT")
    print (prompt)

  for i in range(repeat): 

    try: 
      curr_gpt_response = ChatGPT_request(prompt).strip()
      end_index = curr_gpt_response.rfind('}') + 1
      curr_gpt_response = curr_gpt_response[:end_index]
      curr_gpt_response = json.loads(curr_gpt_response)["output"]

      # print ("---ashdfaf")
      # print (curr_gpt_response)
      # print ("000asdfhia")
      
      if func_validate(curr_gpt_response, prompt=prompt): 
        return func_clean_up(curr_gpt_response, prompt=prompt)
      
      if verbose: 
        print ("---- repeat count: \n", i, curr_gpt_response)
        print (curr_gpt_response)
        print ("~~~~")

    except: 
      pass

  return False


def ChatGPT_safe_generate_response_OLD(prompt, 
                                   repeat=3,
                                   fail_safe_response="error",
                                   func_validate=None,
                                   func_clean_up=None,
                                   verbose=False): 
  if verbose: 
    print ("CHAT GPT PROMPT")
    print (prompt)

  for i in range(repeat): 
    try: 
      curr_gpt_response = ChatGPT_request(prompt).strip()
      if func_validate(curr_gpt_response, prompt=prompt): 
        return func_clean_up(curr_gpt_response, prompt=prompt)
      if verbose: 
        print (f"---- repeat count: {i}")
        print (curr_gpt_response)
        print ("~~~~")

    except: 
      pass
  print ("FAIL SAFE TRIGGERED") 
  return fail_safe_response


# ============================================================================
# ###################[SECTION 2: ORIGINAL GPT-3 STRUCTURE] ###################
# ============================================================================

def GPT_request(prompt, gpt_parameter): 
  """
  Given a prompt and a dictionary of legacy GPT parameters, route the request
  through the configured chat provider.
  ARGS:
    prompt: a str prompt
    gpt_parameter: a python dictionary with the keys indicating the names of  
                   the parameter and the values indicating the parameter 
                   values.   
  RETURNS: 
    a str of GPT-3's response. 
  """
  temp_sleep()
  try: 
    request_model = _map_legacy_engine(gpt_parameter.get("engine"))
    return _get_chat_client().complete(
      prompt,
      model=request_model,
      temperature=gpt_parameter.get("temperature"),
      max_tokens=gpt_parameter.get("max_tokens"),
      stop=gpt_parameter.get("stop"),
    )
  except Exception as exc: 
    print ("TOKEN LIMIT EXCEEDED", _describe_ai_error(exc))
    return "TOKEN LIMIT EXCEEDED"


def generate_prompt(curr_input, prompt_lib_file): 
  """
  Takes in the current input (e.g. comment that you want to classifiy) and 
  the path to a prompt file. The prompt file contains the raw str prompt that
  will be used, which contains the following substr: !<INPUT>! -- this 
  function replaces this substr with the actual curr_input to produce the 
  final promopt that will be sent to the GPT3 server. 
  ARGS:
    curr_input: the input we want to feed in (IF THERE ARE MORE THAN ONE
                INPUT, THIS CAN BE A LIST.)
    prompt_lib_file: the path to the promopt file. 
  RETURNS: 
    a str prompt that will be sent to OpenAI's GPT server.  
  """
  if type(curr_input) == type("string"): 
    curr_input = [curr_input]
  curr_input = [str(i) for i in curr_input]

  f = open(prompt_lib_file, "r")
  prompt = f.read()
  f.close()
  for count, i in enumerate(curr_input):   
    prompt = prompt.replace(f"!<INPUT {count}>!", i)
  if "<commentblockmarker>###</commentblockmarker>" in prompt: 
    prompt = prompt.split("<commentblockmarker>###</commentblockmarker>")[1]
  return prompt.strip()


def safe_generate_response(prompt, 
                           gpt_parameter,
                           repeat=5,
                           fail_safe_response="error",
                           func_validate=None,
                           func_clean_up=None,
                           verbose=False): 
  if verbose: 
    print (prompt)

  for i in range(repeat): 
    curr_gpt_response = GPT_request(prompt, gpt_parameter)
    if func_validate(curr_gpt_response, prompt=prompt): 
      return func_clean_up(curr_gpt_response, prompt=prompt)
    if verbose: 
      print ("---- repeat count: ", i, curr_gpt_response)
      print (curr_gpt_response)
      print ("~~~~")
  return fail_safe_response


def get_embedding(text, model="text-embedding-ada-002"):
  text = text.replace("\n", " ")
  if not text: 
    text = "this is blank"
  request_model = model
  if model == "text-embedding-ada-002":
    request_model = None
  return _get_embedding_client().embed_text(text, model=request_model)


if __name__ == '__main__':
  gpt_parameter = {"engine": "text-davinci-003", "max_tokens": 50, 
                   "temperature": 0, "top_p": 1, "stream": False,
                   "frequency_penalty": 0, "presence_penalty": 0, 
                   "stop": ['"']}
  curr_input = ["driving to a friend's house"]
  prompt_lib_file = "prompt_template/test_prompt_July5.txt"
  prompt = generate_prompt(curr_input, prompt_lib_file)

  def __func_validate(gpt_response): 
    if len(gpt_response.strip()) <= 1:
      return False
    if len(gpt_response.strip().split(" ")) > 1: 
      return False
    return True
  def __func_clean_up(gpt_response):
    cleaned_response = gpt_response.strip()
    return cleaned_response

  output = safe_generate_response(prompt, 
                                 gpt_parameter,
                                 5,
                                 "rest",
                                 __func_validate,
                                 __func_clean_up,
                                 True)

  print (output)
















