from __future__ import annotations
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from k8s_env import k8s
from k8s_env.utils import AppContext, ENV_FILE, is_available, validate

DISCOVERY_TIMEOUT = 10

GLOBAL_DIR = os.path.join(
    os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), 'k8s-env',
)
PROFILES_DIR = os.path.join(GLOBAL_DIR, 'profiles')
ACTIVE_LINK = os.path.join(GLOBAL_DIR, 'active')


@dataclass
class Env:
    tool: str
    ssh_host: str = ''
    context: str = ''
    namespace: str = ''


def _parse_env_file(path: str) -> Env:
    # Parse key=value pairs, skip port-forward lines (pf.*)
    fields: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('pf.'):
                key, _, val = line.partition('=')
                fields[key] = val
    return Env(
        tool=fields.get('tool', ''),
        ssh_host=fields.get('ssh_host', ''),
        context=fields.get('context', ''),
        namespace=fields.get('namespace', ''),
    )


def resolve_env(ctx: AppContext) -> None:
    # Local file wins unless -g forces global mode
    if not ctx.global_mode and os.path.isfile(ENV_FILE):
        ctx.env_path = ENV_FILE
        return
    # Fall through to global active profile
    if os.path.islink(ACTIVE_LINK):
        ctx.env_path = os.path.realpath(ACTIVE_LINK)
        return
    raise SystemExit('No environment set. Run: k8s-env use')


@dataclass
class Profile:
    name: str
    env: Env


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


def save_global(env: Env, name: str) -> None:
    validate('profile', name)
    os.makedirs(PROFILES_DIR, exist_ok=True)

    # Write profile file with restricted permissions
    path = os.path.join(PROFILES_DIR, f'{name}.env')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(f'tool={env.tool}\n')
        f.write(f'ssh_host={env.ssh_host}\n')
        f.write(f'context={env.context}\n')
        f.write(f'namespace={env.namespace}\n')

    # Atomically update active symlink
    tmp = ACTIVE_LINK + '.tmp'
    os.symlink(path, tmp)
    os.replace(tmp, ACTIVE_LINK)


def activate_profile(name: str) -> None:
    path = os.path.join(PROFILES_DIR, f'{name}.env')
    if not os.path.isfile(path):
        raise SystemExit(f'Profile not found: {name}')
    tmp = ACTIVE_LINK + '.tmp'
    os.symlink(path, tmp)
    os.replace(tmp, ACTIVE_LINK)


def active_profile_name() -> str:
    if not os.path.islink(ACTIVE_LINK):
        return ''
    target = os.path.basename(os.readlink(ACTIVE_LINK))
    return target.removesuffix('.env')


def load_env(ctx: AppContext) -> Env:
    if ctx.env:
        return ctx.env

    # Resolve env_path if still at the default
    if ctx.env_path == ENV_FILE and (ctx.global_mode or not os.path.isfile(ENV_FILE)):
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
    path = ctx.env_path
    if os.path.islink(path):
        raise SystemExit(f'{path} is a symlink — refusing to write')

    # Preserve port-forward mappings from previous env file
    pf_lines: list[str] = []
    if os.path.isfile(path):
        with open(path) as f:
            pf_lines = [line.rstrip('\n') for line in f if line.startswith('pf.')]

    # Write with restricted permissions (owner-only)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(f'tool={env.tool}\n')
        f.write(f'ssh_host={env.ssh_host}\n')
        f.write(f'context={env.context}\n')
        f.write(f'namespace={env.namespace}\n')
        for line in pf_lines:
            f.write(f'{line}\n')

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
    group: str  # display group label


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
