import tempfile
import unittest
from pathlib import Path

from agentic.config import deep_merge, load_config, resolve_model


class ConfigTests(unittest.TestCase):
    def test_deep_merge_preserves_nested_defaults(self):
        self.assertEqual(deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}), {"a": {"b": 3, "c": 2}})

    def test_load_config_resolves_project_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "agentic.yaml").write_text("runtime:\n  artifacts_dir: output\n")
            config = load_config(repo)
            self.assertEqual(config["project"]["name"], repo.name)
            self.assertEqual(config["runtime"]["artifacts_dir"], str(repo / "output"))

    def test_high_risk_routing_escalates_only_sensitive_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory))
            self.assertEqual(resolve_model("implementation", "change payment flow", config, {}), "opus")
            self.assertEqual(resolve_model("requirements", "change payment flow", config, {}), "haiku")

    def test_explicit_model_override_resolves_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory))
            self.assertEqual(resolve_model("review", "rename button", config, {"review": "cheap"}), "haiku")


if __name__ == "__main__":
    unittest.main()

