from __future__ import annotations
import shlex
import subprocess
from abc import ABC, abstractmethod

from k8s_env.utils import SYSTEM_NAMESPACES


class KubeCtl(ABC):
    """Base kubectl abstraction. Subclasses define the command and tool name."""

    def __init__(self, **_):
        pass

    @abstractmethod
    def _base_cmd(self) -> list[str]: ...

    @property
    @abstractmethod
    def tool_name(self) -> str: ...

    @property
    def context(self) -> str:
        return ''

    @property
    def ssh_host(self) -> str:
        return ''

    def run(self, *args: str, timeout: int | None = None) -> str:
        cmd = self._base_cmd() + list(args)
        # kubectl-level timeout; subprocess gets +5s grace for process cleanup
        if timeout:
            cmd += [f'--request-timeout={timeout}s']
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout + 5 if timeout else None,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f'Command timed out: {shlex.join(cmd)}')
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f'Command failed: {shlex.join(cmd)}')
        return result.stdout

    # -- High-level methods --------------------------------------------------

    def get_pods(self, namespace: str, wide: bool = True, timeout: int | None = None) -> str:
        cmd = ['get', 'pods', '-n', namespace]
        if wide:
            cmd += ['-o', 'wide']
        return self.run(*cmd, timeout=timeout)

    def get_namespaces_all(self, timeout: int | None = None) -> str:
        return self.run('get', 'namespaces', timeout=timeout)

    def list_custom_namespaces(self, timeout: int | None = None) -> list[str]:
        out = self.run(
            'get', 'namespaces', '-o',
            'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}',
            timeout=timeout,
        )
        return sorted(
            ns for ns in out.strip().splitlines()
            if ns and ns not in SYSTEM_NAMESPACES
        )


class MicroK8s(KubeCtl):
    def _base_cmd(self) -> list[str]:
        return ['microk8s', 'kubectl']

    @property
    def tool_name(self) -> str:
        return 'microk8s'


class MiniKube(KubeCtl):
    def _base_cmd(self) -> list[str]:
        return ['kubectl', '--context', 'minikube']

    @property
    def tool_name(self) -> str:
        return 'minikube'


class K8sContext(KubeCtl):
    def __init__(self, context: str = '', **_):
        self._context = context

    def _base_cmd(self) -> list[str]:
        return ['kubectl', '--context', self._context]

    @property
    def tool_name(self) -> str:
        return 'k8s'

    @property
    def context(self) -> str:
        return self._context


class SshKubeCtl(KubeCtl):
    """Decorator that routes any KubeCtl through SSH."""

    def __init__(self, inner: KubeCtl, host: str):
        self._inner = inner
        self._host = host

    def _base_cmd(self) -> list[str]:
        return self._inner._base_cmd()

    @property
    def tool_name(self) -> str:
        return self._inner.tool_name

    @property
    def context(self) -> str:
        return self._inner.context

    @property
    def ssh_host(self) -> str:
        return self._host

    def run(self, *args: str, timeout: int | None = None) -> str:
        # Embed kubectl timeout in the remote command string
        cmd_args = list(args)
        if timeout:
            cmd_args += [f'--request-timeout={timeout}s']
        remote_cmd = shlex.join(self._base_cmd() + cmd_args)
        try:
            result = subprocess.run(
                ['ssh', '-n', '--', self._host, remote_cmd],
                capture_output=True, text=True,
                timeout=timeout + 5 if timeout else None,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f'SSH command timed out on {self._host}')
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f'SSH command failed on {self._host}')
        return result.stdout


# -- Factory -----------------------------------------------------------------

_TOOLS: dict[str, type[KubeCtl]] = {
    'microk8s':     MicroK8s,
    'microk8s-ssh': MicroK8s,
    'minikube':     MiniKube,
    'minikube-ssh': MiniKube,
    'k8s':          K8sContext,
}

_CACHE: dict[tuple[str, str, str], KubeCtl] = {}


def get(tool: str, context: str = '', ssh_host: str = '') -> KubeCtl:
    key = (tool, context, ssh_host)
    if key not in _CACHE:
        kubectl = _TOOLS[tool](context=context)
        if ssh_host:
            kubectl = SshKubeCtl(kubectl, ssh_host)
        _CACHE[key] = kubectl
    return _CACHE[key]
