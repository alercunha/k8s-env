from __future__ import annotations

import builtins
import contextlib
import os
from dataclasses import dataclass

from k8s_env.service import Env
from k8s_env.utils import CMD, CONFIG_DIR

_PROFILES_DIR = os.path.join(CONFIG_DIR, 'profiles')
_ACTIVE_LINK = os.path.join(CONFIG_DIR, 'active')


@dataclass
class EnvEntry:
    name: str
    env: Env


def _path(name: str) -> str:
    return os.path.join(_PROFILES_DIR, f'{name}.env')


def _entry(name: str) -> EnvEntry:
    return EnvEntry(name=name, env=Env.load(_path(name)))


def _check_permissions() -> None:
    st = os.stat(CONFIG_DIR)
    if st.st_uid != os.getuid():
        raise SystemExit(f'Refusing to load {CONFIG_DIR}: not owned by you')
    if st.st_mode & 0o077:
        raise SystemExit(f'Refusing to load {CONFIG_DIR}: permissions too open. Run: chmod 700 {CONFIG_DIR}')


class Profiles:
    def __init__(self) -> None:
        self._active: EnvEntry | None = None
        if not os.path.isdir(CONFIG_DIR):
            if os.path.lexists(CONFIG_DIR):
                raise SystemExit(f'{CONFIG_DIR} exists but is not a directory')
            return
        _check_permissions()
        # A dangling link or a non-link file reads as "no active context"
        if os.path.islink(_ACTIVE_LINK) and os.path.isfile(_ACTIVE_LINK):
            self._active = _entry(os.path.basename(os.readlink(_ACTIVE_LINK)).removesuffix('.env'))

    @property
    def active(self) -> EnvEntry:
        if self._active is None:
            raise SystemExit(f'No active context. Run: {CMD} ctx {"set" if self.list() else "add"}')
        return self._active

    @property
    def active_name(self) -> str:
        return self._active.name if self._active else ''

    def by_alias(self, alias: str) -> EnvEntry:
        for entry in self.list():
            if entry.env.alias == alias:
                return entry
        raise SystemExit(f'No context with alias: {alias}')

    def _check_alias_unique(self, env: Env) -> None:
        if not env.alias:
            return
        for entry in self.list():
            if entry.name != env.profile_name and entry.env.alias == env.alias:
                raise SystemExit(f'Alias already in use: {env.alias}')

    def save(self, env: Env) -> None:
        self._check_alias_unique(env)
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
        os.makedirs(_PROFILES_DIR, mode=0o700, exist_ok=True)
        env.save(_path(env.profile_name))

    def add(self, env: Env) -> None:
        # Re-adding an existing context keeps its saved port-forwards and alias
        if os.path.isfile(_path(env.profile_name)):
            existing = Env.load(_path(env.profile_name))
            env.port_forwards = existing.port_forwards
            env.alias = env.alias or existing.alias
        self.save(env)
        self.activate(env.profile_name)

    def list(self) -> builtins.list[EnvEntry]:
        if not os.path.isdir(_PROFILES_DIR):
            return []
        return [_entry(f.removesuffix('.env'))
                for f in sorted(os.listdir(_PROFILES_DIR)) if f.endswith('.env')]

    def activate(self, name: str) -> None:
        tmp = _ACTIVE_LINK + '.tmp'
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp)
        os.symlink(os.path.relpath(_path(name), CONFIG_DIR), tmp)
        os.replace(tmp, _ACTIVE_LINK)
        self._active = _entry(name)

    def delete(self, name: str) -> EnvEntry | None:
        was_active = self.active_name == name
        if was_active:
            os.remove(_ACTIVE_LINK)
            self._active = None
        os.remove(_path(name))
        remaining = self.list()
        if was_active and remaining:
            self.activate(remaining[0].name)
        return self._active if was_active else None
