import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentic.forges.gitea import GiteaForge


class GiteaForgeTests(unittest.TestCase):
    def test_repo_slug_parses_ssh_remote_with_port(self):
        with tempfile.TemporaryDirectory() as directory:
            forge = GiteaForge(Path(directory), [], [])
            with patch.object(GiteaForge, "_git", return_value="ssh://adrien@192.168.6.212:4022/adrien/job-search.git"):
                self.assertEqual(forge._repo_slug(), "adrien/job-search")

    def test_create_pr_requires_pushed_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            forge = GiteaForge(root, [], [])
            body = root / "pr-body.md"
            body.write_text("Body", encoding="utf-8")

            def fake_git(*args):
                if args == ("branch", "--show-current"):
                    return "ai/example"
                if args == ("ls-remote", "--heads", "origin", "ai/example"):
                    return ""
                raise AssertionError(args)

            with patch.object(GiteaForge, "_git", side_effect=fake_git):
                with self.assertRaisesRegex(RuntimeError, "not pushed to origin"):
                    forge.create_pr("Title", body, "main")

    def test_create_pr_uses_explicit_repo_and_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            forge = GiteaForge(root, [], [])
            body = root / "pr-body.md"
            body.write_text("Body", encoding="utf-8")

            def fake_git(*args):
                if args == ("branch", "--show-current"):
                    return "ai/example"
                if args == ("ls-remote", "--heads", "origin", "ai/example"):
                    return "abc123\trefs/heads/ai/example"
                if args == ("remote", "get-url", "origin"):
                    return "ssh://adrien@192.168.6.212:4022/adrien/job-search.git"
                raise AssertionError(args)

            with patch.object(GiteaForge, "_git", side_effect=fake_git):
                with patch.object(GiteaForge, "_run", return_value="https://gitea/pulls/1") as run:
                    url = forge.create_pr("Title", body, "main")

            self.assertEqual(url, "https://gitea/pulls/1")
            run.assert_called_once_with(
                "pulls",
                "create",
                "--repo",
                "adrien/job-search",
                "--head",
                "ai/example",
                "--title",
                "Title",
                "--description",
                "Body",
                "--base",
                "main",
            )


if __name__ == "__main__":
    unittest.main()
