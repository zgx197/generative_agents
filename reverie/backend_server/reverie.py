"""
Author: Joon Sung Park (joonspk@stanford.edu)

File: reverie.py
Description: This is the main program for running generative agent simulations
that defines the ReverieServer class. This class maintains and records all  
states related to the simulation. The primary mode of interaction for those  
running the simulation should be through the open_server function, which  
enables the simulator to input command-line prompts for running and saving  
the simulation, among other tasks.

Release note (June 14, 2023) -- Reverie implements the core simulation 
mechanism described in my paper entitled "Generative Agents: Interactive 
Simulacra of Human Behavior." If you are reading through these lines after 
having read the paper, you might notice that I use older terms to describe 
generative agents and their cognitive modules here. Most notably, I use the 
term "personas" to refer to generative agents, "associative memory" to refer 
to the memory stream, and "reverie" to refer to the overarching simulation 
framework.
"""
import argparse
import json
import numpy
import datetime
import pickle
import io
import time
import math
import os
import shutil
import sys
import threading
import traceback

try:
  from selenium import webdriver
except ImportError:
  webdriver = None

from global_methods import *
from utils import *
from maze import *
from persona.persona import *
from persona.prompt_template.gpt_structure import *


class _TeeStream(io.TextIOBase):
  def __init__(self, primary_stream, mirror_stream):
    self._primary_stream = primary_stream
    self._mirror_stream = mirror_stream

  @property
  def encoding(self):
    return getattr(self._primary_stream, "encoding", "utf-8")

  def write(self, data):
    if not isinstance(data, str):
      data = str(data)
    self._primary_stream.write(data)
    self._primary_stream.flush()
    self._mirror_stream.write(data)
    self._mirror_stream.flush()
    return len(data)

  def flush(self):
    self._primary_stream.flush()
    self._mirror_stream.flush()

  def isatty(self):
    return bool(getattr(self._primary_stream, "isatty", lambda: False)())


def _install_process_logging():
  log_path = os.getenv("GA_BACKEND_LOG_PATH")
  if not log_path:
    return
  if getattr(sys, "_ga_process_logging_installed", False):
    return

  log_dir = os.path.dirname(log_path)
  if log_dir:
    os.makedirs(log_dir, exist_ok=True)

  log_stream = open(log_path, "a", encoding="utf-8", buffering=1)
  sys.stdout = _TeeStream(sys.stdout, log_stream)
  sys.stderr = _TeeStream(sys.stderr, log_stream)
  sys._ga_process_logging_installed = True


_install_process_logging()

##############################################################################
#                                  REVERIE                                   #
##############################################################################

