from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

from k8s_env import service
from k8s_env.args import first, handle_help, parse_args
from k8s_env.context import AppContext
from k8s_env.profile import EnvEntry
from k8s_env.service import Env
from k8s_env.trust import trust, untrust
from k8s_env.utils import CMD

# -- Colors -------------------------------------------------------------------

_RED = '\033[0;31m'
_GREEN = '\033[0;32m'
_YELLOW = '\033[1;33m'
_CYAN = '\033[0;36m'
_BOLD = '\033[1m'
_DIM = '\033[2m'
_NC = '\033[0m'


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


def print_banner(ctx: AppContext) -> None:
    k = ctx.kubectl
    name = k.tool_name
    ns = ctx.namespace
    if k.ssh_host:
        line = f'{_YELLOW}[{name} ssh]{_NC} host: {_BOLD}{k.ssh_host}{_NC} | namespace: {_BOLD}{ns}{_NC}'
    elif k.context:
        line = f'{_CYAN}[{name} remote]{_NC} context: {_BOLD}{k.context}{_NC} | namespace: {_BOLD}{ns}{_NC}'
    else:
        line = f'{_YELLOW}[{name} local]{_NC} namespace: {_BOLD}{ns}{_NC}'
    print(line, file=sys.stderr)


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

    # Display items, optionally grouped by adjacent group names (to stderr so
    # stdout stays clean for piping)
    print(f'{_BOLD}{title}:{_NC}', file=sys.stderr)
    current_group = ''
    indent = '    ' if groups else '  '
    for i, item in enumerate(items):
        if groups and groups[i] != current_group:
            if current_group:
                print(file=sys.stderr)
            current_group = groups[i]
            print(f'  {_YELLOW}{current_group}{_NC}', file=sys.stderr)
        print(f'{indent}{_CYAN}{i + 1}){_NC} {item}', file=sys.stderr)
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


# -- Context commands ---------------------------------------------------------

def _ctx_list(ctx: AppContext) -> None:
    entries = ctx.profiles.list()
    if not entries:
        print(f'{_DIM}No contexts saved. Run: {CMD} ctx add{_NC}')
        return
    active = ctx.profiles.active_name
    for e in entries:
        print(_format_entry(e, active))


def _ctx_add(ctx: AppContext) -> None:
    entries = service.discover_local()
    if not entries:
        raise SystemExit('No namespaces found (checked microk8s, minikube, and kubectl contexts)')

    labels = [e.namespace for e in entries]
    groups = [e.group for e in entries]
    selected = entries[pick('Available namespaces', labels, groups=groups)[0][0]]

    env = Env(tool=selected.tool, context=selected.context, namespace=selected.namespace)
    ctx.profiles.save(env)
    print()
    print_status(f'Set to {_BOLD}{selected.group}{_NC} namespace: {_BOLD}{selected.namespace}{_NC}')


def _ctx_add_remote(ctx: AppContext, host: str) -> None:
    if not host:
        host = _input('Remote host: ').strip()
        if not host:
            raise SystemExit('No host provided')

    entries = service.discover_remote(host)
    if not entries:
        raise SystemExit(f'No custom namespaces found on {host} (checked microk8s and minikube)')

    labels = [e.namespace for e in entries]
    groups = [e.tool for e in entries]
    selected = entries[pick(f'Namespaces on {host}', labels, groups=groups)[0][0]]

    env = Env(tool=selected.tool, ssh_host=host, namespace=selected.namespace)
    ctx.profiles.save(env)
    print()
    ns = selected.namespace
    print_status(f'Set to {_YELLOW}{selected.tool} ssh{_NC} host: {_BOLD}{host}{_NC} namespace: {_BOLD}{ns}{_NC}')


def _ctx_set(ctx: AppContext) -> None:
    entries = ctx.profiles.list()
    if not entries:
        raise SystemExit(f'No contexts saved. Run: {CMD} ctx add')
    if len(entries) == 1:
        print_status(f'Already on the only context: {_BOLD}{entries[0].name}{_NC}')
        return
    active = ctx.profiles.active_name
    items = [_format_entry(e, active) for e in entries]
    selected = entries[pick('Activate context', items)[0][0]]
    ctx.profiles.activate(selected.name)
    print()
    print_status(f'Activated context {_BOLD}{selected.name}{_NC}')


