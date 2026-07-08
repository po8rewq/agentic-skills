import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from agentic.install import main


class InstallTests(unittest.TestCase):
    def run_installer(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            return main(args)

    def test_installs_skills_only_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-skills"
            source.mkdir()
            (source / "demo.md").write_text("skill\n")
            destination = root / "project" / ".ai" / "skills"

            self.assertEqual(self.run_installer(["--source", str(source), str(destination)]), 0)

            self.assertTrue((destination / "demo.md").exists())
            self.assertFalse((root / "project" / ".ai" / "context").exists())
            self.assertFalse((root / "project" / ".ai" / "memory").exists())

    def test_installs_optional_context_and_memory_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills_source = root / "skills"
            context_source = root / "context"
            memory_source = root / "memory"
            for path, filename in (
                (skills_source, "skill.md"),
                (context_source, "repo-map.md"),
                (memory_source, "decisions.md"),
            ):
                path.mkdir()
                (path / filename).write_text(filename + "\n")

            project = root / "project"
            self.assertEqual(
                self.run_installer(
                    [
                        "--source",
                        str(skills_source),
                        "--with-context",
                        "--context-source",
                        str(context_source),
                        "--context-destination",
                        str(project / ".ai" / "context"),
                        "--with-memory",
                        "--memory-source",
                        str(memory_source),
                        "--memory-destination",
                        str(project / ".ai" / "memory"),
                        str(project / ".ai" / "skills"),
                    ]
                ),
                0,
            )

            self.assertTrue((project / ".ai" / "skills" / "skill.md").exists())
            self.assertTrue((project / ".ai" / "context" / "repo-map.md").exists())
            self.assertTrue((project / ".ai" / "memory" / "decisions.md").exists())

    def test_existing_destination_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "demo.md").write_text("skill\n")

            with self.assertRaises(SystemExit):
                self.run_installer(["--source", str(source), str(destination)])

            self.assertEqual(self.run_installer(["--force", "--source", str(source), str(destination)]), 0)
            self.assertTrue((destination / "demo.md").exists())


if __name__ == "__main__":
    unittest.main()