class ReverieServer: 
  def __init__(self, 
               fork_sim_code,
               sim_code):
    # FORKING FROM A PRIOR SIMULATION:
    # <fork_sim_code> indicates the simulation we are forking from. 
    # Interestingly, all simulations must be forked from some initial 
    # simulation, where the first simulation is "hand-crafted".
    self.fork_sim_code = fork_sim_code
    fork_folder = f"{fs_storage}/{self.fork_sim_code}"

    # <sim_code> indicates our current simulation. The first step here is to 
    # copy everything that's in <fork_sim_code>, but edit its 
    # reverie/meta/json's fork variable. 
    self.sim_code = sim_code
    sim_folder = f"{fs_storage}/{self.sim_code}"
    copyanything(fork_folder, sim_folder)

    with open(f"{sim_folder}/reverie/meta.json") as json_file:  
      reverie_meta = json.load(json_file)

    ensure_embedding_metadata_compatible(reverie_meta, sim_folder)

    with open(f"{sim_folder}/reverie/meta.json", "w") as outfile: 
      reverie_meta["fork_sim_code"] = fork_sim_code
      reverie_meta["ai_runtime"] = get_ai_runtime_audit_metadata()
      outfile.write(json.dumps(reverie_meta, indent=2))

    # LOADING REVERIE'S GLOBAL VARIABLES
    # The start datetime of the Reverie: 
    # <start_datetime> is the datetime instance for the start datetime of 
    # the Reverie instance. Once it is set, this is not really meant to 
    # change. It takes a string date in the following example form: 
    # "June 25, 2022"
    # e.g., ...strptime(June 25, 2022, "%B %d, %Y")
    self.start_time = datetime.datetime.strptime(
                        f"{reverie_meta['start_date']}, 00:00:00",  
                        "%B %d, %Y, %H:%M:%S")
    # <curr_time> is the datetime instance that indicates the game's current
    # time. This gets incremented by <sec_per_step> amount everytime the world
    # progresses (that is, everytime curr_env_file is recieved). 
    self.curr_time = datetime.datetime.strptime(reverie_meta['curr_time'], 
                                                "%B %d, %Y, %H:%M:%S")
    # <sec_per_step> denotes the number of seconds in game time that each 
    # step moves foward. 
    self.sec_per_step = reverie_meta['sec_per_step']
    
    # <maze> is the main Maze instance. Note that we pass in the maze_name
    # (e.g., "double_studio") to instantiate Maze. 
    # e.g., Maze("double_studio")
    self.maze = Maze(reverie_meta['maze_name'])
    
    # <step> denotes the number of steps that our game has taken. A step here
    # literally translates to the number of moves our personas made in terms
    # of the number of tiles. 
    self.step = reverie_meta['step']

    # SETTING UP PERSONAS IN REVERIE
    # <personas> is a dictionary that takes the persona's full name as its 
    # keys, and the actual persona instance as its values.
    # This dictionary is meant to keep track of all personas who are part of
    # the Reverie instance. 
    # e.g., ["Isabella Rodriguez"] = Persona("Isabella Rodriguezs")
    self.personas = dict()
    # <personas_tile> is a dictionary that contains the tile location of
    # the personas (!-> NOT px tile, but the actual tile coordinate).
    # The tile take the form of a set, (row, col). 
    # e.g., ["Isabella Rodriguez"] = (58, 39)
    self.personas_tile = dict()
    
    # # <persona_convo_match> is a dictionary that describes which of the two
    # # personas are talking to each other. It takes a key of a persona's full
    # # name, and value of another persona's full name who is talking to the 
    # # original persona. 
    # # e.g., dict["Isabella Rodriguez"] = ["Maria Lopez"]
    # self.persona_convo_match = dict()
    # # <persona_convo> contains the actual content of the conversations. It
    # # takes as keys, a pair of persona names, and val of a string convo. 
    # # Note that the key pairs are *ordered alphabetically*. 
    # # e.g., dict[("Adam Abraham", "Zane Xu")] = "Adam: baba \n Zane:..."
    # self.persona_convo = dict()

    # Loading in all personas. 
    init_env_file = f"{sim_folder}/environment/{str(self.step)}.json"
    init_env = json.load(open(init_env_file))
    for persona_name in reverie_meta['persona_names']: 
      persona_folder = f"{sim_folder}/personas/{persona_name}"
      p_x = init_env[persona_name]["x"]
      p_y = init_env[persona_name]["y"]
      curr_persona = Persona(persona_name, persona_folder)

      self.personas[persona_name] = curr_persona
      self.personas_tile[persona_name] = (p_x, p_y)
      self.maze.tiles[p_y][p_x]["events"].add(curr_persona.scratch
                                              .get_curr_event_and_desc())

    # REVERIE SETTINGS PARAMETERS:  
    # <server_sleep> denotes the amount of time that our while loop rests each
    # cycle; this is to not kill our machine. 
    self.server_sleep = 0.1

    # SIGNALING THE FRONTEND SERVER: 
    # curr_sim_code.json contains the current simulation code, and
    # curr_step.json contains the current step of the simulation. These are 
    # used to communicate the code and step information to the frontend. 
    # Note that step file is removed as soon as the frontend opens up the 
    # simulation. 
    curr_sim_code = dict()
    curr_sim_code["sim_code"] = self.sim_code
    with open(f"{fs_temp_storage}/curr_sim_code.json", "w") as outfile: 
      outfile.write(json.dumps(curr_sim_code, indent=2))
    
    curr_step = dict()
    curr_step["step"] = self.step
    with open(f"{fs_temp_storage}/curr_step.json", "w") as outfile: 
      outfile.write(json.dumps(curr_step, indent=2))

    # BACKGROUND RUN JOB STATE
    self.status_file_path = f"{fs_temp_storage}/simulation_status.json"
    self._job_lock = threading.Lock()
    self._worker_thread = None
    self._active_job = None
    self._write_status_file()


  def _now_iso(self):
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


  def _build_status_snapshot_locked(self):
    current_step = self.step
    current_time = self.curr_time.strftime("%B %d, %Y, %H:%M:%S")

    if self._active_job is None:
      return {
        "simulation": {
          "sim_code": self.sim_code,
          "fork_sim_code": self.fork_sim_code,
        },
        "job": {
          "job_id": None,
          "state": "idle",
          "requested_steps": 0,
          "completed_steps": 0,
          "current_world_step": current_step,
          "started_at": None,
          "updated_at": self._now_iso(),
          "stop_requested": False,
        },
        "progress": {
          "current_persona": None,
          "current_stage": "idle",
          "current_prompt_type": None,
          "current_time": current_time,
        },
        "last_error": None,
      }

    job = dict(self._active_job)
    last_error = job.get("last_error")
    return {
      "simulation": {
        "sim_code": self.sim_code,
        "fork_sim_code": self.fork_sim_code,
      },
      "job": {
        "job_id": job.get("job_id"),
        "state": job.get("state", "idle"),
        "requested_steps": job.get("requested_steps", 0),
        "completed_steps": job.get("completed_steps", 0),
        "current_world_step": job.get("current_world_step", current_step),
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
        "stop_requested": job.get("stop_requested", False),
      },
      "progress": {
        "current_persona": job.get("current_persona"),
        "current_stage": job.get("current_stage", "idle"),
        "current_prompt_type": job.get("current_prompt_type"),
        "current_time": current_time,
      },
      "last_error": last_error,
    }


  def _write_status_file(self, snapshot=None):
    if snapshot is None:
      with self._job_lock:
        snapshot = self._build_status_snapshot_locked()

    tmp_path = self.status_file_path + ".tmp"
    with open(tmp_path, "w") as outfile:
      outfile.write(json.dumps(snapshot, indent=2))
    os.replace(tmp_path, self.status_file_path)


  def _job_is_active_locked(self):
    if self._active_job is None:
      return False
    return self._active_job.get("state") in ("queued", "running", "cancelling")


  def _has_active_run_job(self):
    with self._job_lock:
      return self._job_is_active_locked()


  def _update_active_job(self, job_id=None, **fields):
    with self._job_lock:
      if self._active_job is None:
        return
      if job_id and self._active_job.get("job_id") != job_id:
        return

      changed = False
      for key, value in fields.items():
        if self._active_job.get(key) != value:
          self._active_job[key] = value
          changed = True
      if not changed:
        return
      self._active_job["updated_at"] = self._now_iso()
      snapshot = self._build_status_snapshot_locked()

    self._write_status_file(snapshot)


  def _increment_completed_steps(self, job_id):
    with self._job_lock:
      if self._active_job is None:
        return
      if self._active_job.get("job_id") != job_id:
        return

      self._active_job["completed_steps"] += 1
      self._active_job["current_world_step"] = self.step
      self._active_job["updated_at"] = self._now_iso()
      snapshot = self._build_status_snapshot_locked()

    self._write_status_file(snapshot)


  def _stop_requested_for_job(self, job_id):
    with self._job_lock:
      if self._active_job is None:
        return False
      if self._active_job.get("job_id") != job_id:
        return False
      return bool(self._active_job.get("stop_requested", False))


  def _format_run_status(self):
    with self._job_lock:
      snapshot = self._build_status_snapshot_locked()

    job = snapshot["job"]
    progress = snapshot["progress"]
    simulation = snapshot["simulation"]
    last_error = snapshot["last_error"]

    lines = []
    lines += [f"simulation: {simulation['sim_code']} (forked from {simulation['fork_sim_code']})"]
    lines += [f"state: {job['state']}"]
    lines += [f"step progress: {job['completed_steps']} / {job['requested_steps']}"]
    lines += [f"current world step: {job['current_world_step']}"]
    lines += [f"current time: {progress['current_time']}"]
    lines += [f"current persona: {progress['current_persona'] or '-'}"]
    lines += [f"current stage: {progress['current_stage'] or '-'}"]
    lines += [f"stop requested: {job['stop_requested']}"]
    lines += [f"job id: {job['job_id'] or '-'}"]
    lines += [f"started at: {job['started_at'] or '-'}"]
    lines += [f"updated at: {job['updated_at'] or '-'}"]
    if last_error:
      lines += [f"last error: {last_error.get('type', 'Error')}: {last_error.get('message', '')}"]
    return "\n".join(lines)


  def _start_background_run(self, requested_steps):
    if requested_steps <= 0:
      return False, "Step count must be a positive integer."

    with self._job_lock:
      if self._job_is_active_locked():
        current_job_id = self._active_job.get("job_id")
        return False, (
          "A run job is already active. "
          f"Use 'status' to inspect it or 'stop' to request a graceful stop. "
          f"(job_id={current_job_id})"
        )

      job_id = f"run-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
      self._active_job = {
        "job_id": job_id,
        "state": "queued",
        "requested_steps": requested_steps,
        "completed_steps": 0,
        "current_world_step": self.step,
        "current_persona": None,
        "current_stage": "queued",
        "current_prompt_type": None,
        "started_at": None,
        "updated_at": self._now_iso(),
        "stop_requested": False,
        "last_error": None,
      }
      snapshot = self._build_status_snapshot_locked()

    self._write_status_file(snapshot)
    self._worker_thread = threading.Thread(
      target=self._run_background_job,
      args=(job_id, requested_steps),
      daemon=True,
      name=f"reverie-run-{job_id}",
    )
    self._worker_thread.start()
    return True, (
      f"Started background run job {job_id} for {requested_steps} step(s). "
      "Use 'status' to inspect progress or 'stop' to request a graceful stop."
    )


  def _request_stop_for_active_job(self):
    with self._job_lock:
      if not self._job_is_active_locked():
        return "No active run job."

      self._active_job["state"] = "cancelling"
      self._active_job["stop_requested"] = True
      self._active_job["updated_at"] = self._now_iso()
      snapshot = self._build_status_snapshot_locked()

    self._write_status_file(snapshot)
    return "Stop requested. The active run job will stop after the current step finishes."


  def _run_background_job(self, job_id, requested_steps):
    self._update_active_job(
      job_id,
      state="running",
      started_at=self._now_iso(),
      current_world_step=self.step,
      current_persona=None,
      current_stage="starting",
      current_prompt_type=None,
      last_error=None,
    )
    print(f"[run-job] started job_id={job_id} requested_steps={requested_steps}")

    try:
      self.start_server(requested_steps, job_id=job_id)
      final_state = "stopped" if self._stop_requested_for_job(job_id) else "completed"
      self._update_active_job(
        job_id,
        state=final_state,
        current_world_step=self.step,
        current_persona=None,
        current_stage="idle",
        current_prompt_type=None,
      )
      print(f"[run-job] finished job_id={job_id} state={final_state}")
    except Exception as exc:
      traceback_str = traceback.format_exc()
      traceback.print_exc()
      self._update_active_job(
        job_id,
        state="failed",
        current_world_step=self.step,
        current_persona=None,
        current_stage="failed",
        current_prompt_type=None,
        last_error={
          "type": type(exc).__name__,
          "message": str(exc),
          "traceback": traceback_str,
        },
      )
      print(f"[run-job] failed job_id={job_id} error={type(exc).__name__}: {exc}")


  def save(self): 
    """
    Save all Reverie progress -- this includes Reverie's global state as well
    as all the personas.  

    INPUT
      None
    OUTPUT 
      None
      * Saves all relevant data to the designated memory directory
    """
    # <sim_folder> points to the current simulation folder.
    sim_folder = f"{fs_storage}/{self.sim_code}"

    # Save Reverie meta information.
    reverie_meta = dict() 
    reverie_meta["fork_sim_code"] = self.fork_sim_code
    reverie_meta["start_date"] = self.start_time.strftime("%B %d, %Y")
    reverie_meta["curr_time"] = self.curr_time.strftime("%B %d, %Y, %H:%M:%S")
    reverie_meta["sec_per_step"] = self.sec_per_step
    reverie_meta["maze_name"] = self.maze.maze_name
    reverie_meta["persona_names"] = list(self.personas.keys())
    reverie_meta["step"] = self.step
    reverie_meta.update(get_embedding_runtime_metadata())
    reverie_meta["ai_runtime"] = get_ai_runtime_audit_metadata()
    reverie_meta_f = f"{sim_folder}/reverie/meta.json"
    with open(reverie_meta_f, "w") as outfile: 
      outfile.write(json.dumps(reverie_meta, indent=2))

    # Save the personas.
    for persona_name, persona in self.personas.items(): 
      save_folder = f"{sim_folder}/personas/{persona_name}/bootstrap_memory"
      persona.save(save_folder)
    self._write_status_file()


  def start_path_tester_server(self): 
    """
    Starts the path tester server. This is for generating the spatial memory
    that we need for bootstrapping a persona's state. 

    To use this, you need to open server and enter the path tester mode, and
    open the front-end side of the browser. 

    INPUT 
      None
    OUTPUT 
      None
      * Saves the spatial memory of the test agent to the path_tester_env.json
        of the temp storage. 
    """
    def print_tree(tree): 
      def _print_tree(tree, depth):
        dash = " >" * depth

        if type(tree) == type(list()): 
          if tree:
            print (dash, tree)
          return 

        for key, val in tree.items(): 
          if key: 
            print (dash, key)
          _print_tree(val, depth+1)
      
      _print_tree(tree, 0)

    # <curr_vision> is the vision radius of the test agent. Recommend 8 as 
    # our default. 
    curr_vision = 8
    # <s_mem> is our test spatial memory. 
    s_mem = dict()

    # The main while loop for the test agent. 
    while (True): 
      try: 
        curr_dict = {}
        tester_file = fs_temp_storage + "/path_tester_env.json"
        if check_if_file_exists(tester_file): 
          with open(tester_file) as json_file: 
            curr_dict = json.load(json_file)
            os.remove(tester_file)
          
          # Current camera location
          curr_sts = self.maze.sq_tile_size
          curr_camera = (int(math.ceil(curr_dict["x"]/curr_sts)), 
                         int(math.ceil(curr_dict["y"]/curr_sts))+1)
          curr_tile_det = self.maze.access_tile(curr_camera)

          # Initiating the s_mem
          world = curr_tile_det["world"]
          if curr_tile_det["world"] not in s_mem: 
            s_mem[world] = dict()

          # Iterating throughn the nearby tiles.
          nearby_tiles = self.maze.get_nearby_tiles(curr_camera, curr_vision)
          for i in nearby_tiles: 
            i_det = self.maze.access_tile(i)
            if (curr_tile_det["sector"] == i_det["sector"] 
                and curr_tile_det["arena"] == i_det["arena"]): 
              if i_det["sector"] != "": 
                if i_det["sector"] not in s_mem[world]: 
                  s_mem[world][i_det["sector"]] = dict()
              if i_det["arena"] != "": 
                if i_det["arena"] not in s_mem[world][i_det["sector"]]: 
                  s_mem[world][i_det["sector"]][i_det["arena"]] = list()
              if i_det["game_object"] != "": 
                if (i_det["game_object"] 
                    not in s_mem[world][i_det["sector"]][i_det["arena"]]):
                  s_mem[world][i_det["sector"]][i_det["arena"]] += [
                                                         i_det["game_object"]]

        # Incrementally outputting the s_mem and saving the json file. 
        print ("= " * 15)
        out_file = fs_temp_storage + "/path_tester_out.json"
        with open(out_file, "w") as outfile: 
          outfile.write(json.dumps(s_mem, indent=2))
        print_tree(s_mem)

      except:
        pass

      time.sleep(self.server_sleep * 10)


  def start_server(self, int_counter, job_id=None): 
    """
    The main backend server of Reverie. 
    This function retrieves the environment file from the frontend to 
    understand the state of the world, calls on each personas to make 
    decisions based on the world state, and saves their moves at certain step
    intervals. 
    INPUT
      int_counter: Integer value for the number of steps left for us to take
                   in this iteration. 
    OUTPUT 
      None
    """
    # <sim_folder> points to the current simulation folder.
    sim_folder = f"{fs_storage}/{self.sim_code}"

    # When a persona arrives at a game object, we give a unique event
    # to that object. 
    # e.g., ('double studio[...]:bed', 'is', 'unmade', 'unmade')
    # Later on, before this cycle ends, we need to return that to its 
    # initial state, like this: 
    # e.g., ('double studio[...]:bed', None, None, None)
    # So we need to keep track of which event we added. 
    # <game_obj_cleanup> is used for that. 
    game_obj_cleanup = dict()

    # The main while loop of Reverie. 
    while (True): 
      # Done with this iteration if <int_counter> reaches 0. 
      if int_counter == 0: 
        break
      if job_id and self._stop_requested_for_job(job_id):
        break

      # <curr_env_file> file is the file that our frontend outputs. When the
      # frontend has done its job and moved the personas, then it will put a 
      # new environment file that matches our step count. That's when we run 
      # the content of this for loop. Otherwise, we just wait. 
      curr_env_file = f"{sim_folder}/environment/{self.step}.json"
      env_retrieved = False
      if check_if_file_exists(curr_env_file):
        # If we have an environment file, it means we have a new perception
        # input to our personas. So we first retrieve it.
        try: 
          # Try and save block for robustness of the while loop.
          with open(curr_env_file) as json_file:
            new_env = json.load(json_file)
            env_retrieved = True
        except: 
          pass
      
        if env_retrieved: 
          if job_id:
            self._update_active_job(
              job_id,
              state="running",
              current_world_step=self.step,
              current_persona=None,
              current_stage="step.begin",
              current_prompt_type=None,
            )
          # This is where we go through <game_obj_cleanup> to clean up all 
          # object actions that were used in this cylce. 
          for key, val in game_obj_cleanup.items(): 
            # We turn all object actions to their blank form (with None). 
            self.maze.turn_event_from_tile_idle(key, val)
          # Then we initialize game_obj_cleanup for this cycle. 
          game_obj_cleanup = dict()

          # We first move our personas in the backend environment to match 
          # the frontend environment. 
          for persona_name, persona in self.personas.items(): 
            # <curr_tile> is the tile that the persona was at previously. 
            curr_tile = self.personas_tile[persona_name]
            # <new_tile> is the tile that the persona will move to right now,
            # during this cycle. 
            new_tile = (new_env[persona_name]["x"], 
                        new_env[persona_name]["y"])

            # We actually move the persona on the backend tile map here. 
            self.personas_tile[persona_name] = new_tile
            self.maze.remove_subject_events_from_tile(persona.name, curr_tile)
            self.maze.add_event_from_tile(persona.scratch
                                         .get_curr_event_and_desc(), new_tile)

            # Now, the persona will travel to get to their destination. *Once*
            # the persona gets there, we activate the object action.
            if not persona.scratch.planned_path: 
              # We add that new object action event to the backend tile map. 
              # At its creation, it is stored in the persona's backend. 
              game_obj_cleanup[persona.scratch
                               .get_curr_obj_event_and_desc()] = new_tile
              self.maze.add_event_from_tile(persona.scratch
                                     .get_curr_obj_event_and_desc(), new_tile)
              # We also need to remove the temporary blank action for the 
              # object that is currently taking the action. 
              blank = (persona.scratch.get_curr_obj_event_and_desc()[0], 
                       None, None, None)
              self.maze.remove_event_from_tile(blank, new_tile)

          # Then we need to actually have each of the personas perceive and
          # move. The movement for each of the personas comes in the form of
          # x y coordinates where the persona will move towards. e.g., (50, 34)
          # This is where the core brains of the personas are invoked. 
          movements = {"persona": dict(), 
                       "meta": dict()}
          for persona_name, persona in self.personas.items(): 
            if job_id:
              self._update_active_job(
                job_id,
                state="running",
                current_world_step=self.step,
                current_persona=persona_name,
                current_stage="persona.move",
                current_prompt_type=None,
              )
            # <next_tile> is a x,y coordinate. e.g., (58, 9)
            # <pronunciatio> is an emoji. e.g., "\ud83d\udca4"
            # <description> is a string description of the movement. e.g., 
            #   writing her next novel (editing her novel) 
            #   @ double studio:double studio:common room:sofa
            next_tile, pronunciatio, description = persona.move(
              self.maze, self.personas, self.personas_tile[persona_name], 
              self.curr_time)
            movements["persona"][persona_name] = {}
            movements["persona"][persona_name]["movement"] = next_tile
            movements["persona"][persona_name]["pronunciatio"] = pronunciatio
            movements["persona"][persona_name]["description"] = description
            movements["persona"][persona_name]["chat"] = (persona
                                                          .scratch.chat)

          # Include the meta information about the current stage in the 
          # movements dictionary. 
          movements["meta"]["curr_time"] = (self.curr_time 
                                             .strftime("%B %d, %Y, %H:%M:%S"))

          # We then write the personas' movements to a file that will be sent 
          # to the frontend server. 
          # Example json output: 
          # {"persona": {"Maria Lopez": {"movement": [58, 9]}},
          #  "persona": {"Klaus Mueller": {"movement": [38, 12]}}, 
          #  "meta": {curr_time: <datetime>}}
          if job_id:
            self._update_active_job(
              job_id,
              state="running",
              current_world_step=self.step,
              current_persona=None,
              current_stage="step.commit",
              current_prompt_type=None,
            )
          curr_move_file = f"{sim_folder}/movement/{self.step}.json"
          with open(curr_move_file, "w") as outfile: 
            outfile.write(json.dumps(movements, indent=2))

          # After this cycle, the world takes one step forward, and the 
          # current time moves by <sec_per_step> amount. 
          self.step += 1
          self.curr_time += datetime.timedelta(seconds=self.sec_per_step)

          int_counter -= 1
          if job_id:
            self._increment_completed_steps(job_id)
            self._update_active_job(
              job_id,
              state="running",
              current_world_step=self.step,
              current_persona=None,
              current_stage="waiting_for_frontend_environment",
              current_prompt_type=None,
            )
      elif job_id:
        self._update_active_job(
          job_id,
          state="running" if not self._stop_requested_for_job(job_id) else "cancelling",
          current_world_step=self.step,
          current_persona=None,
          current_stage="waiting_for_frontend_environment",
          current_prompt_type=None,
        )
          
      # Sleep so we don't burn our machines. 
      time.sleep(self.server_sleep)


  def open_server(self): 
    """
    Open up an interactive terminal prompt that lets you run the simulation 
    step by step and probe agent state. 

    INPUT 
      None
    OUTPUT
      None
    """
    print ("Note: The agents in this simulation package are computational")
    print ("constructs powered by generative agents architecture and LLM. We")
    print ("clarify that these agents lack human-like agency, consciousness,")
    print ("and independent decision-making.\n---")

    # <sim_folder> points to the current simulation folder.
    sim_folder = f"{fs_storage}/{self.sim_code}"

    while True: 
      sim_command = input("Enter option: ")
      sim_command = sim_command.strip()
      ret_str = ""
      command_lower = sim_command.lower()

      try: 
        if command_lower in ["status", "jobs"]:
          ret_str += self._format_run_status()

        elif command_lower == "stop":
          ret_str += self._request_stop_for_active_job()

        elif self._has_active_run_job():
          ret_str += (
            "A background run job is active. "
            "Only 'status', 'jobs', and 'stop' are available until it finishes."
          )

        elif command_lower in ["f", "fin", "finish", "save and finish"]: 
          # Finishes the simulation environment and saves the progress. 
          # Example: fin
          self.save()
          break

        elif command_lower == "start path tester mode": 
          # Starts the path tester and removes the currently forked sim files.
          # Note that once you start this mode, you need to exit out of the
          # session and restart in case you want to run something else. 
          shutil.rmtree(sim_folder) 
          self.start_path_tester_server()

        elif command_lower == "exit": 
          # Finishes the simulation environment but does not save the progress
          # and erases all saved data from current simulation. 
          # Example: exit 
          shutil.rmtree(sim_folder) 
          break 

        elif command_lower == "save": 
          # Saves the current simulation progress. 
          # Example: save
          self.save()

        elif sim_command[:3].lower() == "run":
          parts = sim_command.split()
          if len(parts) != 2:
            raise ValueError("Usage: run <positive-step-count>")
          int_count = int(parts[-1])
          _, message = self._start_background_run(int_count)
          ret_str += message

        elif ("print persona schedule" 
              in sim_command[:22].lower()): 
          # Print the decomposed schedule of the persona specified in the 
          # prompt.
          # Example: print persona schedule Isabella Rodriguez
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                      .scratch.get_str_daily_schedule_summary())

        elif ("print all persona schedule" 
              in sim_command[:26].lower()): 
          # Print the decomposed schedule of all personas in the world. 
          # Example: print all persona schedule
          for persona_name, persona in self.personas.items(): 
            ret_str += f"{persona_name}\n"
            ret_str += f"{persona.scratch.get_str_daily_schedule_summary()}\n"
            ret_str += f"---\n"

        elif ("print hourly org persona schedule" 
              in sim_command.lower()): 
          # Print the hourly schedule of the persona specified in the prompt.
          # This one shows the original, non-decomposed version of the 
          # schedule.
          # Ex: print persona schedule Isabella Rodriguez
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                      .scratch.get_str_daily_schedule_hourly_org_summary())

        elif ("print persona current tile" 
              in sim_command[:26].lower()): 
          # Print the x y tile coordinate of the persona specified in the 
          # prompt. 
          # Ex: print persona current tile Isabella Rodriguez
          ret_str += str(self.personas[" ".join(sim_command.split()[-2:])]
                      .scratch.curr_tile)

        elif ("print persona chatting with buffer" 
              in sim_command.lower()): 
          # Print the chatting with buffer of the persona specified in the 
          # prompt.
          # Ex: print persona chatting with buffer Isabella Rodriguez
          curr_persona = self.personas[" ".join(sim_command.split()[-2:])]
          for p_n, count in curr_persona.scratch.chatting_with_buffer.items(): 
            ret_str += f"{p_n}: {count}"

        elif ("print persona associative memory (event)" 
              in sim_command.lower()):
          # Print the associative memory (event) of the persona specified in
          # the prompt
          # Ex: print persona associative memory (event) Isabella Rodriguez
          ret_str += f'{self.personas[" ".join(sim_command.split()[-2:])]}\n'
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                                       .a_mem.get_str_seq_events())

        elif ("print persona associative memory (thought)" 
              in sim_command.lower()): 
          # Print the associative memory (thought) of the persona specified in
          # the prompt
          # Ex: print persona associative memory (thought) Isabella Rodriguez
          ret_str += f'{self.personas[" ".join(sim_command.split()[-2:])]}\n'
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                                       .a_mem.get_str_seq_thoughts())

        elif ("print persona associative memory (chat)" 
              in sim_command.lower()): 
          # Print the associative memory (chat) of the persona specified in
          # the prompt
          # Ex: print persona associative memory (chat) Isabella Rodriguez
          ret_str += f'{self.personas[" ".join(sim_command.split()[-2:])]}\n'
          ret_str += (self.personas[" ".join(sim_command.split()[-2:])]
                                       .a_mem.get_str_seq_chats())

        elif ("print persona spatial memory" 
              in sim_command.lower()): 
          # Print the spatial memory of the persona specified in the prompt
          # Ex: print persona spatial memory Isabella Rodriguez
          self.personas[" ".join(sim_command.split()[-2:])].s_mem.print_tree()

        elif ("print current time" 
              in sim_command[:18].lower()): 
          # Print the current time of the world. 
          # Ex: print current time
          ret_str += f'{self.curr_time.strftime("%B %d, %Y, %H:%M:%S")}\n'
          ret_str += f'steps: {self.step}'

        elif ("print tile event" 
              in sim_command[:16].lower()): 
          # Print the tile events in the tile specified in the prompt 
          # Ex: print tile event 50, 30
          cooordinate = [int(i.strip()) for i in sim_command[16:].split(",")]
          for i in self.maze.access_tile(cooordinate)["events"]: 
            ret_str += f"{i}\n"

        elif ("print tile details" 
              in sim_command.lower()): 
          # Print the tile details of the tile specified in the prompt 
          # Ex: print tile event 50, 30
          cooordinate = [int(i.strip()) for i in sim_command[18:].split(",")]
          for key, val in self.maze.access_tile(cooordinate).items(): 
            ret_str += f"{key}: {val}\n"

        elif ("call -- analysis" 
              in sim_command.lower()): 
          # Starts a stateless chat session with the agent. It does not save 
          # anything to the agent's memory. 
          # Ex: call -- analysis Isabella Rodriguez
          persona_name = sim_command[len("call -- analysis"):].strip() 
          self.personas[persona_name].open_convo_session("analysis")

        elif ("call -- load history" 
              in sim_command.lower()): 
          curr_file = maze_assets_loc + "/" + sim_command[len("call -- load history"):].strip() 
          # call -- load history the_ville/agent_history_init_n3.csv

          rows = read_file_to_list(curr_file, header=True, strip_trail=True)[1]
          clean_whispers = []
          for row in rows: 
            agent_name = row[0].strip() 
            whispers = row[1].split(";")
            whispers = [whisper.strip() for whisper in whispers]
            for whisper in whispers: 
              clean_whispers += [[agent_name, whisper]]

          load_history_via_whisper(self.personas, clean_whispers)

        print (ret_str)

      except:
        traceback.print_exc()
        print ("Error.")
        pass


if __name__ == '__main__':
  # rs = ReverieServer("base_the_ville_isabella_maria_klaus", 
  #                    "July1_the_ville_isabella_maria_klaus-step-3-1")
  # rs = ReverieServer("July1_the_ville_isabella_maria_klaus-step-3-20", 
  #                    "July1_the_ville_isabella_maria_klaus-step-3-21")
  # rs.open_server()

  parser = argparse.ArgumentParser(
      description="Start the Reverie simulation server."
  )
  parser.add_argument(
      "--forked-sim",
      dest="forked_sim",
      help="Existing simulation folder to fork from.",
  )
  parser.add_argument(
      "--new-sim",
      dest="new_sim",
      help="New simulation folder name to create.",
  )
  args = parser.parse_args()

  origin = args.forked_sim or input("Enter the name of the forked simulation: ").strip()
  target = args.new_sim or input("Enter the name of the new simulation: ").strip()

  rs = ReverieServer(origin, target)
  rs.open_server()











































