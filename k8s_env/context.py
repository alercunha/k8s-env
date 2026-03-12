from __future__ import annotations
import os

from k8s_env import k8s
from k8s_env.service import Env
from k8s_env.utils import ENV_FILE


class AppContext:
    def __init__(self, ns_override: str = '', follow: bool = False) -> None:
        self.ns_override = ns_override
        self.follow = follow
        self._env: Env | None = None
        self._env_path: str | None = None
        self._kubectl: k8s.KubeCtl | None = None

    @property
    def env_path(self) -> str:
        if self._env_path is None:
            self._env_path = self._resolve_env_path()
        return self._env_path

    @property
    def env(self) -> Env:
        if self._env is None:
            path = self.env_path
            if not os.path.isfile(path):
                raise SystemExit('No environment set. Run: k8s-env use')
            self._env = Env.load(path)
        return self._env

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
        if self._env and self._env.namespace:
            return self._env.namespace
        return self.env.namespace

    def set_env(self, env: Env, path: str | None = None) -> None:
        self._env = env
        if path:
            self._env_path = path

    def _resolve_env_path(self) -> str:
        active_link = os.path.join(ENV_FILE, 'active')
        if os.path.isfile(ENV_FILE):
            return ENV_FILE
        if os.path.isdir(ENV_FILE):
            if os.path.islink(active_link):
                return os.path.realpath(active_link)
            raise SystemExit('No active profile. Run: k8s-env profile activate')
        raise SystemExit('No environment set. Run: k8s-env use')
