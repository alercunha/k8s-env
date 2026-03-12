from __future__ import annotations
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from k8s_env import k8s
from k8s_env.utils import AppContext, ENV_FILE, is_available, validate

DISCOVERY_TIMEOUT = 10

PROFILES_DIR = os.path.join(ENV_FILE, 'profiles')
ACTIVE_LINK = os.path.join(ENV_FILE, 'active')


@dataclass
class Env:
    tool: str
    ssh_host: str = ''
    context: str = ''
    namespace: str = ''
    port_forwards: dict[str, str] = field(default_factory=dict)


def _parse_env_file(path: str) -> Env:
    # Parse key=value pairs; pf.* lines become port_forwards
    fields: dict[str, str] = {}
    port_forwards: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or '=' not in line:
                continue
            key, _, val = line.partition('=')
            if key.startswith('pf.'):
                port_forwards[key] = val
            else:
                fields[key] = val
    return Env(
        tool=fields.get('tool', ''),
        ssh_host=fields.get('ssh_host', ''),
        context=fields.get('context', ''),
        namespace=fields.get('namespace', ''),
        port_forwards=port_forwards,
    )


def resolve_env(ctx: AppContext) -> None:
    if os.path.isfile(ENV_FILE):
        ctx.env_path = ENV_FILE
        return
    if os.path.isdir(ENV_FILE):
        if os.path.islink(ACTIVE_LINK):
            ctx.env_path = os.path.realpath(ACTIVE_LINK)
            return
        raise SystemExit('No active profile. Run: k8s-env profile activate')
    raise SystemExit('No environment set. Run: k8s-env use')


@dataclass
class Profile:
    name: str
    env: Env


def _profile_name(env: Env) -> str:
    location = env.ssh_host or env.context or 'local'
    return f'{env.tool}-{location}-{env.namespace}'


def active_profile_name() -> str:
    if not os.path.islink(ACTIVE_LINK):
        return ''
    target = os.path.basename(os.readlink(ACTIVE_LINK))
    return target.removesuffix('.env')


def list_profiles() -> list[Profile]:
    if not os.path.isdir(PROFILES_DIR):
        return []
    profiles: list[Profile] = []
    for fname in sorted(os.listdir(PROFILES_DIR)):
        if not fname.endswith('.env'):
            continue
        profiles.append(Profile(
            name=fname.removesuffix('.env'),
            env=_parse_env_file(os.path.join(PROFILES_DIR, fname)),
        ))
    return profiles


def _write_env(path: str, env: Env) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(f'tool={env.tool}\n')
        f.write(f'ssh_host={env.ssh_host}\n')
        f.write(f'context={env.context}\n')
        f.write(f'namespace={env.namespace}\n')
        for key, val in env.port_forwards.items():
            f.write(f'{key}={val}\n')


def _write_profile(name: str, env: Env) -> str:
    os.makedirs(PROFILES_DIR, exist_ok=True)
    path = os.path.join(PROFILES_DIR, f'{name}.env')
    _write_env(path, env)
    return path


def _set_active(path: str) -> None:
    # Symlink target must be relative to the .k8s-env directory
    rel = os.path.relpath(path, ENV_FILE)
    tmp = ACTIVE_LINK + '.tmp'
    os.symlink(rel, tmp)
    os.replace(tmp, ACTIVE_LINK)


def profile_init(ctx: AppContext) -> str:
    # Initialize multi-profile structure from single .k8s-env file
    if os.path.isdir(ENV_FILE):
        raise SystemExit('Already in multi-profile mode. Use: k8s-env use')
    if not os.path.isfile(ENV_FILE):
        raise SystemExit('No environment set. Run: k8s-env use')
    env = load_env(ctx)
    name = _profile_name(env)
    os.remove(ENV_FILE)
    _set_active(_write_profile(name, env))
    return name


def profile_activate(name: str) -> None:
    path = os.path.join(PROFILES_DIR, f'{name}.env')
    if not os.path.isfile(path):
        raise SystemExit(f'Profile not found: {name}')
    _set_active(path)


def profile_delete(name: str) -> None:
    path = os.path.join(PROFILES_DIR, f'{name}.env')
    if not os.path.isfile(path):
        raise SystemExit(f'Profile not found: {name}')
    # If deleting the active profile, remove the symlink
    if os.path.islink(ACTIVE_LINK) and os.path.realpath(ACTIVE_LINK) == os.path.realpath(path):
        os.remove(ACTIVE_LINK)
    os.remove(path)
    # If no profiles left, remove the directory structure
    remaining = [f for f in os.listdir(PROFILES_DIR) if f.endswith('.env')]
    if not remaining:
        shutil.rmtree(ENV_FILE)


def load_env(ctx: AppContext) -> Env:
    if ctx.env:
        return ctx.env

    if ctx.env_path == ENV_FILE:
        resolve_env(ctx)

    path = ctx.env_path
    if not os.path.isfile(path):
        raise SystemExit('No environment set. Run: k8s-env use')

    env = _parse_env_file(path)

    # Validate all non-empty fields
    validate('tool', env.tool)
    if env.namespace:
        validate('namespace', env.namespace)
    if env.context:
        validate('context', env.context)
    if env.ssh_host:
        validate('host', env.ssh_host)

    ctx.env = env
    return env


def save_env(env: Env, ctx: AppContext) -> None:
    # In multi-profile mode, create a new profile and activate it
    if ctx.env_path == ENV_FILE and os.path.isdir(ENV_FILE):
        name = _profile_name(env)
        path = _write_profile(name, env)
        _set_active(path)
        ctx.env_path = path
        ctx.env = env
        return

    path = ctx.env_path
    if os.path.islink(path):
        raise SystemExit(f'{path} is a symlink — refusing to write')

    _write_env(path, env)
    ctx.env = env


def require_env(ctx: AppContext) -> None:
    env = load_env(ctx)
    if not ctx.kubectl:
        ctx.kubectl = k8s.get(
            tool=env.tool,
            context=env.context,
            ssh_host=env.ssh_host,
        )


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
    return [NamespaceEntry(tool=kubectl.tool_name, context=kubectl.context, namespace=ns, group=group) for ns in namespaces]


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
