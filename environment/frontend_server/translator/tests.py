import json
import os

from django.test import SimpleTestCase


class SimulationStatusViewTests(SimpleTestCase):
  status_file_path = os.path.join("temp_storage", "simulation_status.json")
  command_queue_dir = os.path.join("temp_storage", "command_queue")
  command_result_file_path = os.path.join("temp_storage", "command_result.json")

  def setUp(self):
    self._original_status_file_content = None
    self._had_original_status_file = os.path.exists(self.status_file_path)
    if self._had_original_status_file:
      with open(self.status_file_path, "r") as status_file:
        self._original_status_file_content = status_file.read()
      os.remove(self.status_file_path)

    self._original_command_result_content = None
    self._had_original_command_result_file = os.path.exists(self.command_result_file_path)
    if self._had_original_command_result_file:
      with open(self.command_result_file_path, "r") as command_result_file:
        self._original_command_result_content = command_result_file.read()
      os.remove(self.command_result_file_path)

    self._original_command_queue_files = []
    if os.path.isdir(self.command_queue_dir):
      for filename in os.listdir(self.command_queue_dir):
        path = os.path.join(self.command_queue_dir, filename)
        with open(path, "r") as command_file:
          self._original_command_queue_files.append((filename, command_file.read()))
        os.remove(path)

  def tearDown(self):
    if os.path.exists(self.status_file_path):
      os.remove(self.status_file_path)
    if self._had_original_status_file:
      os.makedirs("temp_storage", exist_ok=True)
      with open(self.status_file_path, "w") as status_file:
        status_file.write(self._original_status_file_content)

    if os.path.exists(self.command_result_file_path):
      os.remove(self.command_result_file_path)
    if self._had_original_command_result_file:
      os.makedirs("temp_storage", exist_ok=True)
      with open(self.command_result_file_path, "w") as command_result_file:
        command_result_file.write(self._original_command_result_content)

    if os.path.isdir(self.command_queue_dir):
      for filename in os.listdir(self.command_queue_dir):
        os.remove(os.path.join(self.command_queue_dir, filename))
    if self._original_command_queue_files:
      os.makedirs(self.command_queue_dir, exist_ok=True)
      for filename, content in self._original_command_queue_files:
        with open(os.path.join(self.command_queue_dir, filename), "w") as command_file:
          command_file.write(content)

  def test_simulation_status_returns_idle_payload_when_file_missing(self):
    response = self.client.get("/simulation_status/")

    self.assertEqual(response.status_code, 200)
    payload = response.json()
    self.assertEqual(payload["job"]["state"], "idle")
    self.assertFalse(payload["meta"]["status_file_present"])
    self.assertTrue(payload["meta"]["matches_requested_simulation"])

  def test_simulation_status_returns_status_file_contents(self):
    os.makedirs("temp_storage", exist_ok=True)
    with open(self.status_file_path, "w") as status_file:
      json.dump(
        {
          "simulation": {
            "sim_code": "test-sim",
            "fork_sim_code": "base-sim",
          },
          "job": {
            "job_id": "run-1",
            "state": "running",
            "requested_steps": 10,
            "completed_steps": 3,
            "current_world_step": 42,
            "started_at": "2026-03-25T20:00:00+08:00",
            "updated_at": "2026-03-25T20:01:00+08:00",
            "stop_requested": False,
          },
          "progress": {
            "current_persona": "Isabella Rodriguez",
            "current_stage": "persona.move",
            "current_prompt_type": None,
            "current_time": "February 13, 2023, 08:00:00",
          },
          "last_error": None,
        },
        status_file,
      )

    response = self.client.get("/simulation_status/", {"sim_code": "test-sim"})

    self.assertEqual(response.status_code, 200)
    payload = response.json()
    self.assertEqual(payload["simulation"]["sim_code"], "test-sim")
    self.assertEqual(payload["job"]["state"], "running")
    self.assertEqual(payload["job"]["completed_steps"], 3)
    self.assertEqual(payload["progress"]["current_persona"], "Isabella Rodriguez")
    self.assertTrue(payload["meta"]["status_file_present"])
    self.assertTrue(payload["meta"]["matches_requested_simulation"])

  def test_simulation_command_enqueues_command_file(self):
    response = self.client.post(
      "/simulation_command/",
      data=json.dumps({"sim_code": "test-sim", "command": "run 10"}),
      content_type="application/json",
    )

    self.assertEqual(response.status_code, 200)
    payload = response.json()
    self.assertTrue(payload["accepted"])
    self.assertEqual(payload["command"], "run 10")
    self.assertEqual(payload["sim_code"], "test-sim")
    self.assertTrue(os.path.isdir(self.command_queue_dir))
    queue_files = os.listdir(self.command_queue_dir)
    self.assertEqual(len(queue_files), 1)
    with open(os.path.join(self.command_queue_dir, queue_files[0]), "r") as command_file:
      queued_payload = json.load(command_file)
    self.assertEqual(queued_payload["command"], "run 10")
    self.assertEqual(queued_payload["sim_code"], "test-sim")
    self.assertEqual(queued_payload["source"], "web")

  def test_simulation_command_result_returns_saved_result(self):
    os.makedirs("temp_storage", exist_ok=True)
    with open(self.command_result_file_path, "w") as result_file:
      json.dump(
        {
          "sim_code": "test-sim",
          "command_id": "web-123",
          "command": "status",
          "source": "web",
          "state": "completed",
          "output": "state: idle",
          "error": None,
          "created_at": "2026-03-25T21:00:00+08:00",
          "completed_at": "2026-03-25T21:00:01+08:00",
        },
        result_file,
      )

    response = self.client.get("/simulation_command_result/", {"sim_code": "test-sim"})

    self.assertEqual(response.status_code, 200)
    payload = response.json()
    self.assertEqual(payload["state"], "completed")
    self.assertEqual(payload["command"], "status")
    self.assertEqual(payload["output"], "state: idle")
    self.assertTrue(payload["meta"]["matches_requested_simulation"])
