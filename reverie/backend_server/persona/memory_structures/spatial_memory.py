"""
Author: Joon Sung Park (joonspk@stanford.edu)

File: spatial_memory.py
Description: Defines the MemoryTree class that serves as the agents' spatial
memory that aids in grounding their behavior in the game world. 
"""
import json
import sys
sys.path.append('../../')

from utils import *
from global_methods import *

class MemoryTree: 
  def __init__(self, f_saved): 
    self.tree = {}
    if check_if_file_exists(f_saved): 
      self.tree = json.load(open(f_saved))


  def _candidate_parts(self, raw_value):
    if raw_value is None:
      return []
    text = str(raw_value).strip()
    if not text:
      return []

    candidates = [text]
    for separator in ["------", "->", "|", "/", ","]:
      next_candidates = []
      for candidate in candidates:
        next_candidates.append(candidate)
        if separator in candidate:
          next_candidates.extend(
            part.strip() for part in candidate.split(separator) if part.strip()
          )
      candidates = next_candidates

    deduped = []
    seen = set()
    for candidate in candidates:
      normalized = candidate.strip()
      lowered = normalized.lower()
      if normalized and lowered not in seen:
        deduped.append(normalized)
        seen.add(lowered)
    return deduped


  def _match_sector_name(self, curr_world, raw_sector, raw_arena=None):
    world_tree = self.tree.get(curr_world, {})
    if not isinstance(world_tree, dict):
      return None

    if raw_arena:
      arena_candidates = self._candidate_parts(raw_arena)
      for candidate in self._candidate_parts(raw_sector):
        for sector_name, sector_tree in world_tree.items():
          if sector_name.lower() != candidate.lower():
            continue
          if not isinstance(sector_tree, dict):
            continue
          for arena_name in sector_tree.keys():
            if any(arena_name.lower() == arena_candidate.lower()
                   for arena_candidate in arena_candidates):
              return sector_name

    for candidate in self._candidate_parts(raw_sector):
      if candidate in world_tree:
        return candidate
      for sector_name in world_tree.keys():
        if sector_name.lower() == candidate.lower():
          return sector_name

    if raw_arena:
      for arena_candidate in self._candidate_parts(raw_arena):
        for sector_name, sector_tree in world_tree.items():
          if not isinstance(sector_tree, dict):
            continue
          for arena_name in sector_tree.keys():
            if arena_name.lower() == arena_candidate.lower():
              return sector_name
    return None


  def _match_arena_name(self, curr_world, curr_sector, raw_arena):
    sector_tree = self.tree.get(curr_world, {}).get(curr_sector, {})
    if not isinstance(sector_tree, dict):
      return None

    for candidate in self._candidate_parts(raw_arena):
      if candidate in sector_tree:
        return candidate
      for arena_name in sector_tree.keys():
        if arena_name.lower() == candidate.lower():
          return arena_name
    return None


  def _resolve_sector_parts(self, sector):
    parts = [part.strip() for part in str(sector).split(":") if part.strip()]
    if len(parts) < 2:
      raise ValueError(f"Invalid sector address: {sector}")

    curr_world = parts[0]
    raw_sector = ":".join(parts[1:])
    curr_sector = self._match_sector_name(curr_world, raw_sector)
    if curr_sector is None:
      curr_sector = raw_sector
    return curr_world, curr_sector


  def _resolve_arena_parts(self, arena):
    parts = [part.strip() for part in str(arena).split(":") if part.strip()]
    if len(parts) < 3:
      raise ValueError(f"Invalid arena address: {arena}")

    curr_world = parts[0]
    raw_arena = parts[-1]
    raw_sector = ":".join(parts[1:-1])
    curr_sector = self._match_sector_name(curr_world, raw_sector, raw_arena)

    if curr_sector is None:
      # Fall back to a tree-guided split when the sector itself contains colons.
      world_tree = self.tree.get(curr_world, {})
      if isinstance(world_tree, dict):
        for split_index in range(2, len(parts)):
          sector_candidate = ":".join(parts[1:split_index])
          arena_candidate = ":".join(parts[split_index:])
          matched_sector = self._match_sector_name(curr_world, sector_candidate, arena_candidate)
          if matched_sector is None:
            continue
          matched_arena = self._match_arena_name(curr_world, matched_sector, arena_candidate)
          if matched_arena is not None:
            return curr_world, matched_sector, matched_arena

      curr_sector = raw_sector

    curr_arena = self._match_arena_name(curr_world, curr_sector, raw_arena)
    if curr_arena is None:
      curr_arena = raw_arena

    return curr_world, curr_sector, curr_arena


  def print_tree(self): 
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
    
    _print_tree(self.tree, 0)
    

  def save(self, out_json):
    with open(out_json, "w") as outfile:
      json.dump(self.tree, outfile) 



  def get_str_accessible_sectors(self, curr_world): 
    """
    Returns a summary string of all the arenas that the persona can access 
    within the current sector. 

    Note that there are places a given persona cannot enter. This information
    is provided in the persona sheet. We account for this in this function. 

    INPUT
      None
    OUTPUT 
      A summary string of all the arenas that the persona can access. 
    EXAMPLE STR OUTPUT
      "bedroom, kitchen, dining room, office, bathroom"
    """
    x = ", ".join(list(self.tree[curr_world].keys()))
    return x


  def get_str_accessible_sector_arenas(self, sector): 
    """
    Returns a summary string of all the arenas that the persona can access 
    within the current sector. 

    Note that there are places a given persona cannot enter. This information
    is provided in the persona sheet. We account for this in this function. 

    INPUT
      None
    OUTPUT 
      A summary string of all the arenas that the persona can access. 
    EXAMPLE STR OUTPUT
      "bedroom, kitchen, dining room, office, bathroom"
    """
    try:
      curr_world, curr_sector = self._resolve_sector_parts(sector)
    except ValueError:
      return ""
    if not curr_sector: 
      return ""
    try:
      x = ", ".join(list(self.tree[curr_world][curr_sector].keys()))
    except KeyError:
      return ""
    return x


  def get_str_accessible_arena_game_objects(self, arena):
    """
    Get a str list of all accessible game objects that are in the arena. If 
    temp_address is specified, we return the objects that are available in
    that arena, and if not, we return the objects that are in the arena our
    persona is currently in. 

    INPUT
      temp_address: optional arena address
    OUTPUT 
      str list of all accessible game objects in the gmae arena. 
    EXAMPLE STR OUTPUT
      "phone, charger, bed, nightstand"
    """
    try:
      curr_world, curr_sector, curr_arena = self._resolve_arena_parts(arena)
    except ValueError:
      return ""

    if not curr_arena: 
      return ""

    try:
      x = ", ".join(list(self.tree[curr_world][curr_sector][curr_arena]))
    except KeyError:
      try:
        x = ", ".join(list(self.tree[curr_world][curr_sector][curr_arena.lower()]))
      except KeyError:
        return ""
    return x


if __name__ == '__main__':
  x = f"../../../../environment/frontend_server/storage/the_ville_base_LinFamily/personas/Eddy Lin/bootstrap_memory/spatial_memory.json"
  x = MemoryTree(x)
  x.print_tree()

  print (x.get_str_accessible_sector_arenas("dolores double studio:double studio"))




