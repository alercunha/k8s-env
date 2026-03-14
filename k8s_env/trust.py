from __future__ import annotations
import hashlib
import os

from k8s_env.utils import CMD

TRUST_DIR = os.path.join(os.path.expanduser('~'), '.config', 'k8s-env', 'allowed')


def _path_hash(env_path: str) -> str:
    return hashlib.sha256(os.path.abspath(env_path).encode()).hexdigest()


def _content_hash(file_path: str) -> str:
    with open(os.path.abspath(file_path), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_trusted(env_path: str) -> None:
    marker = os.path.join(TRUST_DIR, _path_hash(env_path))
    if not os.path.isfile(marker):
        raise SystemExit(f'.k8s-env is not trusted. Run: {CMD} allow')
    with open(marker) as f:
        stored = f.read().strip()
    if stored != _content_hash(env_path):
        raise SystemExit(f'.k8s-env has changed since last allowed. Run: {CMD} allow')


def trust(env_path: str) -> None:
    os.makedirs(TRUST_DIR, exist_ok=True)
    marker = os.path.join(TRUST_DIR, _path_hash(env_path))
    with open(marker, 'w') as f:
        f.write(_content_hash(env_path))


def untrust(env_path: str) -> None:
    marker = os.path.join(TRUST_DIR, _path_hash(env_path))
    if os.path.isfile(marker):
        os.remove(marker)
