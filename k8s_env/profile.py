from __future__ import annotations
import os
import shutil

from k8s_env.service import Env
from k8s_env.context import AppContext
from k8s_env.utils import ENV_FILE

PROFILES_DIR = os.path.join(ENV_FILE, 'profiles')
ACTIVE_LINK = os.path.join(ENV_FILE, 'active')


class Profile:
    def __init__(self, name: str, env: Env) -> None:
        self.name = name
        self.env = env
        self.path = os.path.join(PROFILES_DIR, f'{name}.env')

    def activate(self) -> None:
        if not os.path.isfile(self.path):
            raise SystemExit(f'Profile not found: {self.name}')
        _set_active(self.path)

    def delete(self) -> None:
        if not os.path.isfile(self.path):
            raise SystemExit(f'Profile not found: {self.name}')
        # If deleting the active profile, remove the symlink
        if os.path.islink(ACTIVE_LINK) and os.path.realpath(ACTIVE_LINK) == os.path.realpath(self.path):
            os.remove(ACTIVE_LINK)
        os.remove(self.path)
        # If no profiles left, remove the directory structure
        remaining = [f for f in os.listdir(PROFILES_DIR) if f.endswith('.env')]
        if not remaining:
            shutil.rmtree(ENV_FILE)


def list_profiles() -> list[Profile]:
    if not os.path.isdir(PROFILES_DIR):
        return []
    profiles: list[Profile] = []
    for fname in sorted(os.listdir(PROFILES_DIR)):
        if not fname.endswith('.env'):
            continue
        profiles.append(Profile(
            name=fname.removesuffix('.env'),
            env=Env.load(os.path.join(PROFILES_DIR, fname)),
        ))
    return profiles


def active_profile_name() -> str:
    if not os.path.islink(ACTIVE_LINK):
        return ''
    target = os.path.basename(os.readlink(ACTIVE_LINK))
    return target.removesuffix('.env')


def init_profiles(ctx: AppContext) -> str:
    # Initialize multi-profile structure from single .k8s-env file
    if os.path.isdir(ENV_FILE):
        raise SystemExit('Already in multi-profile mode. Use: k8s-env use')
    if not os.path.isfile(ENV_FILE):
        raise SystemExit('No environment set. Run: k8s-env use')
    env = ctx.env
    name = env.profile_name
    os.remove(ENV_FILE)
    _set_active(_write_profile(name, env))
    return name


def save_env(env: Env, ctx: AppContext) -> None:
    # In multi-profile mode, create a new profile and activate it
    if os.path.isdir(ENV_FILE):
        path = _write_profile(env.profile_name, env)
        _set_active(path)
        ctx.set_env(env, path)
        return

    path = ctx.env_path
    if os.path.islink(path):
        raise SystemExit(f'{path} is a symlink — refusing to write')

    env.save(path)
    ctx.set_env(env, path)


def _write_profile(name: str, env: Env) -> str:
    os.makedirs(PROFILES_DIR, exist_ok=True)
    path = os.path.join(PROFILES_DIR, f'{name}.env')
    env.save(path)
    return path


def _set_active(path: str) -> None:
    # Symlink target must be relative to the .k8s-env directory
    rel = os.path.relpath(path, ENV_FILE)
    tmp = ACTIVE_LINK + '.tmp'
    os.symlink(rel, tmp)
    os.replace(tmp, ACTIVE_LINK)
