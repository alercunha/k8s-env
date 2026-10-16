from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass

from k8s_env import service
from k8s_env.args import first, handle_help, parse_args
from k8s_env.app import App
from k8s_env.k8s import KubeCtl
from k8s_env.service import Env
from k8s_env.utils import CMD, ENV_VAR, validate

# -- Colors -------------------------------------------------------------------

# Emit ANSI only when stdout is a terminal, so redirected/piped output stays
# clean (no escape bytes in files or downstream tools). Honors NO_COLOR too.
_COLOR = sys.stdout.isatty() and not os.environ.get('NO_COLOR')


def _c(code: str) -> str:
    return code if _COLOR else ''


_RED = _c('\033[0;31m')
_GREEN = _c('\033[0;32m')
_YELLOW = _c('\033[1;33m')
_CYAN = _c('\033[0;36m')
_BOLD = _c('\033[1m')
_DIM = _c('\033[2m')
_NC = _c('\033[0m')

# Per-pod prefix colors for multi-tail (cycled when there are more pods).
_LOG_PALETTE = tuple(_c(code) for code in (
    '\033[0;36m', '\033[0;32m', '\033[0;33m', '\033[0;35m', '\033[0;34m', '\033[0;31m',
    '\033[1;36m', '\033[1;32m', '\033[1;33m', '\033[1;35m', '\033[1;34m', '\033[1;31m',
))

# Cap concurrent follow streams (one process + thread each) to avoid fan-out.
_MAX_FOLLOW = 50


