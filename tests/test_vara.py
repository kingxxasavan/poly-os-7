import json
import tempfile
import unittest
from pathlib import Path

from polyos.core import EventBus, Settings
from polyos.mock import MockBackend


class VaraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.backend = MockBackend(Settings(root / "settings.json"), EventBus(), home=root / "home")
        # nothing listens on this port, so the model call fails fast
        self.backend.vara.config.update("http://127.0.0.1:9", "test-model", "sk-secret")

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, text):
        return self.backend.vara.chat(self.backend, text)

    def test_local_actions(self):
        self.assertIn("40%", self.ask("set volume to 40")["reply"])
        self.assertEqual(self.backend.system_status()["volume"]["level"], 40)
        self.assertEqual(self.ask("mute")["reply"], "Muted.")
        self.assertTrue(self.backend.system_status()["volume"]["muted"])
        reply = self.ask("open firefox")["reply"]
        self.assertEqual(reply, "Opening Firefox.")
        self.assertTrue(any(w["appId"] == "firefox-esr.desktop" for w in self.backend.windows()))
        self.assertIn("off", self.ask("turn wifi off")["reply"])
        self.assertFalse(self.backend.system_status()["network"]["wifiEnabled"])
        self.assertTrue(self.ask("what's the time?")["reply"].startswith("It's"))

    def test_model_unreachable_is_a_friendly_error(self):
        res = self.ask("write me a poem about Debian")
        self.assertTrue(res["error"])
        self.assertIn("couldn't reach", res["reply"])
        # errors stay out of what is sent to the model next time
        self.assertEqual([m["role"] for m in res["history"]], ["user", "assistant"])

    def test_key_is_never_returned(self):
        public = self.backend.vara.config.public()
        self.assertNotIn("apiKey", public)
        self.assertTrue(public["hasKey"])
        self.assertNotIn("sk-secret", json.dumps(public))
        self.assertEqual(self.backend.vara.reset(), {"history": []})


if __name__ == "__main__":
    unittest.main()
