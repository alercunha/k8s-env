from __future__ import annotations

import shutil
import subprocess
import sys

from k8s_env import service
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
    return input(prompt)


def print_status(msg: str) -> None:
    print(f'{_GREEN}[INFO]{_NC} {msg}')


def print_warning(msg: str) -> None:
    print(f'{_YELLOW}[WARN]{_NC} {msg}')


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
        print(f'{_YELLOW}[{name} ssh]{_NC} host: {_BOLD}{k.ssh_host}{_NC} | namespace: {_BOLD}{ns}{_NC}')
    elif k.context:
        print(f'{_CYAN}[{name} remote]{_NC} context: {_BOLD}{k.context}{_NC} | namespace: {_BOLD}{ns}{_NC}')
    else:
        print(f'{_YELLOW}[{name} local]{_NC} namespace: {_BOLD}{ns}{_NC}')


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
        print(f'{_BOLD}{title}:{_NC} {items[0]}')
        return [(0, items[0])]

    # Display items, optionally grouped by adjacent group names
    print(f'{_BOLD}{title}:{_NC}')
    current_group = ''
    indent = '    ' if groups else '  '
    for i, item in enumerate(items):
        if groups and groups[i] != current_group:
            if current_group:
                print()
            current_group = groups[i]
            print(f'  {_YELLOW}{current_group}{_NC}')
        print(f'{indent}{_CYAN}{i + 1}){_NC} {item}')
    print()

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
    ctx.check_trust()
    entries = ctx.profiles.list()
    if not entries:
        print(f'{_DIM}No contexts saved. Run: {CMD} ctx add{_NC}')
        return
    active = ctx.profiles.active_name
    for e in entries:
        env = e.env
        location = env.ssh_host or env.context or 'local'
        if e.name == active:
            print(f'{_GREEN}[{e.name}]{_NC} {env.tool} on {location} / {env.namespace} {_GREEN}(active){_NC}')
        else:
            print(f'{_DIM}[{e.name}] {env.tool} on {location} / {env.namespace}{_NC}')


def _ctx_add(ctx: AppContext) -> None:
    ctx.check_trust()
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
    ctx.check_trust()
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
    ctx.check_trust()
    entries = ctx.profiles.list()
    if not entries:
        raise SystemExit(f'No contexts saved. Run: {CMD} ctx add')
    if len(entries) == 1:
        print_status(f'Already on the only context: {_BOLD}{entries[0].name}{_NC}')
        return
    active = ctx.profiles.active_name
    items = [_entry_label(e, active) for e in entries]
    selected = entries[pick('Activate context', items)[0][0]]
    ctx.profiles.activate(selected.name)
    print()
    print_status(f'Activated context {_BOLD}{selected.name}{_NC}')


def _ctx_del(ctx: AppContext) -> None:
    ctx.check_trust()
    entries = ctx.profiles.list()
    if not entries:
        raise SystemExit('No contexts saved')
    active = ctx.profiles.active_name
    items = [_entry_label(e, active) for e in entries]
    selected = entries[pick('Delete context', items)[0][0]]
    new_active = ctx.profiles.delete(selected.name)
    print()
    print_status(f'Deleted context {_BOLD}{selected.name}{_NC}')
    if new_active:
        print_status(f'Switched to context {_BOLD}{new_active.name}{_NC}')


_CTX_COMMANDS = {
    '':           lambda ctx, _arg: _ctx_list(ctx),
    'add':        lambda ctx, _arg: _ctx_add(ctx),
    'add-remote': lambda ctx, arg:  _ctx_add_remote(ctx, arg),
    'set':        lambda ctx, _arg: _ctx_set(ctx),
    'del':        lambda ctx, _arg: _ctx_del(ctx),
}


def cmd_ctx(ctx: AppContext, sub: str, extra: str) -> None:
    handler = _CTX_COMMANDS.get(sub)
    if not handler:
        raise SystemExit(f'Unknown ctx subcommand: {sub}. Use: add, add-remote, set, del')
    handler(ctx, extra)


