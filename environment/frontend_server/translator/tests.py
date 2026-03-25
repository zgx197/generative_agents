import json
import os

from django.test import SimpleTestCase


class SimulationStatusViewTests(SimpleTestCase):
  status_file_path = os.path.join("temp_storage", "simulation_status.json")

  def setUp(self):
    self._original_status_file_content = None
    self._had_original_status_file = os.path.exists(self.status_file_path)
    if self._had_original_status_file:
      with open(self.status_file_path, "r") as status_file:
        self._original_status_file_content = status_file.read()
      os.remove(self.status_file_path)

  def tearDown(self):
    if os.path.exists(self.status_file_path):
      os.remove(self.status_file_path)
    if self._had_original_status_file:
      os.makedirs("temp_storage", exist_ok=True)
      with open(self.status_file_path, "w") as status_file:
        status_file.write(self._original_status_file_content)

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
