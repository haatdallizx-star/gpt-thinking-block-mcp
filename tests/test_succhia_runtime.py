import json
import tempfile
import unittest
from pathlib import Path


class FakeClock:
    def __init__(self, value=1_000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class SucchiaRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "secrets.json"
        self.state_path = self.root / "state.json"
        self.config_path.write_text(json.dumps({
            "page_token": "page-secret-000000",
            "mcp_token": "mcp-secret-0000000",
            "max_intensity": 30,
        }))
        self.clock = FakeClock()

    def make_runtime(self):
        from succhia_runtime import SucchiaRuntime
        return SucchiaRuntime(self.config_path, self.state_path, clock=self.clock)

    @staticmethod
    def page_headers(token="page-secret-000000"):
        return {"X-Succhia-Token": token}

    def test_page_api_rejects_missing_or_wrong_token_without_mutating_state(self):
        runtime = self.make_runtime()

        missing = runtime.handle_post(
            "/succhia-api/set", {}, {},
            json.dumps({"vibe_intensity": 12, "duration_sec": 20}).encode(),
        )
        wrong = runtime.handle_post(
            "/succhia-api/set", {}, self.page_headers("wrong"),
            json.dumps({"vibe_intensity": 12, "duration_sec": 20}).encode(),
        )

        self.assertEqual(401, missing[0])
        self.assertEqual(401, wrong[0])
        self.assertEqual(0, runtime.snapshot()["vibe_intensity"])

    def test_mcp_token_is_separate_and_gates_tools_and_calls(self):
        runtime = self.make_runtime()

        self.assertFalse(runtime.mcp_authorized("page-secret-000000"))
        self.assertTrue(runtime.mcp_authorized("mcp-secret-0000000"))
        self.assertEqual([], runtime.mcp_tools(False))
        self.assertEqual({"ok": False, "error": "unauthorized"},
                         runtime.mcp_call("succhia_stop", {}, False))
        names = {tool["name"] for tool in runtime.mcp_tools(True)}
        self.assertEqual(
            {"succhia_set", "succhia_pattern", "succhia_stop", "succhia_status"},
            names,
        )

    def test_set_allows_full_suction_but_keeps_vibration_at_30_and_rejects_ems(self):
        runtime = self.make_runtime()

        code, _, payload = runtime.handle_post(
            "/succhia-api/set", {}, self.page_headers(),
            json.dumps({
                "suck_intensity": 999,
                "vibe_intensity": 99,
                "duration_sec": 20,
            }).encode(),
        )

        self.assertEqual(200, code)
        self.assertTrue(payload["ok"])
        self.assertEqual(100, payload["state"]["suck_intensity"])
        self.assertEqual(30, payload["state"]["vibe_intensity"])

        code, _, payload = runtime.handle_post(
            "/succhia-api/set", {}, self.page_headers(),
            json.dumps({"ems_intensity": 1, "duration_sec": 20}).encode(),
        )
        self.assertEqual(400, code)
        self.assertEqual("ems_locked", payload["error"])
        self.assertEqual(0, runtime.snapshot()["ems_intensity"])

    def test_nonzero_commands_require_a_bounded_lease_and_reject_bool_values(self):
        runtime = self.make_runtime()

        no_lease = runtime.mcp_call("succhia_set", {"vibe": 10}, True)
        bool_value = runtime.mcp_call(
            "succhia_set", {"vibe": True, "duration_sec": 20}, True
        )
        short_lease = runtime.mcp_call(
            "succhia_set", {"vibe": 10, "duration_sec": 1}, True
        )

        self.assertEqual("duration_required", no_lease["error"])
        self.assertEqual("invalid_intensity", bool_value["error"])
        self.assertEqual("duration_out_of_range", short_lease["error"])
        self.assertEqual(0, runtime.snapshot()["vibe_intensity"])

    def test_expired_lease_atomically_clears_channels_and_patterns(self):
        runtime = self.make_runtime()
        result = runtime.mcp_call(
            "succhia_pattern",
            {
                "channel": "suck",
                "type": "wave",
                "low": 4,
                "high": 80,
                "period_sec": 2,
                "duration_sec": 10,
            },
            True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(80, runtime.snapshot()["patterns"]["suck"]["high"])

        self.clock.advance(11)
        expired = runtime.snapshot()

        self.assertEqual(0, expired["suck_intensity"])
        self.assertEqual(0, expired["vibe_intensity"])
        self.assertEqual({"suck": None, "vibe": None, "ems": None}, expired["patterns"])
        self.assertIsNone(expired["expires_at"])

    def test_disconnect_clears_channels_and_patterns(self):
        runtime = self.make_runtime()
        runtime.mcp_call(
            "succhia_pattern",
            {
                "channel": "vibe",
                "type": "pulse",
                "low": 1,
                "high": 12,
                "period_sec": 1,
                "duration_sec": 30,
            },
            True,
        )

        code, _, payload = runtime.handle_post(
            "/succhia-api/disconnect", {}, self.page_headers(), b"{}"
        )

        self.assertEqual(200, code)
        self.assertTrue(payload["ok"])
        self.assertEqual(0, payload["state"]["vibe_intensity"])
        self.assertIsNone(payload["state"]["patterns"]["vibe"])
        self.assertIsNone(payload["state"]["expires_at"])

    def test_restart_never_replays_persisted_nonzero_state(self):
        self.state_path.write_text(json.dumps({
            "suck_intensity": 30,
            "vibe_intensity": 30,
            "ems_intensity": 25,
            "patterns": {
                "suck": {"type": "wave", "low": 1, "high": 30, "period": 1000},
                "vibe": None,
                "ems": {"type": "pulse", "low": 1, "high": 25, "period": 1000},
            },
            "expires_at": self.clock() + 100,
            "updated_at": self.clock(),
        }))

        runtime = self.make_runtime()
        state = runtime.snapshot()

        self.assertEqual(0, state["suck_intensity"])
        self.assertEqual(0, state["vibe_intensity"])
        self.assertEqual(0, state["ems_intensity"])
        self.assertEqual({"suck": None, "vibe": None, "ems": None}, state["patterns"])
        self.assertIsNone(state["expires_at"])

    def test_state_file_remains_owner_only_after_atomic_rewrite(self):
        runtime = self.make_runtime()

        runtime.mcp_call(
            "succhia_set",
            {"vibe": 5, "duration_sec": 3},
            True,
        )

        self.assertEqual(0o600, self.state_path.stat().st_mode & 0o777)

    def test_status_never_contains_tokens(self):
        runtime = self.make_runtime()
        code, _, payload = runtime.handle_get(
            "/succhia-api/status", {}, self.page_headers()
        )

        self.assertEqual(200, code)
        rendered = json.dumps(payload)
        self.assertNotIn("page-secret-000000", rendered)
        self.assertNotIn("mcp-secret-0000000", rendered)


if __name__ == "__main__":
    unittest.main()
