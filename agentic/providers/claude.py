import shlex

from .base import Provider, ProviderResult


class ClaudeProvider(Provider):
    def run(self, prompt: str, model: str, stage: str) -> ProviderResult:
        argv = shlex.split(self.command) + ["--print", "--model", model]
        return self._execute(argv, prompt)

