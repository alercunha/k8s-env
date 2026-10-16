from __future__ import annotations

from functools import cached_property

from k8s_env import k8s
from k8s_env.service import Env
from k8s_env.store import EnvStore
from k8s_env.utils import validate


class App:
    def __init__(self, env_override: str = '', ns_override: str = '') -> None:
        if ns_override:
            validate('namespace', ns_override)
        self.env_override = env_override
        self.ns_override = ns_override
        self.store = EnvStore()

    @cached_property
    def env(self) -> Env:
        # The env override applies to this invocation only; the saved active env is untouched
        if self.env_override:
            return self.store.by_name(self.env_override)
        return self.store.active

    @property
    def kubectl(self) -> k8s.KubeCtl:
        return k8s.get(tool=self.env.tool, context=self.env.context, ssh_host=self.env.ssh_host)

    @property
    def namespace(self) -> str:
        return self.ns_override or self.env.namespace
