from __future__ import annotations
import os
import shutil
from dataclasses import dataclass

from k8s_env.service import Env
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
                raise SystemExit(f'No active profile. Run: {CMD} profile activate')
            raise SystemExit(f'No environment set. Run: {CMD} use')
        return self._active

    @property
    def active_name(self) -> str:
        return self.active.name

    @property
    def multi(self) -> bool:
        return self._multi

    def save(self, env: Env) -> EnvEntry:
        if self.multi:
            path = self._write_profile(env.profile_name, env)
            self._set_active(path)
            entry = EnvEntry(name=env.profile_name, env=env, path=path)
        else:
            if os.path.islink(ENV_FILE):
                raise SystemExit(f'{ENV_FILE} is a symlink — refusing to write')
            env.save(ENV_FILE)
            entry = EnvEntry(name=env.profile_name, env=env, path=ENV_FILE)
        self._active = entry
        return entry

    def init_multi(self) -> EnvEntry:
        if self.multi:
            raise SystemExit(f'Already in multi-profile mode. Use: {CMD} use')
        env = self.active.env
        name = env.profile_name
        os.remove(ENV_FILE)
        path = self._write_profile(name, env)
        self._set_active(path)
        entry = EnvEntry(name=name, env=env, path=path)
        self._multi = True
        self._active = entry
        return entry

    def list(self) -> list[EnvEntry]:
        if not os.path.isdir(_PROFILES_DIR):
            return []
        entries: list[EnvEntry] = []
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
            raise SystemExit(f'Profile not found: {name}')
        self._set_active(path)
        self._active = EnvEntry(name=name, env=Env.load(path), path=path)

    def delete(self, name: str) -> None:
        path = os.path.join(_PROFILES_DIR, f'{name}.env')
        if not os.path.isfile(path):
            raise SystemExit(f'Profile not found: {name}')
        if self._active and os.path.realpath(self._active.path) == os.path.realpath(path):
            os.remove(_ACTIVE_LINK)
            self._active = None
        os.remove(path)
        remaining = [f for f in os.listdir(_PROFILES_DIR) if f.endswith('.env')]
        if not remaining:
            shutil.rmtree(ENV_FILE)
            self._multi = False

    def _write_profile(self, name: str, env: Env) -> str:
        os.makedirs(_PROFILES_DIR, exist_ok=True)
        path = os.path.join(_PROFILES_DIR, f'{name}.env')
        env.save(path)
        return path

    def _set_active(self, path: str) -> None:
        rel = os.path.relpath(path, ENV_FILE)
        tmp = _ACTIVE_LINK + '.tmp'
        os.symlink(rel, tmp)
        os.replace(tmp, _ACTIVE_LINK)
