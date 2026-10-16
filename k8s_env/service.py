from __future__ import annotations

import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from k8s_env import k8s
from k8s_env.utils import is_available, validate

DISCOVERY_TIMEOUT = 10


class Env:
    def __init__(
        self, tool: str, ssh_host: str = '', context: str = '',
        namespace: str = '', port_forwards: dict[str, str] | None = None,
        name: str = '',
    ) -> None:
        self.tool = tool
        self.ssh_host = ssh_host
        self.context = context
        self.namespace = namespace
        self.port_forwards = port_forwards or {}
        self.name = name

    @classmethod
    def load(cls, path: str) -> Env:
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            raise SystemExit(f'Refusing to load {path}: not a regular file')
        with open(path, encoding='utf-8') as f:
            raw = f.read()
        # Parse key=value pairs; pf.* lines become port_forwards
        fields: dict[str, str] = {}
        port_forwards: dict[str, str] = {}
        for line in raw.splitlines():
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
            name=fields.get('name', ''),
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
        if self.name:
            validate('name', self.name)
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
            f.write(f'name={self.name}\n')
            for key, val in self.port_forwards.items():
                f.write(f'{key}={val}\n')

    @property
    def key(self) -> str:
        # Storage id (filename); stable regardless of the user-facing name
        return f'{self.tool}-{self.ssh_host or self.context or "local"}-{self.namespace}'

    @property
    def label(self) -> str:
        return self.name or self.key

    @property
    def target(self) -> str:
        # Where kubectl runs: 'k8s @ <kubectl context>', 'microk8s @ local', 'minikube @ <host> (ssh)'
        location = f'{self.ssh_host} (ssh)' if self.ssh_host else self.context or 'local'
        return f'{self.tool} @ {location}'

    def describe(self, namespace: str = '') -> str:
        return f'{self.target} / {namespace or self.namespace}'



# -- Discovery ---------------------------------------------------------------

def _probe_namespaces(kubectl: k8s.KubeCtl) -> list[Env]:
    try:
        namespaces = kubectl.list_custom_namespaces(timeout=DISCOVERY_TIMEOUT)
    except (RuntimeError, OSError):
        return []
    return [
        Env(tool=kubectl.tool_name, ssh_host=kubectl.ssh_host, context=kubectl.context, namespace=ns)
        for ns in namespaces
    ]


def _minikube_running() -> bool:
    try:
        return subprocess.run(
            ['minikube', 'status'], capture_output=True, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _collect_probes(probes: list[k8s.KubeCtl]) -> list[Env]:
    # Pre-allocate slots to preserve display order regardless of completion order
    entries: list[list[Env]] = [[] for _ in probes]
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        future_to_idx = {
            pool.submit(_probe_namespaces, kubectl): i
            for i, kubectl in enumerate(probes)
        }
        for future in as_completed(future_to_idx):
            entries[future_to_idx[future]] = future.result()
    # Flatten into a single ordered list
    return [e for batch in entries for e in batch]


def discover_local() -> list[Env]:
    # Build probe list from available runtimes, then run all in parallel
    probes: list[k8s.KubeCtl] = []

    if is_available('microk8s'):
        probes.append(k8s.get('microk8s'))

    if is_available('minikube') and _minikube_running():
        probes.append(k8s.get('minikube'))

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
                probes.append(k8s.get('k8s', context=ctx_name))

    return _collect_probes(probes) if probes else []


def discover_remote(host: str) -> list[Env]:
    validate('host', host)
    return _collect_probes([
        k8s.get('microk8s', ssh_host=host),
        k8s.get('minikube', ssh_host=host),
    ])
