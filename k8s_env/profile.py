from __future__ import annotations

import builtins
import os
import shutil
from dataclasses import dataclass

from k8s_env.service import Env
from k8s_env.trust import trust
from k8s_env.utils import CMD, ENV_FILE

_PROFILES_DIR = os.path.join(ENV_FILE, 'profiles')
_ACTIVE_LINK = os.path.join(ENV_FILE, 'active')


@dataclass
class EnvEntry:
    name: str
    env: Env
    path: str


class Profiles:
    def __init__(self) -> None:
        self._multi = False
        self._active: EnvEntry | None = None
        if os.path.isdir(ENV_FILE):
            self._multi = True
            if os.path.islink(_ACTIVE_LINK):
                resolved = os.path.realpath(_ACTIVE_LINK)
                env_dir = os.path.realpath(ENV_FILE)
                if not resolved.startswith(env_dir + os.sep):
                    raise SystemExit('Refusing to load: active symlink points outside .k8s-env/')
                name = os.path.basename(resolved).removesuffix('.env')
                self._active = EnvEntry(name=name, env=Env.load(resolved), path=resolved)
        elif os.path.isfile(ENV_FILE):
            env = Env.load(ENV_FILE)
            self._active = EnvEntry(name=env.profile_name, env=env, path=ENV_FILE)

    @property
    def active(self) -> EnvEntry:
        if self._active is None:
            if self._multi:
                raise SystemExit(f'No active context. Run: {CMD} ctx set')
            raise SystemExit(f'No environment set. Run: {CMD} ctx add')
        return self._active

    @property
    def active_name(self) -> str:
        return self._active.name if self._active else ''

    @property
    def multi(self) -> bool:
        return self._multi

    def save(self, env: Env) -> EnvEntry:
        if not self._multi and self._active and self._active.name != env.profile_name:
            self._convert_to_multi()
        if self._multi:
            path = self._write_profile(env.profile_name, env)
            self._symlink_active(path)
            entry = EnvEntry(name=env.profile_name, env=env, path=path)
        else:
            if os.path.islink(ENV_FILE):
                raise SystemExit(f'{ENV_FILE} is a symlink — refusing to write')
            env.save(ENV_FILE)
            entry = EnvEntry(name=env.profile_name, env=env, path=ENV_FILE)
        trust(entry.path)
        self._active = entry
        return entry

    def _convert_to_multi(self) -> None:
        current_env = self._active.env
        os.remove(ENV_FILE)
        current_path = self._write_profile(current_env.profile_name, current_env)
        trust(current_path)
        self._multi = True

    def list(self) -> builtins.list[EnvEntry]:
        if not self._multi:
            return [self._active] if self._active else []
        if not os.path.isdir(_PROFILES_DIR):
            return []
        entries: builtins.list[EnvEntry] = []
        for fname in sorted(os.listdir(_PROFILES_DIR)):
            if not fname.endswith('.env'):
                continue
            path = os.path.join(_PROFILES_DIR, fname)
            entries.append(EnvEntry(
                name=fname.removesuffix('.env'),
                env=Env.load(path),
                path=path,
            ))
        return entries

    def activate(self, name: str) -> None:
        path = os.path.join(_PROFILES_DIR, f'{name}.env')
        if not os.path.isfile(path):
            raise SystemExit(f'Context not found: {name}')
        self._symlink_active(path)
        trust(path)
        self._active = EnvEntry(name=name, env=Env.load(path), path=path)

    def delete(self, name: str) -> EnvEntry | None:
        if not self._multi:
            if not self._active or self._active.name != name:
                raise SystemExit(f'Context not found: {name}')
            os.remove(ENV_FILE)
            self._active = None
            return None
        path = os.path.join(_PROFILES_DIR, f'{name}.env')
        if not os.path.isfile(path):
            raise SystemExit(f'Context not found: {name}')
        was_active = self._active and self._active.name == name
        if was_active:
            os.remove(_ACTIVE_LINK)
            self._active = None
        os.remove(path)
        remaining = sorted(f for f in os.listdir(_PROFILES_DIR) if f.endswith('.env'))
        if not remaining:
            shutil.rmtree(ENV_FILE)
            self._multi = False
        elif was_active:
            self.activate(remaining[0].removesuffix('.env'))
        return self._active if was_active else None

    def _write_profile(self, name: str, env: Env) -> str:
        os.makedirs(_PROFILES_DIR, exist_ok=True)
        path = os.path.join(_PROFILES_DIR, f'{name}.env')
        env.save(path)
        return path

    def _symlink_active(self, path: str) -> None:
        rel = os.path.relpath(path, ENV_FILE)
        tmp = _ACTIVE_LINK + '.tmp'
        os.symlink(rel, tmp)
        os.replace(tmp, _ACTIVE_LINK)