def _ctx_del(ctx: AppContext) -> None:
    entries = ctx.profiles.list()
    if not entries:
        raise SystemExit('No contexts saved')
    active = ctx.profiles.active_name
    items = [_format_entry(e, active) for e in entries]
    selected = entries[pick('Delete context', items)[0][0]]
    new_active = ctx.profiles.delete(selected.name)
    print()
    print_status(f'Deleted context {_BOLD}{selected.name}{_NC}')
    if new_active:
        print_status(f'Switched to context {_BOLD}{new_active.name}{_NC}')


def _ctx_use(ctx: AppContext) -> None:
    env = ctx.env
    if env.tool not in ('k8s', 'k8s-ssh'):
        print_status(f'{env.tool} does not use kubectl contexts — nothing to do.')
        return

    context_name = env.context
    ns = ctx.namespace
    print('This will set your kubectl config to:')
    print(f'  context:   {_BOLD}{context_name}{_NC}')
    print(f'  namespace: {_BOLD}{ns}{_NC}')
    raw = _input('\nProceed? [y/N]: ').strip().lower()
    if raw != 'y':
        raise SystemExit('Aborted')

    subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
    subprocess.run(['kubectl', 'config', 'set-context', context_name,
                     '--namespace', ns], check=True)
    print()
    print_status(f'kubectl now using context {_BOLD}{context_name}{_NC} / namespace {_BOLD}{ns}{_NC}')


_CTX_COMMANDS = {
    '':           lambda ctx, _arg: _ctx_list(ctx),
    'add':        lambda ctx, _arg: _ctx_add(ctx),
    'add-remote': lambda ctx, arg:  _ctx_add_remote(ctx, arg),
    'set':        lambda ctx, _arg: _ctx_set(ctx),
    'del':        lambda ctx, _arg: _ctx_del(ctx),
    'use':        lambda ctx, _arg: _ctx_use(ctx),
}


def cmd_ctx(ctx: AppContext, args: list[str]) -> None:
    ctx.check_trust()
    sub = first(args)
    handler = _CTX_COMMANDS.get(sub)
    if not handler:
        raise SystemExit(f'Unknown ctx subcommand: {sub}. Use: add, add-remote, set, del, use')
    handler(ctx, first(args[1:]))


def _format_entry(e: EnvEntry, active: str) -> str:
    env = e.env
    location = env.ssh_host or env.context or 'local'
    if e.name == active:
        return f'{_GREEN}[{e.name}]{_NC} {env.tool} on {location} / {env.namespace} {_GREEN}(active){_NC}'
    return f'{_DIM}[{e.name}] {env.tool} on {location} / {env.namespace}{_NC}'


# -- Other commands -----------------------------------------------------------

def _env_summary(env: Env) -> str:
    parts = [env.tool]
    if env.ssh_host:
        parts.append(f'on {_YELLOW}{env.ssh_host}{_NC}')
    elif env.context:
        parts.append(f'on context {env.context}')
    else:
        parts.append('on local')
    parts.append(f'namespace {env.namespace}')
    return ' / '.join(parts)


def cmd_allow(ctx: AppContext) -> None:
    print(f'{_BOLD}Trusting .k8s-env:{_NC}')
    for entry in ctx.profiles.list():
        print(f'  {_env_summary(entry.env)}')
    raw = _input('\nAllow? [y/N]: ').strip().lower()
    if raw != 'y':
        raise SystemExit('Aborted')
    for entry in ctx.profiles.list():
        trust(entry.path)
    print_status('Trusted .k8s-env in current directory')


def cmd_deny(ctx: AppContext) -> None:
    for entry in ctx.profiles.list():
        untrust(entry.path)
    print_status('Removed trust for .k8s-env in current directory')


def cmd_namespaces(ctx: AppContext) -> None:
    print_banner(ctx)
    print(ctx.kubectl.get_namespaces_all(), end='')


