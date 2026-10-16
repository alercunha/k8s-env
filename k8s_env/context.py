from __future__ import annotations

from functools import cached_property

from k8s_env import k8s
from k8s_env.profile import EnvEntry, Profiles
from k8s_env.utils import validate


class AppContext:
    def __init__(self, ctx_override: str = '', ns_override: str = '') -> None:
        if ns_override:
            validate('namespace', ns_override)
        self.ctx_override = ctx_override
        self.ns_override = ns_override
        self.profiles = Profiles()
        self._kubectl: k8s.KubeCtl | None = None

    @cached_property
    def entry(self) -> EnvEntry:
        # The context override applies to this invocation only; the saved active context is untouched
        if self.ctx_override:
            return self.profiles.by_alias(self.ctx_override)
        return self.profiles.active

    @property
    def env(self):
        return self.entry.env

    @property
    def kubectl(self) -> k8s.KubeCtl:
        if self._kubectl is None:
            env = self.env
            self._kubectl = k8s.get(
                tool=env.tool,
                context=env.context,
                ssh_host=env.ssh_host,
            )
        return self._kubectl

    @property
    def namespace(self) -> str:
        if self.ns_override:
            return self.ns_override
        return self.env.namespace
