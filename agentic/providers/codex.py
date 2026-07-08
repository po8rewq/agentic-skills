import shlex

from .base import Provider, ProviderResult


class CodexProvider(Provider):
    def run(self, prompt: str, model: str, stage: str) -> ProviderResult:
        argv = shlex.split(self.command) + ["--model", model, "-"]
        return self._execute(argv, prompt)