def cmd_pods(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    print_status(f'Pods in {_BOLD}{ns}{_NC}')
    print_filtered(ctx.kubectl.get_pods(ns), filter_text)


def cmd_services(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    print_status(f'Services in {_BOLD}{ns}{_NC}')
    print_filtered(ctx.kubectl.get_services(ns), filter_text)


def cmd_secrets(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    print_status(f'Secrets in {_BOLD}{ns}{_NC} {_DIM}(names only){_NC}')
    print_filtered(ctx.kubectl.get_secrets(ns), filter_text)


def cmd_cronjobs(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    print_status(f'CronJobs in {_BOLD}{ns}{_NC}')
    print_filtered(ctx.kubectl.get_cronjobs(ns), filter_text)


def cmd_events(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    print_status(f'Recent events in {_BOLD}{ns}{_NC}')
    # Show last 30 lines of sorted events
    output = ctx.kubectl.get_events(ns)
    lines = output.rstrip('\n').splitlines()
    trimmed = '\n'.join(lines[:1] + lines[-30:]) if len(lines) > 31 else output
    print_filtered(trimmed, filter_text)


def cmd_logs(ctx: AppContext, args: list[str]) -> None:
    follow, tail, rest = parse_args(args, {'-f': False, '--tail': 20})
    if tail == 0:
        raise SystemExit('--tail must be a positive number or -1 for all lines')
    filter_text = first(rest)
    print_banner(ctx)
    ns = ctx.namespace
    k = ctx.kubectl

    pods = k.list_pods(ns)
    if filter_text:
        pods = _filter(pods, filter_text)
    if not pods:
        print_warning(f'No pods found in {ns}')
        return

    if follow:
        # Pick one pod and stream its logs
        selected = pick('Follow logs for', pods, auto=True)[0][1]
        print_status(f'Tailing {_BOLD}{selected}{_NC} (Ctrl+C to stop)')
        k.follow_logs(selected, ns, tail=tail)
    else:
        for pod in pods:
            print()
            print(f'{_CYAN}{_BOLD}--- {pod} ---{_NC}')
            try:
                print(k.get_logs(pod, ns, tail=tail), end='')
            except RuntimeError:
                print(f'{_DIM}(no logs){_NC}')


def cmd_configmaps(ctx: AppContext, filter_text: str = '') -> None:
    print_banner(ctx)
    ns = ctx.namespace

    cms = ctx.kubectl.list_configmaps(ns)
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
    print(ctx.kubectl.get_configmap_yaml(cms[int(raw) - 1], ns), end='')


def cmd_exec(ctx: AppContext, args: list[str]) -> None:
    # Everything after '--' is a command to run in the pod; without it, open a shell
    if '--' in args:
        sep = args.index('--')
        filter_text, command = first(args[:sep]), args[sep + 1:]
    else:
        filter_text, command = first(args), []

    print_banner(ctx)
    ns = ctx.namespace
    k = ctx.kubectl

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


def _do_port_forward(ctx: AppContext, svc_name: str, svc_port: str) -> None:
    # Look up saved local port from env
    env = ctx.env
    pf_key = f'pf.{svc_name}.{svc_port}'
    saved_port = env.port_forwards.get(pf_key, '')
    default_port = saved_port or svc_port

    raw = _input(f'Local port [{default_port}]: ').strip()
    local_port = raw or default_port
    if not local_port.isdigit() or not 1 <= int(local_port) <= 65535:
        raise SystemExit(f'Invalid port: {local_port} (must be 1-65535)')

    # Save the port mapping
    env.port_forwards[pf_key] = local_port
    ctx.profiles.save(env)

    print_status(f'Forwarding localhost:{local_port} → svc/{svc_name}:{svc_port} (Ctrl+C to stop)')
    ctx.kubectl.port_forward(svc_name, ctx.namespace, local_port, svc_port)


def cmd_restart(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    k = ctx.kubectl

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


def cmd_port_forward(ctx: AppContext, filter_text: str = '') -> None:
    print_banner(ctx)
    if ctx.kubectl.ssh_host:
        raise SystemExit('port-forward is not supported over SSH sessions')

    pairs = ctx.kubectl.list_services_with_ports(ctx.namespace)
    if filter_text:
        pairs = _filter(pairs, filter_text, key=lambda x: x[0])
    if not pairs:
        print_warning(f'No services found in {ctx.namespace}')
        return

    svc_name, svc_port = _pick_service(pairs, f'Services in {ctx.namespace}', 'port')
    _do_port_forward(ctx, svc_name, svc_port)


def cmd_app(ctx: AppContext, filter_text: str = '') -> None:
    if ctx.kubectl.ssh_host:
        raise SystemExit('app is not supported over SSH sessions')

    if ctx.env.tool == 'minikube':
        print_warning("minikube doesn't expose NodePorts on localhost — using port-forward instead")
        cmd_port_forward(ctx, filter_text)
        return

    print_banner(ctx)
    pairs = ctx.kubectl.list_nodeport_services(ctx.namespace)
    if filter_text:
        pairs = _filter(pairs, filter_text, key=lambda x: x[0])
    if not pairs:
        print_warning(f'No NodePort services found in {ctx.namespace}')
        return

    _, node_port = _pick_service(pairs, f'NodePort services in {ctx.namespace}', 'nodePort')
    url = f'http://localhost:{node_port}'
    print_status(f'Opening {_BOLD}{url}{_NC}')
    open_url(url)


def cmd_dashboard(ctx: AppContext, args: list[str]) -> None:
    new_token, _ = parse_args(args, {'-t': False})

    if ctx.kubectl.ssh_host:
        raise SystemExit('dashboard is not supported over SSH sessions')

    k = ctx.kubectl
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


def cmd_describe(ctx: AppContext, arg: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace

    if not arg:
        resources = ctx.kubectl.list_resources(ns)
        if not resources:
            print_warning(f'No resources found in {ns}')
            return
        arg = pick(f'Resources in {ns}', resources, auto=True)[0][1]
    print(ctx.kubectl.describe(arg, ns), end='')


def cmd_status(ctx: AppContext) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    print()

    output = ctx.kubectl.get_resources_summary(ns)
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
    usage: str = ''                                 # full usage line (overrides name+args)
    options: tuple[tuple[str, str], ...] = ()       # (flag, description) pairs
    aliases: tuple[str, ...] = ()                   # short forms
    forms: tuple[tuple[str, str], ...] = ()         # extra invocation forms (label, summary)
    subcommands: tuple[tuple[str, str], ...] = ()   # (usage, summary) — ctx only


_GROUPS = ('Context', 'Inspection', 'Actions')

# Single source of truth for both the overview (show_help) and per-command help.
_COMMANDS_META = {
    # Context
    'ctx': _Cmd('Context', 'Manage saved contexts (shows them with no subcommand)', subcommands=(
        ('ctx',                   'Show saved contexts'),
        ('ctx add',               'Add local k8s namespace as context'),
        ('ctx add-remote [host]', 'Add remote k8s namespace via SSH'),
        ('ctx set',               'Switch active context'),
        ('ctx del',               'Delete a saved context'),
        ('ctx use',               'Apply active context to kubectl config'),
    )),
    'allow': _Cmd('Context', 'Trust .k8s-env in current directory'),
    'deny':  _Cmd('Context', 'Remove trust for .k8s-env in current directory'),
    # Inspection
    'pods':       _Cmd('Inspection', 'List pods (filter by name)', args='[filter]'),
    'logs':       _Cmd('Inspection', 'Show log output for pods in the current namespace',
                       args='[filter]', usage='logs [filter] [-f] [--tail N]', options=(
                           ('-f',             'Follow log output (streams one pod)'),
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
    'exec':         _Cmd('Actions', 'Open a shell in a pod (interactive picker)', args='[filter]',
                         usage='exec [filter] [-- cmd]', aliases=('sh',), forms=(
                             ('exec [filter] -- cmd', 'Run a command in a pod and return'),
                         )),
    'restart':      _Cmd('Actions', 'Restart deployments (interactive multi-picker)', args='[filter]'),
    'port-forward': _Cmd('Actions', 'Forward a service port (local only)', args='[filter]', aliases=('pf',)),
    'app':          _Cmd('Actions', 'Open a NodePort service in browser (local only)', args='[filter]'),
    'dashboard':    _Cmd('Actions', 'Open Headlamp dashboard in the browser', usage='dashboard [-t]', options=(
        ('-t', 'Generate a new access token (valid 1 year)'),
    )),
}

_ALIASES = {alias: name for name, c in _COMMANDS_META.items() for alias in c.aliases}


def _label(name: str, c: _Cmd) -> str:
    return f'{name} {c.args}'.strip()


def _rows() -> list[tuple[str, str, str]]:
    # Flatten the table into (group, label, summary) rows; ctx expands to its subcommands.
    rows: list[tuple[str, str, str]] = []
    for name, c in _COMMANDS_META.items():
        if c.subcommands:
            rows += [(c.group, usage, summary) for usage, summary in c.subcommands]
        else:
            rows.append((c.group, _label(name, c), c.summary))
            rows += [(c.group, label, summary) for label, summary in c.forms]
    return rows


def _aligned(pairs: list[tuple[str, str]], indent: str = '  ') -> list[str]:
    width = max(len(left) for left, _ in pairs) + 2
    return [f'{indent}{left.ljust(width)}{right}' for left, right in pairs]


def show_help() -> None:
    b, n = _BOLD, _NC
    rows = _rows()
    lines = [
        f'{b}{CMD}{n} — Kubernetes environment helper',
        '',
        f'{b}Usage:{n} {CMD} <command> [args] [-n namespace]',
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
    lines = [f'{b}Usage:{n} {CMD} {c.usage or _label(name, c)}', '', c.summary]
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
    # Context
    'ctx':          lambda ctx, args:  cmd_ctx(ctx, args),
    'allow':        lambda ctx, _args: cmd_allow(ctx),
    'deny':         lambda ctx, _args: cmd_deny(ctx),
    # Inspection
    'pods':         lambda ctx, args:  cmd_pods(ctx, first(args)),
    'logs':         lambda ctx, args:  cmd_logs(ctx, args),
    'services':     lambda ctx, args:  cmd_services(ctx, first(args)),
    'svc':          lambda ctx, args:  cmd_services(ctx, first(args)),
    'namespaces':   lambda ctx, _args: cmd_namespaces(ctx),
    'ns':           lambda ctx, _args: cmd_namespaces(ctx),
    'events':       lambda ctx, args:  cmd_events(ctx, first(args)),
    'configmaps':   lambda ctx, args:  cmd_configmaps(ctx, first(args)),
    'cm':           lambda ctx, args:  cmd_configmaps(ctx, first(args)),
    'secrets':      lambda ctx, args:  cmd_secrets(ctx, first(args)),
    'cronjobs':     lambda ctx, args:  cmd_cronjobs(ctx, first(args)),
    'cj':           lambda ctx, args:  cmd_cronjobs(ctx, first(args)),
    'status':       lambda ctx, _args: cmd_status(ctx),
    'st':           lambda ctx, _args: cmd_status(ctx),
    'describe':     lambda ctx, args:  cmd_describe(ctx, first(args)),
    'desc':         lambda ctx, args:  cmd_describe(ctx, first(args)),
    # Actions
    'exec':         lambda ctx, args:  cmd_exec(ctx, args),
    'sh':           lambda ctx, args:  cmd_exec(ctx, args),
    'restart':      lambda ctx, args:  cmd_restart(ctx, first(args)),
    'port-forward': lambda ctx, args:  cmd_port_forward(ctx, first(args)),
    'pf':           lambda ctx, args:  cmd_port_forward(ctx, first(args)),
    'app':          lambda ctx, args:  cmd_app(ctx, first(args)),
    'dashboard':    lambda ctx, args:  cmd_dashboard(ctx, args),
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

    ns_override, positional = parse_args(head, {'-n': ''})

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

    ctx = AppContext(ns_override=ns_override)
    try:
        handler = _COMMANDS.get(command)
        if not handler:
            print_error(f'Unknown command: {command}')
            print()
            show_help()
            sys.exit(1)
        handler(ctx, args)
    except KeyboardInterrupt:
        print()
    except RuntimeError as e:
        print_error(str(e))
        sys.exit(1)
