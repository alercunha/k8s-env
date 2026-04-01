from __future__ import annotations

from k8s_env import k8s
from k8s_env.profile import Profiles
from k8s_env.trust import check_trusted
from k8s_env.utils import validate


class AppContext:
    def __init__(self, ns_override: str = '', follow: bool = False, new_token: bool = False, tail: int = 20) -> None:
        if ns_override:
            validate('namespace', ns_override)
        self.ns_override = ns_override
        self.follow = follow
        self.new_token = new_token
        self.tail = tail
        self.profiles = Profiles()
        self._trusted = False
        self._kubectl: k8s.KubeCtl | None = None

    @property
    def env(self):
        if not self._trusted:
            entry = self.profiles.active
            check_trusted(entry.path, entry.env.content_hash)
            self._trusted = True
        return self.profiles.active.env

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
