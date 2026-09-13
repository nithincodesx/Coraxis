"""
Unit tests for the Coraxis config store, comms layer, and teams module.
Run: python -m unittest discover tests
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Point stores at a temp dir BEFORE importing modules
_TMP = Path(__file__).parent / ".tmp_test_data"
_TMP.mkdir(exist_ok=True)
os.environ.setdefault("CORAXIS_TEST", "1")

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfigStore(unittest.TestCase):
    """Test the persistent JSON config store."""

    def setUp(self):
        import utils.config_store as cs
        self.cs = cs
        cs.reset_cache()
        self._orig = cs.CONFIG_PATH
        cs.CONFIG_PATH = str(_TMP / "test_config.json")
        if os.path.exists(cs.CONFIG_PATH):
            os.remove(cs.CONFIG_PATH)
        cs.reset_cache()

    def tearDown(self):
        self.cs.reset_cache()
        self.cs.CONFIG_PATH = self._orig
        if os.path.exists(self.cs.CONFIG_PATH):
            os.remove(self.cs.CONFIG_PATH)

    def test_defaults_created(self):
        cfg = self.cs.get_config()
        self.assertIn("agents", cfg)
        self.assertIn("researcher", cfg["agents"])
        self.assertEqual(cfg["agents"]["researcher"]["provider"], "groq")

    def test_set_and_get_agent_config(self):
        self.cs.set_agent_config("researcher", {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"})
        ac = self.cs.get_agent_config("researcher")
        self.assertEqual(ac["provider"], "openai")
        self.assertEqual(ac["model"], "gpt-4o-mini")
        self.assertEqual(ac["api_key"], "sk-test")

    def test_custom_agent_crud(self):
        self.cs.set_agent_config("test_agent", {
            "name": "test_agent", "role": "Tester", "goal": "Test things",
            "provider": "gemini", "tools": ["duckduckgo_search"],
        })
        ca = self.cs.get_agent_config("test_agent")
        self.assertIsNotNone(ca)
        self.assertEqual(ca["role"], "Tester")
        self.assertEqual(ca["provider"], "gemini")

        # Update
        self.cs.set_agent_config("test_agent", {"provider": "ollama"})
        ca = self.cs.get_agent_config("test_agent")
        self.assertEqual(ca["provider"], "ollama")
        self.assertEqual(ca["role"], "Tester")  # preserved

        # Delete
        self.assertTrue(self.cs.delete_custom_agent("test_agent"))
        self.assertIsNone(self.cs.get_agent_config("test_agent"))

    def test_cannot_delete_builtin(self):
        self.assertFalse(self.cs.delete_custom_agent("researcher"))

    def test_team_upsert_delete(self):
        team = self.cs.upsert_team({"name": "T1", "agent_names": ["researcher"], "workflow": []})
        self.assertEqual(team["id"], 1)
        team2 = self.cs.upsert_team({"name": "T2", "agent_names": ["analyst"], "workflow": []})
        self.assertEqual(team2["id"], 2)

        # Update
        updated = self.cs.upsert_team({"id": 1, "name": "T1b", "agent_names": ["researcher", "analyst"], "workflow": []})
        self.assertEqual(updated["id"], 1)
        self.assertEqual(updated["name"], "T1b")
        self.assertEqual(len(self.cs.list_teams()), 2)

        self.assertTrue(self.cs.delete_team(1))
        self.assertFalse(self.cs.delete_team(999))

    def test_global_settings_and_key_resolution(self):
        self.cs.set_global_settings(True, "openai", "sk-global")
        gs = self.cs.get_global_settings()
        self.assertTrue(gs["use_global_key"])
        self.assertEqual(gs["global_key"], "sk-global")
        # resolve_api_key should prefer global when enabled
        self.assertEqual(self.cs.resolve_api_key("gemini", ""), "sk-global")
        # explicit key wins
        self.assertEqual(self.cs.resolve_api_key("gemini", "sk-explicit"), "sk-explicit")

    def test_persistence_across_cache_reset(self):
        self.cs.set_agent_config("analyst", {"provider": "gemini", "model": "gemini-1.5-flash"})
        self.cs.reset_cache()
        ac = self.cs.get_agent_config("analyst")
        self.assertEqual(ac["provider"], "gemini")


class TestComms(unittest.TestCase):
    """Test event bus and blackboard."""

    def setUp(self):
        from utils import comms
        comms.reset_state()

    def test_publish_and_get_events(self):
        from utils import comms
        ev = comms.publish("test_event", "agent_a", {"x": 1}, run_id="r1")
        self.assertEqual(ev["type"], "test_event")
        events = comms.get_events(run_id="r1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["x"], 1)

    def test_subscribe_unsubscribe(self):
        from utils import comms
        received = []
        cb = lambda e: received.append(e)
        comms.subscribe(cb)
        comms.publish("sub_test", "a", {})
        self.assertEqual(len(received), 1)
        comms.unsubscribe(cb)
        comms.publish("sub_test2", "a", {})
        self.assertEqual(len(received), 1)

    def test_message_log_and_inbox(self):
        from utils import comms
        comms.send_agent_message("alice", "bob", "hello bob", run_id="r1")
        comms.send_agent_message("bob", "all", "hello everyone", run_id="r1")
        comms.publish("other_type", "alice", {})

        log = comms.get_message_log(run_id="r1")
        self.assertEqual(len(log), 2)

        inbox = comms.read_inbox("bob", run_id="r1")
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["from_agent"], "alice")

    def test_blackboard_write_read(self):
        from utils import comms
        comms.bb_write("findings.q1", "some result", agent="researcher", run_id="r1")
        entry = comms.bb_read("findings.q1")
        self.assertEqual(entry["value"], "some result")
        self.assertEqual(entry["agent"], "researcher")

        self.assertIsNone(comms.bb_read("nonexistent"))

        listing = comms.bb_list(prefix="findings")
        self.assertEqual(len(listing), 1)
        self.assertIn("value_preview", listing[0])


class TestTeamsModule(unittest.TestCase):
    """Test teams module tool resolution (no LLM calls)."""

    def test_tool_factories_cover_registry(self):
        import teams
        import utils.config_store as cs
        for tool in cs.TOOL_REGISTRY:
            self.assertIn(tool["id"], teams.TOOL_FACTORIES, f"Missing factory for {tool['id']}")


if __name__ == "__main__":
    unittest.main()