def _entry_label(e: EnvEntry, active: str) -> str:
    env = e.env
    location = env.ssh_host or env.context or 'local'
    marker = f' {_GREEN}(active){_NC}' if e.name == active else ''
    return f'{e.name} {_DIM}— {env.tool} on {location} / {env.namespace}{_NC}{marker}'


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


def cmd_logs(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    k = ctx.kubectl

    pods = k.list_pods(ns)
    if filter_text:
        pods = _filter(pods, filter_text)
    if not pods:
        print_warning(f'No pods found in {ns}')
        return

    if ctx.follow:
        # Pick one pod and stream its logs
        selected = pick('Follow logs for', pods, auto=True)[0][1]
        print_status(f'Tailing {_BOLD}{selected}{_NC} (Ctrl+C to stop)')
        k.follow_logs(selected, ns, tail=ctx.tail)
    else:
        for pod in pods:
            print()
            print(f'{_CYAN}{_BOLD}--- {pod} ---{_NC}')
            try:
                print(k.get_logs(pod, ns, tail=ctx.tail), end='')
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


def cmd_exec(ctx: AppContext, filter_text: str) -> None:
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


def cmd_dashboard(ctx: AppContext) -> None:
    if ctx.kubectl.ssh_host:
        raise SystemExit('dashboard is not supported over SSH sessions')

    k = ctx.kubectl
    ns = k.find_namespace_exact('headlamp')
    if not ns:
        raise SystemExit('Headlamp namespace not found')

    pairs = k.list_nodeport_services(ns)
    if not pairs:
        raise SystemExit(f'No NodePort service found in {ns}')

    if ctx.new_token:
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

def show_help() -> None:
    print(f'{_BOLD}{CMD}{_NC} — Kubernetes environment helper\n')
    print(f'{_BOLD}Usage:{_NC} {CMD} <command> [args] [-n namespace]\n')
    print(f'{_BOLD}Context:{_NC}')
    print('  ctx                    Show saved contexts')
    print('  ctx add                Add local k8s namespace as context')
    print('  ctx add-remote [host]  Add remote k8s namespace via SSH')
    print('  ctx set                Switch active context')
    print('  ctx del                Delete a saved context')
    print('  allow                  Trust .k8s-env in current directory')
    print('  deny                   Remove trust for .k8s-env in current directory')
    print()
    print(f'{_BOLD}Inspection:{_NC}')
    print('  pods [filter]          List pods (filter by name)')
    print('  logs [filter] [-f]     Show log lines per pod (-f to follow, --tail N)')
    print('  services [filter]      List services')
    print('  namespaces             List all namespaces')
    print('  events [filter]        Show recent events')
    print('  configmaps [filter]    List configmaps (interactive viewer)')
    print('  secrets [filter]       List secret names')
    print('  cronjobs [filter]      List cronjobs')
    print('  status                 Show cluster and namespace stats')
    print('  describe [resource]    Describe a resource (picker if omitted)')
    print()
    print(f'{_BOLD}Actions:{_NC}')
    print('  exec [filter]          Open a shell in a pod (interactive picker)')
    print('  restart [filter]       Restart deployments (interactive multi-picker)')
    print('  port-forward [filter]  Forward a service port (local only)')
    print('  app [filter]           Open a NodePort service in browser (local only)')
    print('  dashboard [-t]         Open Headlamp dashboard (-t to generate new token)')
    print()
    print(f'{_BOLD}Options:{_NC}')
    print('  -f                     Follow logs (used with logs)')
    print('  --tail <lines>         Number of log lines to show (default 20, -1 for all)')
    print('  -t                     Generate new token (used with dashboard)')
    print('  -n <namespace>         Override saved namespace')
    print('  -h, --help             Show this help')


# -- Main ---------------------------------------------------------------------

_COMMANDS: dict[str, object] = {
    'ctx':          lambda ctx, args: cmd_ctx(ctx, args[0] if args else '', args[1] if len(args) > 1 else ''),
    'allow':        lambda ctx, _args: cmd_allow(ctx),
    'deny':         lambda ctx, _args: cmd_deny(ctx),
    'namespaces':   lambda ctx, _args: cmd_namespaces(ctx),
    'ns':           lambda ctx, _args: cmd_namespaces(ctx),
    'pods':         lambda ctx, args:  cmd_pods(ctx, args[0] if args else ''),
    'logs':         lambda ctx, args:  cmd_logs(ctx, args[0] if args else ''),
    'services':     lambda ctx, args:  cmd_services(ctx, args[0] if args else ''),
    'svc':          lambda ctx, args:  cmd_services(ctx, args[0] if args else ''),
    'secrets':      lambda ctx, args:  cmd_secrets(ctx, args[0] if args else ''),
    'cronjobs':     lambda ctx, args:  cmd_cronjobs(ctx, args[0] if args else ''),
    'cj':           lambda ctx, args:  cmd_cronjobs(ctx, args[0] if args else ''),
    'events':       lambda ctx, args:  cmd_events(ctx, args[0] if args else ''),
    'configmaps':   lambda ctx, args:  cmd_configmaps(ctx, args[0] if args else ''),
    'cm':           lambda ctx, args:  cmd_configmaps(ctx, args[0] if args else ''),
    'exec':         lambda ctx, args:  cmd_exec(ctx, args[0] if args else ''),
    'sh':           lambda ctx, args:  cmd_exec(ctx, args[0] if args else ''),
    'describe':     lambda ctx, args:  cmd_describe(ctx, args[0] if args else ''),
    'desc':         lambda ctx, args:  cmd_describe(ctx, args[0] if args else ''),
    'restart':      lambda ctx, args:  cmd_restart(ctx, args[0] if args else ''),
    'port-forward': lambda ctx, args:  cmd_port_forward(ctx, args[0] if args else ''),
    'pf':           lambda ctx, args:  cmd_port_forward(ctx, args[0] if args else ''),
    'app':          lambda ctx, args:  cmd_app(ctx, args[0] if args else ''),
    'dashboard':    lambda ctx, _args: cmd_dashboard(ctx),
    'status':       lambda ctx, _args: cmd_status(ctx),
    'st':           lambda ctx, _args: cmd_status(ctx),
}


def _parse_tail(value: str) -> int:
    try:
        tail = int(value)
    except ValueError:
        raise SystemExit(f'--tail requires an integer, got: {value}') from None
    if tail == 0:
        raise SystemExit('--tail must be a positive number or -1 for all lines')
    return tail


def main() -> None:
    # Parse flags and positional args
    ns_override = ''
    follow = False
    new_token = False
    tail = 20
    positional: list[str] = []
    show_help_flag = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '-n' and i + 1 < len(args):
            ns_override = args[i + 1]
            i += 2
        elif args[i] == '--tail' and i + 1 < len(args):
            tail = _parse_tail(args[i + 1])
            i += 2
        elif args[i] == '--tail':
            raise SystemExit('--tail requires a value')
        elif args[i] == '-f':
            follow = True
            i += 1
        elif args[i] == '-t':
            new_token = True
            i += 1
        elif args[i] in ('-h', '--help'):
            show_help_flag = True
            i += 1
        else:
            positional.append(args[i])
            i += 1

    command = positional[0] if positional else ''

    if show_help_flag or not command:
        show_help()
        return

    handler = _COMMANDS.get(command)
    if not handler:
        print_error(f'Unknown command: {command}')
        print()
        show_help()
        sys.exit(1)

    ctx = AppContext(ns_override=ns_override, follow=follow, new_token=new_token, tail=tail)
    try:
        handler(ctx, positional[1:])
    except KeyboardInterrupt:
        print()
    except RuntimeError as e:
        print_error(str(e))
        sys.exit(1)