def _input(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise SystemExit('This command requires an interactive terminal.')
    # Prompt to stderr so stdout stays clean for piping command output
    print(prompt, end='', file=sys.stderr, flush=True)
    return input()


def print_status(msg: str) -> None:
    print(f'{_GREEN}[INFO]{_NC} {msg}', file=sys.stderr)


def print_warning(msg: str) -> None:
    print(f'{_YELLOW}[WARN]{_NC} {msg}', file=sys.stderr)


def print_error(msg: str) -> None:
    print(f'{_RED}[ERROR]{_NC} {msg}', file=sys.stderr)


def open_url(url: str) -> None:
    for cmd in ('xdg-open', 'open'):
        if shutil.which(cmd):
            subprocess.Popen([cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # pylint: disable=consider-using-with
            return
    print_warning(f'Could not open browser. Visit {url} manually.')


def print_banner(app: App) -> None:
    # '[shop/dev] k8s @ gke-prod / shop'; the tag is yellow when kubectl runs over SSH
    env = app.env
    color = _YELLOW if env.ssh_host else _CYAN
    print(f'{color}[{env.label}]{_NC} {_BOLD}{env.describe(app.namespace)}{_NC}', file=sys.stderr)


def _filter(items: list, text: str, key=lambda x: x) -> list:
    lower = text.lower()
    return [x for x in items if lower in key(x).lower()]


def print_filtered(output: str, filter_text: str) -> None:
    lines = output.rstrip('\n').splitlines()
    if not lines:
        return
    if not filter_text:
        print(output, end='')
        return
    # Always show header row, filter the rest case-insensitively
    print(lines[0])
    for line in _filter(lines[1:], filter_text):
        print(line)


# -- Picker -------------------------------------------------------------------

def print_grouped(
    items: list[str], groups: list[str] | None = None, *,
    numbered: bool = False, indent: str = '', file=sys.stdout,
) -> None:
    # Items under a header for each run of adjacent equal group names;
    # items with an empty group name get no header and no extra indent.
    current = ''
    for i, item in enumerate(items):
        group = groups[i] if groups else ''
        if group != current:
            if i:
                print(file=file)
            print(f'{indent}{_YELLOW}{group}{_NC}', file=file)
            current = group
        num = f'{_CYAN}{i + 1}){_NC} ' if numbered else ''
        print(f'{indent}{"  " if group else ""}{num}{item}', file=file)


def pick(
    title: str, items: list[str], *,
    groups: list[str] | None = None, auto: bool = False, multi: bool = False,
) -> list[tuple[int, str]]:
    if not items:
        raise SystemExit('No items to select from')

    # Skip prompt when only one option and auto is enabled
    if auto and len(items) == 1:
        print(f'{_BOLD}{title}:{_NC} {items[0]}', file=sys.stderr)
        return [(0, items[0])]

    # Display to stderr so stdout stays clean for piping
    print(f'{_BOLD}{title}:{_NC}', file=sys.stderr)
    print_grouped(items, groups, numbered=True, indent='  ', file=sys.stderr)
    print(file=sys.stderr)

    if multi:
        raw = _input(f'Select [1-{len(items)}, comma-separated or \'all\']: ')
    else:
        raw = _input(f'Select [1-{len(items)}]: ')

    if multi and raw.strip().lower() == 'all':
        return list(enumerate(items))

    # Parse comma-separated selections, validate each
    selected: list[tuple[int, str]] = []
    for part in raw.split(','):
        part = part.strip()
        if not part.isdigit() or not 1 <= int(part) <= len(items):
            raise SystemExit(f'Invalid selection: {part}')
        idx = int(part) - 1
        selected.append((idx, items[idx]))

    if not selected:
        raise SystemExit('No selection made')
    return selected


# -- Env commands -------------------------------------------------------------

def _format_env(label: str, env: Env, active_key: str, width: int) -> str:
    if env.key == active_key:
        return f'{_GREEN}{label.ljust(width)}{env.describe()} (active){_NC}'
    return f'{label.ljust(width)}{_DIM}{env.describe()}{_NC}'


def _env_items(app: App) -> tuple[list[Env], list[str], list[str]]:
    # (envs, display items, groups) for print_grouped/pick: 'shop/dev' is item 'dev' in
    # group 'shop', unnamed envs show as '[key]'. Ungrouped sort first, named before
    # unnamed. Grouped labels are 2 narrower to offset their indent, keeping details aligned.
    rows = []
    for env in app.store.list():
        group, _, leaf = env.name.rpartition('/')
        rows.append((group, leaf or f'[{env.key}]', env))
    rows.sort(key=lambda r: (r[0], not r[2].name, r[1]))
    pad = [2 if group else 0 for group, _, _ in rows]
    width = max((len(label) + p for (_, label, _), p in zip(rows, pad)), default=0) + 2
    active_key = app.store.active_key
    items = [_format_env(label, env, active_key, width - p) for (_, label, env), p in zip(rows, pad)]
    return [env for _, _, env in rows], items, [group for group, _, _ in rows]


def _env_list(app: App) -> None:
    envs, items, groups = _env_items(app)
    if not envs:
        print(f'{_DIM}No envs saved. Run: {CMD} env add{_NC}')
        return
    print_grouped(items, groups)


def _validate_name(name: str) -> str:
    if name:
        try:
            validate('name', name)
        except ValueError as e:
            raise SystemExit(str(e)) from None
    return name


def _select_env(app: App, name: str, title: str) -> Env:
    # Resolve by name when given, otherwise fall back to the interactive picker
    if name:
        return app.store.by_name(name)
    envs, items, groups = _env_items(app)
    return envs[pick(title, items, groups=groups)[0][0]]


def _pick_and_add(app: App, found: list[Env], title: str, name: str) -> None:
    labels = [env.namespace for env in found]
    groups = [env.target for env in found]
    env = found[pick(title, labels, groups=groups)[0][0]]
    env.name = _validate_name(name or _input('Name (optional, enter to skip): ').strip())
    app.store.add(env)
    print()
    print_status(f'Added {_BOLD}{env.label}{_NC}: {env.describe()}')


def _env_add(app: App, args: list[str]) -> None:
    found = service.discover_local()
    if not found:
        raise SystemExit('No namespaces found (checked microk8s, minikube, and kubectl contexts)')
    _pick_and_add(app, found, 'Available namespaces', first(args))


def _env_add_remote(app: App, args: list[str]) -> None:
    host = first(args) or _input('Remote host: ').strip()
    if not host:
        raise SystemExit('No host provided')
    found = service.discover_remote(host)
    if not found:
        raise SystemExit(f'No custom namespaces found on {host} (checked microk8s and minikube)')
    _pick_and_add(app, found, f'Namespaces on {host}', args[1] if len(args) > 1 else '')


def _env_set(app: App, name: str) -> None:
    envs = app.store.list()
    if not envs:
        raise SystemExit(f'No envs saved. Run: {CMD} env add')
    if not name and len(envs) == 1:
        print_status(f'Already on the only env: {_BOLD}{envs[0].label}{_NC}')
        return
    selected = _select_env(app, name, 'Activate env')
    if selected.key == app.store.active_key:
        print_status(f'Already on {_BOLD}{selected.label}{_NC}')
        return
    app.store.activate(selected.key)
    print()
    print_status(f'Switched to {_BOLD}{selected.label}{_NC}')
    if app.env_override:
        print_warning(f'-e / {ENV_VAR} ({app.env_override}) still takes precedence')


def _env_del(app: App, name: str) -> None:
    if not app.store.list():
        raise SystemExit('No envs saved')
    selected = _select_env(app, name, 'Delete env')
    new_active = app.store.delete(selected.key)
    print()
    print_status(f'Deleted {_BOLD}{selected.label}{_NC}')
    if new_active:
        print_status(f'Switched to {_BOLD}{new_active.label}{_NC}')


def _env_kubectl(app: App, name: str) -> None:
    # Resolve the target up front, but don't mutate the active env until
    # the user confirms — aborting must leave everything untouched.
    selected = app.store.by_name(name) if name else None
    env = selected or app.env
    if env.tool != 'k8s':
        print_status(f'{env.tool} does not use kubectl contexts — nothing to do.')
        return

    ns = app.ns_override or env.namespace
    print('This will set your kubectl config to:')
    print(f'  context:   {_BOLD}{env.context}{_NC}')
    print(f'  namespace: {_BOLD}{ns}{_NC}')
    raw = _input('\nProceed? [y/N]: ').strip().lower()
    if raw != 'y':
        raise SystemExit('Aborted')

    if selected and selected.key != app.store.active_key:
        app.store.activate(selected.key)
    subprocess.run(['kubectl', 'config', 'use-context', env.context], check=True)
    subprocess.run(['kubectl', 'config', 'set-context', env.context,
                     '--namespace', ns], check=True)
    print()
    print_status(f'kubectl now using context {_BOLD}{env.context}{_NC} / namespace {_BOLD}{ns}{_NC}')


def _env_rename(app: App, name: str) -> None:
    env = app.env
    old = env.label
    if not name:
        name = _input(f'New name for {old}, enter to clear: ').strip()
    env.name = _validate_name(name)
    app.store.save(env)
    print()
    if env.name:
        print_status(f'Renamed {_BOLD}{old}{_NC} to {_BOLD}{env.name}{_NC}')
    else:
        print_status(f'Cleared name on {_BOLD}{old}{_NC}')


_ENV_COMMANDS = {
    '':           lambda app, _args: _env_list(app),
    'add':        lambda app, args:  _env_add(app, args),
    'add-remote': lambda app, args:  _env_add_remote(app, args),
    'set':        lambda app, args:  _env_set(app, first(args)),
    'del':        lambda app, args:  _env_del(app, first(args)),
    'kubectl':    lambda app, args:  _env_kubectl(app, first(args)),
    'rename':     lambda app, args:  _env_rename(app, first(args)),
}


def cmd_env(app: App, args: list[str]) -> None:
    sub = first(args)
    handler = _ENV_COMMANDS.get(sub)
    if not handler:
        raise SystemExit(f'Unknown env subcommand: {sub}. Use: add, add-remote, set, del, kubectl, rename')
    handler(app, args[1:])


# -- Other commands -----------------------------------------------------------

def cmd_namespaces(app: App) -> None:
    print_banner(app)
    print(app.kubectl.get_namespaces_all(), end='')


def cmd_pods(app: App, filter_text: str) -> None:
    print_banner(app)
    ns = app.namespace
    print_status(f'Pods in {_BOLD}{ns}{_NC}')
    print_filtered(app.kubectl.get_pods(ns), filter_text)


def cmd_services(app: App, filter_text: str) -> None:
    print_banner(app)
    ns = app.namespace
    print_status(f'Services in {_BOLD}{ns}{_NC}')
    print_filtered(app.kubectl.get_services(ns), filter_text)


def cmd_secrets(app: App, filter_text: str) -> None:
    print_banner(app)
    ns = app.namespace
    print_status(f'Secrets in {_BOLD}{ns}{_NC} {_DIM}(names only){_NC}')
    print_filtered(app.kubectl.get_secrets(ns), filter_text)


def cmd_cronjobs(app: App, filter_text: str) -> None:
    print_banner(app)
    ns = app.namespace
    print_status(f'CronJobs in {_BOLD}{ns}{_NC}')
    print_filtered(app.kubectl.get_cronjobs(ns), filter_text)


def cmd_events(app: App, filter_text: str) -> None:
    print_banner(app)
    ns = app.namespace
    print_status(f'Recent events in {_BOLD}{ns}{_NC}')
    # Show last 30 lines of sorted events
    output = app.kubectl.get_events(ns)
    lines = output.rstrip('\n').splitlines()
    trimmed = '\n'.join(lines[:1] + lines[-30:]) if len(lines) > 31 else output
    print_filtered(trimmed, filter_text)


def _follow_multi(k: KubeCtl, pods: list[str], ns: str, tail: int) -> None:
    # Stream every matching pod concurrently, each line prefixed with
    # a colored, padded pod name. One Popen + reader thread per pod; a lock keeps
    # lines from interleaving mid-write. Ctrl+C (caught in main) hits the finally.
    width = max(len(p) for p in pods)
    lock = threading.Lock()
    procs: list[subprocess.Popen] = []

    def reader(proc: subprocess.Popen, label: str, color: str) -> None:
        for line in proc.stdout:
            with lock:
                sys.stdout.write(f'{color}{label}{_NC} {line}')
                sys.stdout.flush()

    threads: list[threading.Thread] = []
    try:
        for i, pod in enumerate(pods):
            color = _LOG_PALETTE[i % len(_LOG_PALETTE)]
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                k.log_follow_argv(pod, ns, tail),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            procs.append(proc)
            t = threading.Thread(target=reader, args=(proc, pod.ljust(width), color), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


def cmd_logs(app: App, args: list[str]) -> None:
    follow, tail, rest = parse_args(args, {'-f': False, '--tail': 20})
    if tail == 0:
        raise SystemExit('--tail must be a positive number or -1 for all lines')
    filter_text = first(rest)
    print_banner(app)
    ns = app.namespace
    k = app.kubectl

    pods = k.list_pods(ns)
    if filter_text:
        pods = _filter(pods, filter_text)
    if not pods:
        print_warning(f'No pods found in {ns}')
        return

    if follow:
        if len(pods) > _MAX_FOLLOW:
            print_warning(f'Following first {_MAX_FOLLOW} of {len(pods)} pods; narrow with a filter')
            pods = pods[:_MAX_FOLLOW]
        print_status(f'Tailing {_BOLD}{len(pods)}{_NC} pod(s) (Ctrl+C to stop)')
        _follow_multi(k, pods, ns, tail)
    else:
        for pod in pods:
            print()
            print(f'{_CYAN}{_BOLD}--- {pod} ---{_NC}')
            try:
                print(k.get_logs(pod, ns, tail=tail), end='')
            except RuntimeError:
                print(f'{_DIM}(no logs){_NC}')


def cmd_configmaps(app: App, filter_text: str = '') -> None:
    print_banner(app)
    ns = app.namespace

    cms = app.kubectl.list_configmaps(ns)
    if filter_text:
        cms = _filter(cms, filter_text)
    if not cms:
        print_warning(f'No configmaps found in {ns}')
        return

    print(f'{_BOLD}ConfigMaps in {ns}:{_NC}')
    for i, cm in enumerate(cms):
        print(f'  {_CYAN}{i + 1}){_NC} {cm}')
    print()
    raw = _input(f'View configmap? [1-{len(cms)}, enter to skip]: ').strip()
    if not raw:
        return
    if not raw.isdigit() or not 1 <= int(raw) <= len(cms):
        raise SystemExit(f'Invalid selection: {raw}')
    print()
    print(app.kubectl.get_configmap_yaml(cms[int(raw) - 1], ns), end='')


def cmd_exec(app: App, args: list[str]) -> None:
    # Everything after '--' is a command to run in the pod; without it, open a shell
    if '--' in args:
        sep = args.index('--')
        filter_text, command = first(args[:sep]), args[sep + 1:]
    else:
        filter_text, command = first(args), []

    print_banner(app)
    ns = app.namespace
    k = app.kubectl

    pods = k.list_pods(ns)
    if filter_text:
        pods = _filter(pods, filter_text)
    if not pods:
        print_warning(f'No pods found in {ns}')
        return

    selected = pick(f'Pods in {ns}', pods, auto=True)[0][1]
    if command:
        print_status(f'Running in {_BOLD}{selected}{_NC}...')
        k.exec_command(selected, ns, command)
    else:
        print_status(f'Connecting to {_BOLD}{selected}{_NC}...')
        k.exec_shell(selected, ns)


def _pick_service(pairs: list[tuple[str, str]], title: str, port_label: str) -> tuple[str, str]:
    labels = [f'{name} {_DIM}({port_label}: {port}){_NC}' for name, port in pairs]
    idx = pick(title, labels, auto=True)[0][0]
    return pairs[idx]


def _do_port_forward(app: App, svc_name: str, svc_port: str) -> None:
    # Look up saved local port from env
    env = app.env
    pf_key = f'pf.{svc_name}.{svc_port}'
    saved_port = env.port_forwards.get(pf_key, '')
    default_port = saved_port or svc_port

    raw = _input(f'Local port [{default_port}]: ').strip()
    local_port = raw or default_port
    if not local_port.isdigit() or not 1 <= int(local_port) <= 65535:
        raise SystemExit(f'Invalid port: {local_port} (must be 1-65535)')

    # Save the port mapping
    env.port_forwards[pf_key] = local_port
    app.store.save(env)

    print_status(f'Forwarding localhost:{local_port} → svc/{svc_name}:{svc_port} (Ctrl+C to stop)')
    app.kubectl.port_forward(svc_name, app.namespace, local_port, svc_port)


def cmd_restart(app: App, filter_text: str) -> None:
    print_banner(app)
    ns = app.namespace
    k = app.kubectl

    deployments = k.list_deployments(ns)
    if filter_text:
        deployments = _filter(deployments, filter_text)
    if not deployments:
        print_warning(f'No deployments found in {ns}')
        return

    selected = pick(f'Deployments in {ns}', deployments, multi=True)
    names = [name for _, name in selected]

    for name in names:
        print_status(f'Restarting {_BOLD}{name}{_NC}...')
        k.rollout_restart(name, ns)
    for name in names:
        k.rollout_status(name, ns)
    print_status('Done')


def cmd_port_forward(app: App, filter_text: str = '') -> None:
    print_banner(app)
    if app.kubectl.ssh_host:
        raise SystemExit('port-forward is not supported over SSH sessions')

    pairs = app.kubectl.list_services_with_ports(app.namespace)
    if filter_text:
        pairs = _filter(pairs, filter_text, key=lambda x: x[0])
    if not pairs:
        print_warning(f'No services found in {app.namespace}')
        return

    svc_name, svc_port = _pick_service(pairs, f'Services in {app.namespace}', 'port')
    _do_port_forward(app, svc_name, svc_port)


def cmd_app(app: App, filter_text: str = '') -> None:
    if app.kubectl.ssh_host:
        raise SystemExit('app is not supported over SSH sessions')

    if app.env.tool == 'minikube':
        print_warning("minikube doesn't expose NodePorts on localhost — using port-forward instead")
        cmd_port_forward(app, filter_text)
        return

    print_banner(app)
    pairs = app.kubectl.list_nodeport_services(app.namespace)
    if filter_text:
        pairs = _filter(pairs, filter_text, key=lambda x: x[0])
    if not pairs:
        print_warning(f'No NodePort services found in {app.namespace}')
        return

    _, node_port = _pick_service(pairs, f'NodePort services in {app.namespace}', 'nodePort')
    url = f'http://localhost:{node_port}'
    print_status(f'Opening {_BOLD}{url}{_NC}')
    open_url(url)


def cmd_dashboard(app: App, args: list[str]) -> None:
    new_token, _ = parse_args(args, {'-t': False})

    if app.kubectl.ssh_host:
        raise SystemExit('dashboard is not supported over SSH sessions')

    k = app.kubectl
    ns = k.find_namespace_exact('headlamp')
    if not ns:
        raise SystemExit('Headlamp namespace not found')

    pairs = k.list_nodeport_services(ns)
    if not pairs:
        raise SystemExit(f'No NodePort service found in {ns}')

    if new_token:
        print_status('Generating new Headlamp token (valid 1 year)...')
        token = k.create_token('headlamp', ns)
        print()
        print(token)
        print()

    url = f'http://localhost:{pairs[0][1]}'
    print_status(f'Opening Headlamp at {_BOLD}{url}{_NC}')
    open_url(url)


def cmd_describe(app: App, arg: str) -> None:
    print_banner(app)
    ns = app.namespace

    if not arg:
        resources = app.kubectl.list_resources(ns)
        if not resources:
            print_warning(f'No resources found in {ns}')
            return
        arg = pick(f'Resources in {ns}', resources, auto=True)[0][1]
    print(app.kubectl.describe(arg, ns), end='')


def cmd_status(app: App) -> None:
    print_banner(app)
    ns = app.namespace
    print()

    output = app.kubectl.get_resources_summary(ns)
    lines = output.strip().splitlines()

    # Count resources by type prefix
    counts = {'node/': 0, 'pod/': 0, 'deployment': 0, 'service/': 0}
    pod_lines = []
    for line in lines:
        for prefix in counts:
            if line.startswith(prefix):
                counts[prefix] += 1
        if line.startswith('pod/'):
            pod_lines.append(line)

    print(f'{_BOLD}Cluster:{_NC}')
    print(f'  Nodes:        {counts["node/"]}')
    print()
    print(f'{_BOLD}Namespace {ns}:{_NC}')
    print(f'  Pods:         {counts["pod/"]}')
    print(f'  Deployments:  {counts["deployment"]}')
    print(f'  Services:     {counts["service/"]}')
    print()

    not_ready = [line for line in pod_lines if 'Running' not in line and 'Completed' not in line]
    if not_ready:
        print_warning('Pods not running:')
        for line in not_ready:
            print(f'  {line.removeprefix("pod/")}')
    else:
        print_status('All pods running')


# -- Help ---------------------------------------------------------------------

@dataclass(frozen=True)
class _Cmd:
    group: str
    summary: str
    args: str = ''                                  # positional signature for the overview
    options: tuple[tuple[str, str], ...] = ()       # (flag, description) pairs
    aliases: tuple[str, ...] = ()                   # short forms
    forms: tuple[str, ...] = ()                     # synopsis lines for --help (default: name+args)
    subcommands: tuple[tuple[str, str], ...] = ()   # (usage, summary) — env only


_GROUPS = ('Environments', 'Inspection', 'Actions')

# Single source of truth for both the overview (show_help) and per-command help.
_COMMANDS_META = {
    # Environments
    'env': _Cmd('Environments', 'Manage saved envs (lists them with no subcommand)', subcommands=(
        ('env',                          'List saved envs'),
        ('env add [name]',               'Add an env from a local namespace'),
        ('env add-remote [host] [name]', 'Add an env from a remote namespace via SSH'),
        ('env set [name]',               'Switch the active env'),
        ('env del [name]',               'Delete a saved env'),
        ('env kubectl [name]',           'Point kubectl config at an env (default: active)'),
        ('env rename [name]',            'Rename the current env (active, or -e), or clear its name'),
    )),
    # Inspection
    'pods':       _Cmd('Inspection', 'List pods (filter by name)', args='[filter]'),
    'logs':       _Cmd('Inspection', 'Show log output for pods in the current namespace',
                       args='[filter]', aliases=('log',), forms=('logs [filter] [-f] [--tail N]',), options=(
                           ('-f',             'Follow logs from all matching pods concurrently'),
                           ('--tail <lines>', 'Number of lines to show (default 20, -1 for all)'),
                       )),
    'services':   _Cmd('Inspection', 'List services', args='[filter]', aliases=('svc',)),
    'namespaces': _Cmd('Inspection', 'List all namespaces', aliases=('ns',)),
    'events':     _Cmd('Inspection', 'Show recent events', args='[filter]'),
    'configmaps': _Cmd('Inspection', 'List configmaps (interactive viewer)', args='[filter]', aliases=('cm',)),
    'secrets':    _Cmd('Inspection', 'List secret names', args='[filter]'),
    'cronjobs':   _Cmd('Inspection', 'List cronjobs', args='[filter]', aliases=('cj',)),
    'status':     _Cmd('Inspection', 'Show cluster and namespace stats', aliases=('st',)),
    'describe':   _Cmd('Inspection', 'Describe a resource (picker if omitted)', args='[resource]', aliases=('desc',)),
    # Actions
    'exec':         _Cmd('Actions', 'Open a shell in a pod, or run a command after --', args='[filter]',
                         aliases=('sh',), forms=('exec [filter]', 'exec [filter] -- cmd')),
    'restart':      _Cmd('Actions', 'Restart deployments (interactive multi-picker)', args='[filter]'),
    'port-forward': _Cmd('Actions', 'Forward a service port (local only)', args='[filter]', aliases=('pf',)),
    'app':          _Cmd('Actions', 'Open a NodePort service in browser (local only)', args='[filter]'),
    'dashboard':    _Cmd('Actions', 'Open Headlamp dashboard in the browser', forms=('dashboard [-t]',), options=(
        ('-t', 'Generate a new access token (valid 1 year)'),
    )),
}

_ALIASES = {alias: name for name, c in _COMMANDS_META.items() for alias in c.aliases}


def _label(name: str, c: _Cmd) -> str:
    return f'{name} {c.args}'.strip()


def _rows() -> list[tuple[str, str, str]]:
    # Flatten the table into (group, label, summary) rows; env expands to its subcommands.
    rows: list[tuple[str, str, str]] = []
    for name, c in _COMMANDS_META.items():
        if c.subcommands:
            rows += [(c.group, usage, summary) for usage, summary in c.subcommands]
        else:
            rows.append((c.group, _label(name, c), c.summary))
    return rows


def _aligned(pairs: list[tuple[str, str]], indent: str = '  ') -> list[str]:
    width = max(len(left) for left, _ in pairs) + 2
    return [f'{indent}{left.ljust(width)}{right}' for left, right in pairs]


def _usage_lines(name: str, c: _Cmd) -> list[str]:
    # One synopsis line per invocation form; continuation lines align under the first.
    forms = c.forms or (_label(name, c),)
    pad = ' ' * len('Usage: ')
    return [f'{_BOLD}Usage:{_NC} {CMD} {form}' if i == 0 else f'{pad}{CMD} {form}'
            for i, form in enumerate(forms)]


def show_help() -> None:
    b, n = _BOLD, _NC
    rows = _rows()
    lines = [
        f'{b}{CMD}{n} — Kubernetes environment helper',
        '',
        f'{b}Usage:{n} {CMD} <command> [args] [-e env] [-n namespace]',
        '',
    ]
    width = max(len(label) for _, label, _ in rows) + 2
    for group in _GROUPS:
        lines.append(f'{b}{group}:{n}')
        lines += [f'  {label.ljust(width)}{summary}'
                  for g, label, summary in rows if g == group]
        lines.append('')
    lines.append(f'{b}Options:{n}')
    lines += [f'  {left.ljust(width)}{right}' for left, right in (
        ('-e <env>', f'Use this env instead of the active one (default: ${ENV_VAR})'),
        ('-n <namespace>', 'Override saved namespace'),
        ('-h, --help', 'Show this help'),
    )]
    print('\n'.join(lines))


def _command_help(name: str) -> None:
    b, n = _BOLD, _NC
    c = _COMMANDS_META[name]
    if c.subcommands:
        lines = [f'{b}Usage:{n} {CMD} {name} [subcommand]', '', c.summary,
                 '', f'{b}Subcommands:{n}', *_aligned(list(c.subcommands))]
        print('\n'.join(lines))
        return
    lines = [*_usage_lines(name, c), '', c.summary]
    if c.options:
        lines += ['', f'{b}Options:{n}', *_aligned(list(c.options))]
    if c.aliases:
        lines += ['', f'{b}Aliases:{n} {", ".join(c.aliases)}']
    print('\n'.join(lines))


def _print_help(command: str) -> None:
    name = _ALIASES.get(command, command)
    if name in _COMMANDS_META:
        _command_help(name)
    else:
        show_help()


# -- Main ---------------------------------------------------------------------

_COMMANDS = {
    # Environments
    'env':          lambda app, args:  cmd_env(app, args),
    # Inspection
    'pods':         lambda app, args:  cmd_pods(app, first(args)),
    'logs':         lambda app, args:  cmd_logs(app, args),
    'log':          lambda app, args:  cmd_logs(app, args),
    'services':     lambda app, args:  cmd_services(app, first(args)),
    'svc':          lambda app, args:  cmd_services(app, first(args)),
    'namespaces':   lambda app, _args: cmd_namespaces(app),
    'ns':           lambda app, _args: cmd_namespaces(app),
    'events':       lambda app, args:  cmd_events(app, first(args)),
    'configmaps':   lambda app, args:  cmd_configmaps(app, first(args)),
    'cm':           lambda app, args:  cmd_configmaps(app, first(args)),
    'secrets':      lambda app, args:  cmd_secrets(app, first(args)),
    'cronjobs':     lambda app, args:  cmd_cronjobs(app, first(args)),
    'cj':           lambda app, args:  cmd_cronjobs(app, first(args)),
    'status':       lambda app, _args: cmd_status(app),
    'st':           lambda app, _args: cmd_status(app),
    'describe':     lambda app, args:  cmd_describe(app, first(args)),
    'desc':         lambda app, args:  cmd_describe(app, first(args)),
    # Actions
    'exec':         lambda app, args:  cmd_exec(app, args),
    'sh':           lambda app, args:  cmd_exec(app, args),
    'restart':      lambda app, args:  cmd_restart(app, first(args)),
    'port-forward': lambda app, args:  cmd_port_forward(app, first(args)),
    'pf':           lambda app, args:  cmd_port_forward(app, first(args)),
    'app':          lambda app, args:  cmd_app(app, first(args)),
    'dashboard':    lambda app, args:  cmd_dashboard(app, args),
}

# Dispatch (_COMMANDS) and help (_COMMANDS_META + _ALIASES) are separate
# registries; this tripwire fails loudly if they ever drift out of sync.
assert set(_COMMANDS) == set(_COMMANDS_META) | set(_ALIASES), \
    'cli: dispatch and help registries are out of sync'


def main() -> None:
    # Everything after the first '--' is an opaque command (e.g. for exec) and must
    # not be scanned for our own flags like -n (think `exec api -- tail -n 100`).
    argv = sys.argv[1:]
    sep = argv.index('--') if '--' in argv else -1
    head, passthrough = (argv[:sep], argv[sep:]) if sep >= 0 else (argv, [])

    env_override, ns_override, positional = parse_args(head, {
        '-e': os.environ.get(ENV_VAR, ''),
        '-n': '',
    })

    if not positional:
        show_help()
        sys.exit(0)

    command = positional[0]
    args = positional[1:] + passthrough

    # Single place -h/--help is handled: any command (or a bare flag) prints
    # help and exits. Each command gets a page rendered from _COMMANDS_META;
    # unknown commands fall back to the overview.
    if handle_help(positional, lambda: _print_help(command)):
        sys.exit(0)

    app = App(env_override=env_override, ns_override=ns_override)
    try:
        handler = _COMMANDS.get(command)
        if not handler:
            print_error(f'Unknown command: {command}')
            print()
            show_help()
            sys.exit(1)
        handler(app, args)
    except KeyboardInterrupt:
        print()
    except RuntimeError as e:
        print_error(str(e))
        sys.exit(1)
