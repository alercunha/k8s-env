from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from k8s_env import k8s
from k8s_env.utils import is_available, validate

DISCOVERY_TIMEOUT = 10


class Env:
    def __init__(
        self, tool: str, ssh_host: str = '', context: str = '',
        namespace: str = '', port_forwards: dict[str, str] | None = None,
        content_hash: str = '', slug: str = '',
    ) -> None:
        self.tool = tool
        self.ssh_host = ssh_host
        self.context = context
        self.namespace = namespace
        self.port_forwards = port_forwards or {}
        self.content_hash = content_hash
        self.slug = slug

    @classmethod
    def load(cls, path: str) -> Env:
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            raise SystemExit(f'Refusing to load {path}: not a regular file')
        with open(path, 'rb') as f:
            raw = f.read()
        content_hash = hashlib.sha256(raw).hexdigest()
        # Parse key=value pairs; pf.* lines become port_forwards
        fields: dict[str, str] = {}
        port_forwards: dict[str, str] = {}
        for line in raw.decode().splitlines():
            line = line.strip()
            if not line or '=' not in line:
                continue
            key, _, val = line.partition('=')
            if key.startswith('pf.'):
                port_forwards[key] = val
            else:
                fields[key] = val
        env = cls(
            tool=fields.get('tool', ''),
            ssh_host=fields.get('ssh_host', ''),
            context=fields.get('context', ''),
            namespace=fields.get('namespace', ''),
            port_forwards=port_forwards,
            content_hash=content_hash,
            slug=fields.get('slug', ''),
        )
        env.validate()
        return env

    def validate(self) -> None:
        validate('tool', self.tool)
        if self.namespace:
            validate('namespace', self.namespace)
        if self.context:
            validate('context', self.context)
        if self.ssh_host:
            validate('host', self.ssh_host)
        if self.slug:
            validate('slug', self.slug)
        for key, val in self.port_forwards.items():
            if not val.isdigit() or not 1 <= int(val) <= 65535:
                raise ValueError(f"Invalid port forward value for {key}: '{val}'")

    def save(self, path: str) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(f'tool={self.tool}\n')
            f.write(f'ssh_host={self.ssh_host}\n')
            f.write(f'context={self.context}\n')
            f.write(f'namespace={self.namespace}\n')
            f.write(f'slug={self.slug}\n')
            for key, val in self.port_forwards.items():
                f.write(f'{key}={val}\n')

    @property
    def profile_name(self) -> str:
        location = self.ssh_host or self.context or 'local'
        return f'{self.tool}-{location}-{self.namespace}'



# -- Discovery ---------------------------------------------------------------

@dataclass
class NamespaceEntry:
    tool: str
    context: str
    namespace: str
    group: str


def _probe_namespaces(kubectl: k8s.KubeCtl, location: str) -> list[NamespaceEntry]:
    # Derive tool, context, and group label from the kubectl instance
    try:
        namespaces = kubectl.list_custom_namespaces(timeout=DISCOVERY_TIMEOUT)
    except (RuntimeError, OSError):
        return []
    group = f'{kubectl.tool_name} on {location}'
    return [
        NamespaceEntry(tool=kubectl.tool_name, context=kubectl.context, namespace=ns, group=group)
        for ns in namespaces
    ]


def _minikube_running() -> bool:
    try:
        return subprocess.run(
            ['minikube', 'status'], capture_output=True, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _collect_probes(probes: list[tuple]) -> list[NamespaceEntry]:
    # Pre-allocate slots to preserve display order regardless of completion order
    entries: list[list[NamespaceEntry]] = [[] for _ in probes]
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        future_to_idx = {
            pool.submit(_probe_namespaces, *args): i
            for i, args in enumerate(probes)
        }
        for future in as_completed(future_to_idx):
            entries[future_to_idx[future]] = future.result()
    # Flatten into a single ordered list
    return [e for batch in entries for e in batch]


def discover_local() -> list[NamespaceEntry]:
    # Build probe list from available runtimes, then run all in parallel
    probes: list[tuple] = []

    if is_available('microk8s'):
        probes.append((k8s.get('microk8s'), 'local'))

    if is_available('minikube') and _minikube_running():
        probes.append((k8s.get('minikube'), 'local'))

    # Add one probe per kubectl context (skip minikube, handled above)
    if is_available('kubectl'):
        try:
            out = subprocess.run(
                ['kubectl', 'config', 'get-contexts', '-o', 'name'],
                capture_output=True, text=True,
            ).stdout
        except OSError:
            out = ''
        for ctx_name in out.strip().splitlines():
            if ctx_name and ctx_name != 'minikube':
                probes.append((k8s.get('k8s', context=ctx_name), f'context: {ctx_name}'))

    return _collect_probes(probes) if probes else []


def discover_remote(host: str) -> list[NamespaceEntry]:
    validate('host', host)
    return _collect_probes([
        (k8s.get('microk8s', ssh_host=host), host),
        (k8s.get('minikube', ssh_host=host), host),
    ])
