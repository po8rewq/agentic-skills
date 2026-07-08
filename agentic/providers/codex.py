import tempfile
import shlex
from pathlib import Path

from .base import Provider, ProviderResult


class CodexProvider(Provider):
    def run(self, prompt: str, model: str, stage: str) -> ProviderResult:
        with tempfile.NamedTemporaryFile("r+", encoding="utf-8") as output_file:
            argv = shlex.split(self.command) + ["--model", model, "--output-last-message", output_file.name, "-"]
            result = self._execute(argv, prompt)
            final_message = Path(output_file.name).read_text(encoding="utf-8")
            if final_message.strip():
                result.output = final_message
            return result
