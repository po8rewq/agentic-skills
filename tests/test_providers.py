import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentic.providers.base import ProviderResult
from agentic.providers.codex import CodexProvider


class CodexProviderTests(unittest.TestCase):
    def test_codex_provider_prefers_output_last_message_file(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            provider = CodexProvider("codex exec", repo)
            final_output = "```yaml agentic\nstatus: ready\nconfidence: 0.9\n```\n\n# Summary\n"

            def fake_execute(argv, prompt):
                output_index = argv.index("--output-last-message") + 1
                Path(argv[output_index]).write_text(final_output, encoding="utf-8")
                return ProviderResult(
                    output="progress noise\n",
                    command=argv,
                    returncode=0,
                    stderr="",
                )

            with patch.object(CodexProvider, "_execute", side_effect=fake_execute):
                result = provider.run("prompt", "gpt-5.4-mini", "requirements")

            self.assertEqual(result.output, final_output)
            self.assertIn("--output-last-message", result.command)


if __name__ == "__main__":
    unittest.main()
