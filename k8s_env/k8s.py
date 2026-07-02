from __future__ import annotations

import json
import os
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
        except subprocess.TimeoutExpired as err:
            raise RuntimeError(f'Command timed out: {shlex.join(cmd)}') from err
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f'Command failed: {shlex.join(cmd)}')
        return result.stdout

    def stream(self, *args: str) -> None:
        # Run with inherited stdout/stderr (not captured) — used for follow mode
        cmd = self._base_cmd() + list(args)
        subprocess.run(cmd)

    # -- High-level methods --------------------------------------------------

    def get_pods(self, namespace: str, wide: bool = True, timeout: int | None = None) -> str:
        cmd = ['get', 'pods', '-n', namespace]
        if wide:
            cmd += ['-o', 'wide']
        return self.run(*cmd, timeout=timeout)

    def list_pods(self, namespace: str, timeout: int | None = None) -> list[str]:
        out = self.run(
            'get', 'pods', '-n', namespace, '-o',
            'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}',
            timeout=timeout,
        )
        return [p for p in out.strip().splitlines() if p]

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

    def get_services(self, namespace: str, timeout: int | None = None) -> str:
        return self.run('get', 'services', '-n', namespace, timeout=timeout)

    def get_secrets(self, namespace: str, timeout: int | None = None) -> str:
        return self.run('get', 'secrets', '-n', namespace, timeout=timeout)

    def get_cronjobs(self, namespace: str, timeout: int | None = None) -> str:
        return self.run('get', 'cronjobs', '-n', namespace, timeout=timeout)

    def get_events(self, namespace: str, timeout: int | None = None) -> str:
        return self.run('get', 'events', '-n', namespace, '--sort-by=.lastTimestamp', timeout=timeout)

    @staticmethod
    def _tail_arg(tail: int) -> str:
        return f'--tail={tail}' if tail >= 0 else '--tail=-1'

    def get_logs(self, pod: str, namespace: str, tail: int = 20, timeout: int | None = None) -> str:
        return self.run('logs', self._tail_arg(tail), pod, '-n', namespace, timeout=timeout)

    def log_follow_argv(self, pod: str, namespace: str, tail: int = 20) -> list[str]:
        # Full argv to stream one pod's logs (all containers). The multiplexer in
        # cli.py spawns one of these per pod via Popen and merges the output.
        return self._base_cmd() + [
            'logs', '-f', self._tail_arg(tail), '--all-containers=true', pod, '-n', namespace,
        ]

    def exec_shell(self, pod: str, namespace: str) -> None:
        # Interactive shell into a pod — needs TTY.
        # Prefer bash, fall back to sh. The fallback runs inside the container
        # because os.execvp replaces this process and can't retry.
        self.stream_tty(
            'exec', '-it', pod, '-n', namespace, '--',
            '/bin/sh', '-c', 'command -v bash >/dev/null 2>&1 && exec bash || exec sh',
        )

    def exec_command(self, pod: str, namespace: str, command: list[str]) -> None:
        # Run a one-off command in a pod and stream its output back.
        # The '--' is security-critical: it forces kubectl to treat `command` as
        # the in-container argv, so a user command starting with '-' can't be
        # parsed as a kubectl flag (e.g. --as / --kubeconfig / --token). Keep it.
        self.stream('exec', pod, '-n', namespace, '--', *command)

    def stream_tty(self, *args: str) -> None:
        # Replace process entirely so kubectl gets direct terminal control
        cmd = self._base_cmd() + list(args)
        os.execvp(cmd[0], cmd)

    def list_configmaps(self, namespace: str, timeout: int | None = None) -> list[str]:
        out = self.run(
            'get', 'configmaps', '-n', namespace, '-o',
            'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}',
            timeout=timeout,
        )
        return [c for c in out.strip().splitlines() if c]

    def get_configmap_yaml(self, name: str, namespace: str, timeout: int | None = None) -> str:
        return self.run('get', 'configmap', name, '-n', namespace, '-o', 'yaml', timeout=timeout)

    def describe(self, resource: str, namespace: str, timeout: int | None = None) -> str:
        return self.run('describe', resource, '-n', namespace, timeout=timeout)

    def list_resources(self, namespace: str, timeout: int | None = None) -> list[str]:
        # List common resource names for interactive picker
        out = self.run(
            'get', 'pods,deployments,services,configmaps', '-n', namespace,
            '--no-headers', '-o', 'name', timeout=timeout,
        )
        return [r for r in out.strip().splitlines() if r]

    def get_nodes(self, timeout: int | None = None) -> list[tuple[str, str]]:
        # (name, status) per node; STATUS is "Ready" / "NotReady" / "Ready,SchedulingDisabled".
        out = self.run('get', 'nodes', '--no-headers', timeout=timeout)
        nodes = []
        for line in out.strip().splitlines():
            parts = line.split()
            if parts:
                nodes.append((parts[0], parts[1] if len(parts) > 1 else '?'))
        return nodes

    def list_pod_status(self, namespace: str, timeout: int | None = None) -> list[tuple[str, str, str, str, str]]:
        # (name, ready, status, restarts, age). STATUS is kubectl's composite reason
        # (CrashLoopBackOff, ImagePullBackOff, Pending, ...) — far richer than .status.phase.
        # AGE is the last column; RESTARTS is the leading token of a "12 (5m ago)" field.
        out = self.run('get', 'pods', '-n', namespace, '--no-headers', timeout=timeout)
        pods = []
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                restarts = parts[3] if len(parts) > 3 else '0'
                age = parts[-1] if len(parts) >= 5 else ''
                pods.append((parts[0], parts[1], parts[2], restarts, age))
        return pods

    def workload_health(self, namespace: str, timeout: int | None = None) -> list[tuple[str, str, int, int]]:
        # (kind, name, ready, desired) for deployments, statefulsets and daemonsets.
        # JSON, not jsonpath: ready/available replica fields are omitted when zero
        # (exactly the degraded case we care about), and one call covers all kinds.
        out = self.run(
            'get', 'deployments,statefulsets,daemonsets', '-n', namespace,
            '-o', 'json', timeout=timeout,
        )
        workloads = []
        for item in json.loads(out).get('items', []):
            status, spec = item.get('status', {}), item.get('spec', {})
            name = item.get('metadata', {}).get('name', '?')
            kind = item.get('kind', 'workload').lower()
            if 'desiredNumberScheduled' in status:      # DaemonSet
                ready, desired = status.get('numberReady', 0), status['desiredNumberScheduled']
            else:                                       # Deployment / StatefulSet
                ready, desired = status.get('readyReplicas', 0), spec.get('replicas', 0)
            workloads.append((kind, name, ready, desired))
        return workloads

    def get_warning_events(self, namespace: str, limit: int = 5,
                           timeout: int | None = None) -> list[tuple[str, str, str, str]]:
        # (age, reason, object, message). kubectl's default events table already renders
        # LAST SEEN as a relative age; columns are LAST-SEEN TYPE REASON OBJECT MESSAGE.
        # kubectl sorts oldest-first, so we take the latest `limit` and reverse.
        out = self.run(
            'get', 'events', '-n', namespace, '--field-selector', 'type=Warning',
            '--sort-by=.lastTimestamp', '--no-headers', timeout=timeout,
        )
        events = []
        for line in out.strip().splitlines():
            parts = line.split(None, 4)
            if len(parts) == 5:
                age, _type, reason, obj, msg = parts
                events.append((age, reason, obj, msg))
        return events[-limit:][::-1]

    def list_deployments(self, namespace: str, timeout: int | None = None) -> list[str]:
        out = self.run(
            'get', 'deployments', '-n', namespace, '-o',
            'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}',
            timeout=timeout,
        )
        return [d for d in out.strip().splitlines() if d]

    def rollout_restart(self, deployment: str, namespace: str) -> str:
        return self.run('rollout', 'restart', f'deployment/{deployment}', '-n', namespace)

    def rollout_status(self, deployment: str, namespace: str) -> None:
        self.stream('rollout', 'status', f'deployment/{deployment}', '-n', namespace)

    def _list_name_port_pairs(self, jsonpath: str, namespace: str, timeout: int | None = None) -> list[tuple[str, str]]:
        # Parse "name port1,port2,\n" jsonpath output into (name, port) pairs
        out = self.run('get', 'services', '-n', namespace, '-o', jsonpath, timeout=timeout)
        pairs: list[tuple[str, str]] = []
        for line in out.strip().splitlines():
            if not line.strip():
                continue
            name, _, ports_csv = line.partition(' ')
            for port in ports_csv.split(','):
                if port.strip():
                    pairs.append((name, port.strip()))
        return pairs

    def list_services_with_ports(self, namespace: str, timeout: int | None = None) -> list[tuple[str, str]]:
        return self._list_name_port_pairs(
            'jsonpath={range .items[*]}{.metadata.name}{" "}{range .spec.ports[*]}{.port}{","}{end}{"\\n"}{end}',
            namespace, timeout=timeout,
        )

    def list_nodeport_services(self, namespace: str, timeout: int | None = None) -> list[tuple[str, str]]:
        return self._list_name_port_pairs(
            'jsonpath={range .items[?(@.spec.type=="NodePort")]}'
            '{.metadata.name}{" "}{range .spec.ports[*]}{.nodePort}{","}{end}{"\\n"}{end}',
            namespace, timeout=timeout,
        )

    def port_forward(self, svc: str, namespace: str, local_port: str, remote_port: str) -> None:
        self.stream('port-forward', '-n', namespace, f'svc/{svc}', f'{local_port}:{remote_port}')

    def find_namespace_exact(self, name: str, timeout: int | None = None) -> str:
        out = self.run(
            'get', 'namespaces', '-o',
            'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}',
            timeout=timeout,
        )
        for ns in out.strip().splitlines():
            if ns == name:
                return ns
        return ''

    def create_token(self, service_account: str, namespace: str, duration: str = '8760h') -> str:
        return self.run('create', 'token', service_account, '--namespace', namespace, f'--duration={duration}').strip()


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

    _SSH_OPTS = [
        '-o', 'ForwardAgent=no',
        '-o', 'ForwardX11=no',
        '-o', 'BatchMode=yes',
        '-o', 'PermitLocalCommand=no',
    ]

    def __init__(self, inner: KubeCtl, host: str):
        self._inner = inner
        self._host = host

    def _base_cmd(self) -> list[str]:
        return self._inner._base_cmd()  # pylint: disable=protected-access

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
                ['ssh', '-n'] + self._SSH_OPTS + ['--', self._host, remote_cmd],
                capture_output=True, text=True,
                timeout=timeout + 5 if timeout else None,
            )
        except subprocess.TimeoutExpired as err:
            raise RuntimeError(f'SSH command timed out on {self._host}') from err
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f'SSH command failed on {self._host}')
        return result.stdout

    def stream(self, *args: str) -> None:
        # shlex.join is security-critical: the remote sshd runs remote_cmd through
        # a shell, so each arg must be quoted to neutralize shell metacharacters
        # (;, |, $(), ...) in user-supplied exec commands. Do not interpolate raw.
        remote_cmd = shlex.join(self._base_cmd() + list(args))
        subprocess.run(['ssh', '-n'] + self._SSH_OPTS + ['--', self._host, remote_cmd])

    def stream_tty(self, *args: str) -> None:
        # Replace process with ssh -t for TTY allocation.
        # shlex.join is security-critical here too — see stream() above.
        remote_cmd = shlex.join(self._base_cmd() + list(args))
        os.execvp('ssh', ['ssh', '-t'] + self._SSH_OPTS + ['--', self._host, remote_cmd])

    def log_follow_argv(self, pod: str, namespace: str, tail: int = 20) -> list[str]:
        # Wrap the inner kubectl invocation in ssh. shlex.join quotes the remote
        # command for the same reason as stream() above.
        remote_cmd = shlex.join(self._inner.log_follow_argv(pod, namespace, tail))
        return ['ssh', '-n'] + self._SSH_OPTS + ['--', self._host, remote_cmd]


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
