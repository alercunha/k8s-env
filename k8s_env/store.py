from __future__ import annotations

import builtins
import contextlib
import os

from k8s_env.service import Env
from k8s_env.utils import CMD, CONFIG_DIR

_ENVS_DIR = os.path.join(CONFIG_DIR, 'envs')
_ACTIVE_LINK = os.path.join(CONFIG_DIR, 'active')


def _path(key: str) -> str:
    return os.path.join(_ENVS_DIR, f'{key}.env')


def _check_permissions() -> None:
    st = os.stat(CONFIG_DIR)
    if st.st_uid != os.getuid():
        raise SystemExit(f'Refusing to load {CONFIG_DIR}: not owned by you')
    if st.st_mode & 0o077:
        raise SystemExit(f'Refusing to load {CONFIG_DIR}: permissions too open. Run: chmod 700 {CONFIG_DIR}')


class EnvStore:
    def __init__(self) -> None:
        self._active: Env | None = None
        if not os.path.isdir(CONFIG_DIR):
            if os.path.lexists(CONFIG_DIR):
                raise SystemExit(f'{CONFIG_DIR} exists but is not a directory')
            return
        _check_permissions()
        # A dangling link or a non-link file reads as "no active env"
        if os.path.islink(_ACTIVE_LINK) and os.path.isfile(_ACTIVE_LINK):
            self._active = Env.load(os.path.realpath(_ACTIVE_LINK))

    @property
    def active(self) -> Env:
        if self._active is None:
            raise SystemExit(f'No active env. Run: {CMD} env {"set" if self.list() else "add"}')
        return self._active

    @property
    def active_key(self) -> str:
        return self._active.key if self._active else ''

    def by_name(self, name: str) -> Env:
        for env in self.list():
            if env.name == name:
                return env
        raise SystemExit(f'No env named: {name}')

    def _check_name_unique(self, env: Env) -> None:
        if not env.name:
            return
        for other in self.list():
            if other.key != env.key and other.name == env.name:
                raise SystemExit(f'Name already in use: {env.name}')

    def save(self, env: Env) -> None:
        self._check_name_unique(env)
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
        os.makedirs(_ENVS_DIR, mode=0o700, exist_ok=True)
        env.save(_path(env.key))

    def add(self, env: Env) -> None:
        # Re-adding an existing env keeps its saved port-forwards and name
        if os.path.isfile(_path(env.key)):
            existing = Env.load(_path(env.key))
            env.port_forwards = existing.port_forwards
            env.name = env.name or existing.name
        self.save(env)
        self.activate(env.key)

    def list(self) -> builtins.list[Env]:
        if not os.path.isdir(_ENVS_DIR):
            return []
        return [Env.load(os.path.join(_ENVS_DIR, f))
                for f in sorted(os.listdir(_ENVS_DIR)) if f.endswith('.env')]

    def activate(self, key: str) -> None:
        tmp = _ACTIVE_LINK + '.tmp'
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp)
        os.symlink(os.path.relpath(_path(key), CONFIG_DIR), tmp)
        os.replace(tmp, _ACTIVE_LINK)
        self._active = Env.load(_path(key))

    def delete(self, key: str) -> Env | None:
        was_active = self.active_key == key
        if was_active:
            os.remove(_ACTIVE_LINK)
            self._active = None
        os.remove(_path(key))
        remaining = self.list()
        if was_active and remaining:
            self.activate(remaining[0].key)
        return self._active if was_active else None
