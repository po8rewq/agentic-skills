import tempfile
import unittest
from pathlib import Path

from agentic.config import deep_merge, load_config, resolve_model, review_passes_for_risk


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

    def test_risk_level_routes_implementation_model(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory))
            config["models"]["aliases"]["medium"] = "sonnet"
            config["risk_routing"]["implementation_models"]["low"] = "medium"
            self.assertEqual(resolve_model("implementation", "rename button", config, {}, "low"), "sonnet")
            self.assertEqual(resolve_model("implementation", "rename button", config, {}, "high"), "opus")

    def test_explicit_model_override_resolves_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory))
            self.assertEqual(resolve_model("review", "rename button", config, {"review": "cheap"}), "haiku")
            self.assertEqual(resolve_model("implementation", "payment flow", config, {"implementation": "cheap"}), "haiku")

    def test_review_passes_follow_risk_level(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory))
            self.assertEqual(review_passes_for_risk(config, "low"), ["correctness", "tests"])
            self.assertIn("security", review_passes_for_risk(config, "high"))

    def test_invalid_risk_routing_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "agentic.yaml").write_text("risk_routing:\n  default_level: extreme\n")
            with self.assertRaisesRegex(ValueError, "default_level"):
                load_config(repo)


if __name__ == "__main__":
    unittest.main()
