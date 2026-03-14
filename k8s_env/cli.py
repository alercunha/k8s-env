from __future__ import annotations
import shutil
import subprocess
import sys

from k8s_env import service
from k8s_env.profile import EnvEntry, Profiles
from k8s_env.service import Env
from k8s_env.context import AppContext
from k8s_env.trust import trust, untrust

# -- Colors -------------------------------------------------------------------

_RED = '\033[0;31m'
_GREEN = '\033[0;32m'
_YELLOW = '\033[1;33m'
_CYAN = '\033[0;36m'
_BOLD = '\033[1m'
_DIM = '\033[2m'
_NC = '\033[0m'


def print_status(msg: str) -> None:
    print(f'{_GREEN}[INFO]{_NC} {msg}')


def print_warning(msg: str) -> None:
    print(f'{_YELLOW}[WARN]{_NC} {msg}')


def print_error(msg: str) -> None:
    print(f'{_RED}[ERROR]{_NC} {msg}', file=sys.stderr)


def open_url(url: str) -> None:
    for cmd in ('xdg-open', 'open'):
        if shutil.which(cmd):
            subprocess.Popen([cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


def print_filtered(output: str, filter_text: str) -> None:
    lines = output.rstrip('\n').splitlines()
    if not lines:
        return
    if not filter_text:
        print(output, end='')
        return
    # Always show header row, filter the rest case-insensitively
    print(lines[0])
    lower = filter_text.lower()
    for line in lines[1:]:
        if lower in line.lower():
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
        raw = input(f'Select [1-{len(items)}, comma-separated or \'all\']: ')
    else:
        raw = input(f'Select [1-{len(items)}]: ')

    if multi and raw.strip().lower() == 'all':
        return list(enumerate(items))

    # Parse comma-separated selections, validate each
    selected: list[tuple[int, str]] = []
    for part in raw.split(','):
        part = part.strip()
        if not part.isdigit() or not (1 <= int(part) <= len(items)):
            raise SystemExit(f'Invalid selection: {part}')
        idx = int(part) - 1
        selected.append((idx, items[idx]))

    if not selected:
        raise SystemExit('No selection made')
    return selected


# -- Commands -----------------------------------------------------------------

def cmd_use(ctx: AppContext) -> None:
    entries = service.discover_local()
    if not entries:
        raise SystemExit('No namespaces found (checked microk8s, minikube, and kubectl contexts)')

    labels = [e.namespace for e in entries]
    groups = [e.group for e in entries]
    selected = entries[pick('Available namespaces', labels, groups=groups)[0][0]]

    env = Env(tool=selected.tool, context=selected.context, namespace=selected.namespace)
    entry = ctx.profiles.save(env)
    trust(entry.path)
    print()
    print_status(f'Set to {_BOLD}{selected.group}{_NC} namespace: {_BOLD}{selected.namespace}{_NC}')


def cmd_use_remote(ctx: AppContext, host: str) -> None:
    if not host:
        host = input('Remote host: ').strip()
        if not host:
            raise SystemExit('No host provided')

    entries = service.discover_remote(host)
    if not entries:
        raise SystemExit(f'No custom namespaces found on {host} (checked microk8s and minikube)')

    labels = [e.namespace for e in entries]
    groups = [e.tool for e in entries]
    selected = entries[pick(f'Namespaces on {host}', labels, groups=groups)[0][0]]

    env = Env(tool=selected.tool, ssh_host=host, namespace=selected.namespace)
    entry = ctx.profiles.save(env)
    trust(entry.path)
    print()
    print_status(f'Set to {_YELLOW}{selected.tool} ssh{_NC} host: {_BOLD}{host}{_NC} namespace: {_BOLD}{selected.namespace}{_NC}')


def cmd_ctx(ctx: AppContext) -> None:
    # Instant one-liner showing active environment source and target
    env = ctx.env
    active = ctx.profiles.active_name
    source = active if active else 'local'
    parts = [env.tool]
    if env.ssh_host:
        parts.append(f'on {env.ssh_host}')
    if env.context:
        parts.append(f'on context: {env.context}')
    if not env.ssh_host and not env.context:
        parts.append('on local')
    print(f'{_CYAN}[{source}]{_NC} {" ".join(parts)} / {_BOLD}{env.namespace}{_NC}')


def cmd_allow(ctx: AppContext) -> None:
    trust(ctx.profiles.active.path)
    print_status('Trusted .k8s-env in current directory')


def cmd_deny(ctx: AppContext) -> None:
    untrust(ctx.profiles.active.path)
    print_status('Removed trust for .k8s-env in current directory')


def _entry_label(e: EnvEntry, active: str) -> str:
    # Format: "name — tool on location / namespace"
    env = e.env
    location = env.ssh_host or env.context or 'local'
    marker = f' {_GREEN}(active){_NC}' if e.name == active else ''
    return f'{e.name} {_DIM}— {env.tool} on {location} / {env.namespace}{_NC}{marker}'


def _profile_list(ctx: AppContext) -> None:
    entries = ctx.profiles.list()
    if not entries:
        print(f'{_DIM}No profiles saved. Run: k8s-env profile init{_NC}')
        return
    active = ctx.profiles.active_name
    print(f'{_BOLD}Profiles:{_NC}')
    for e in entries:
        print(f'  {_entry_label(e, active)}')


def _profile_init(ctx: AppContext) -> None:
    entry = ctx.profiles.init_multi()
    trust(entry.path)
    print_status(f'Initialized profiles with {_BOLD}{entry.name}{_NC}')


def _profile_activate(ctx: AppContext) -> None:
    entries = ctx.profiles.list()
    if not entries:
        raise SystemExit('No profiles saved. Run: k8s-env profile init')
    active = ctx.profiles.active_name
    items = [_entry_label(e, active) for e in entries]
    selected = entries[pick('Activate profile', items)[0][0]]
    ctx.profiles.activate(selected.name)
    trust(ctx.profiles.active.path)
    print()
    print_status(f'Activated profile {_BOLD}{selected.name}{_NC}')


def _profile_delete(ctx: AppContext) -> None:
    entries = ctx.profiles.list()
    if not entries:
        raise SystemExit('No profiles saved')
    active = ctx.profiles.active_name
    items = [_entry_label(e, active) for e in entries]
    selected = entries[pick('Delete profile', items)[0][0]]
    ctx.profiles.delete(selected.name)
    print()
    print_status(f'Deleted profile {_BOLD}{selected.name}{_NC}')


_PROFILE_COMMANDS = {
    '':         lambda ctx: _profile_list(ctx),
    'list':     lambda ctx: _profile_list(ctx),
    'init':     lambda ctx: _profile_init(ctx),
    'activate': lambda ctx: _profile_activate(ctx),
    'delete':   lambda ctx: _profile_delete(ctx),
}


def cmd_profile(ctx: AppContext, sub: str) -> None:
    handler = _PROFILE_COMMANDS.get(sub)
    if not handler:
        raise SystemExit(f'Unknown profile subcommand: {sub}. Use: list, init, activate, delete')
    handler(ctx)


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
        lower = filter_text.lower()
        pods = [p for p in pods if lower in p.lower()]
    if not pods:
        print_warning(f'No pods found in {ns}')
        return

    if ctx.follow:
        # Pick one pod and stream its logs
        selected = pick('Follow logs for', pods, auto=True)[0][1]
        print_status(f'Tailing {_BOLD}{selected}{_NC} (Ctrl+C to stop)')
        k.follow_logs(selected, ns)
    else:
        # Show last 20 lines per pod
        for pod in pods:
            print()
            print(f'{_CYAN}{_BOLD}--- {pod} ---{_NC}')
            try:
                print(k.get_logs(pod, ns), end='')
            except RuntimeError:
                print(f'{_DIM}(no logs){_NC}')


def cmd_configmaps(ctx: AppContext) -> None:
    print_banner(ctx)
    ns = ctx.namespace

    cms = ctx.kubectl.list_configmaps(ns)
    if not cms:
        print_warning(f'No configmaps found in {ns}')
        return

    print(f'{_BOLD}ConfigMaps in {ns}:{_NC}')
    for i, cm in enumerate(cms):
        print(f'  {_CYAN}{i + 1}){_NC} {cm}')
    print()
    raw = input(f'View configmap? [1-{len(cms)}, enter to skip]: ').strip()
    if not raw:
        return
    if not raw.isdigit() or not (1 <= int(raw) <= len(cms)):
        raise SystemExit(f'Invalid selection: {raw}')
    print()
    print(ctx.kubectl.get_configmap_yaml(cms[int(raw) - 1], ns), end='')


def cmd_exec(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    k = ctx.kubectl

    pods = k.list_pods(ns)
    if filter_text:
        lower = filter_text.lower()
        pods = [p for p in pods if lower in p.lower()]
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

    raw = input(f'Local port [{default_port}]: ').strip()
    local_port = raw or default_port
    if not local_port.isdigit() or not (1 <= int(local_port) <= 65535):
        raise SystemExit(f'Invalid port: {local_port} (must be 1-65535)')

    # Save the port mapping
    env.port_forwards[pf_key] = local_port
    entry = ctx.profiles.save(env)
    trust(entry.path)

    print_status(f'Forwarding localhost:{local_port} → svc/{svc_name}:{svc_port} (Ctrl+C to stop)')
    ctx.kubectl.port_forward(svc_name, ctx.namespace, local_port, svc_port)


def cmd_restart(ctx: AppContext, filter_text: str) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    k = ctx.kubectl

    deployments = k.list_deployments(ns)
    if filter_text:
        lower = filter_text.lower()
        deployments = [d for d in deployments if lower in d.lower()]
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


def cmd_port_forward(ctx: AppContext) -> None:
    print_banner(ctx)
    if ctx.kubectl.ssh_host:
        raise SystemExit('port-forward is not supported over SSH sessions')

    pairs = ctx.kubectl.list_services_with_ports(ctx.namespace)
    if not pairs:
        print_warning(f'No services found in {ctx.namespace}')
        return

    svc_name, svc_port = _pick_service(pairs, f'Services in {ctx.namespace}', 'port')
    _do_port_forward(ctx, svc_name, svc_port)


def cmd_app(ctx: AppContext) -> None:
    if ctx.kubectl.ssh_host:
        raise SystemExit('app is not supported over SSH sessions')

    if ctx.env.tool == 'minikube':
        print_warning("minikube doesn't expose NodePorts on localhost — using port-forward instead")
        cmd_port_forward(ctx)
        return

    print_banner(ctx)
    pairs = ctx.kubectl.list_nodeport_services(ctx.namespace)
    if not pairs:
        print_warning(f'No NodePort services found in {ctx.namespace}')
        return

    svc_name, node_port = _pick_service(pairs, f'NodePort services in {ctx.namespace}', 'nodePort')
    url = f'http://localhost:{node_port}'
    print_status(f'Opening {_BOLD}{url}{_NC}')
    open_url(url)


def cmd_dashboard(ctx: AppContext) -> None:
    if ctx.kubectl.ssh_host:
        raise SystemExit('dashboard is not supported over SSH sessions')

    k = ctx.kubectl
    ns = k.find_namespace('headlamp')
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

    not_ready = [l for l in pod_lines if 'Running' not in l and 'Completed' not in l]
    if not_ready:
        print_warning('Pods not running:')
        for line in not_ready:
            print(f'  {line.removeprefix("pod/")}')
    else:
        print_status('All pods running')


# -- Help ---------------------------------------------------------------------

def show_help() -> None:
    print(f'{_BOLD}k8s-env{_NC} — Kubernetes environment helper\n')
    print(f'{_BOLD}Usage:{_NC} k8s-env <command> [args] [-n namespace]\n')
    print(f'{_BOLD}Environment:{_NC}')
    print('  use                    Discover local k8s runtimes and set active namespace')
    print('  use-remote <host>      Discover k8s runtimes on remote host via SSH and set active namespace')
    print('  ctx                    Show active environment (no cluster queries)')
    print('  allow                  Trust .k8s-env in current directory')
    print('  deny                   Remove trust for .k8s-env in current directory')
    print()
    print(f'{_BOLD}Profiles:{_NC}')
    print('  profile                List saved profiles')
    print('  profile init           Initialize multi-profile structure')
    print('  profile activate       Switch to a different profile')
    print('  profile delete         Delete a saved profile')
    print()
    print(f'{_BOLD}Inspection:{_NC}')
    print('  pods [filter]          List pods (filter by name)')
    print('  logs [filter] [-f]     Show last 20 log lines per pod (-f to follow)')
    print('  services [filter]      List services')
    print('  namespaces             List all namespaces')
    print('  events [filter]        Show recent events')
    print('  configmaps             List configmaps (interactive viewer)')
    print('  secrets [filter]       List secret names')
    print('  cronjobs [filter]      List cronjobs')
    print('  status                 Show cluster and namespace stats')
    print('  describe [resource]    Describe a resource (picker if omitted)')
    print()
    print(f'{_BOLD}Actions:{_NC}')
    print('  exec [filter]          Open a shell in a pod (interactive picker)')
    print('  restart [filter]       Restart deployments (interactive multi-picker)')
    print('  port-forward           Forward a service port (local only)')
    print('  app                    Open a NodePort service in browser (local only)')
    print('  dashboard [-t]         Open Headlamp dashboard (-t to generate new token)')
    print()
    print(f'{_BOLD}Options:{_NC}')
    print('  -f                     Follow logs (used with logs)')
    print('  -t                     Generate new token (used with dashboard)')
    print('  -n <namespace>         Override saved namespace')
    print('  -h, --help             Show this help')


# -- Main ---------------------------------------------------------------------

_COMMANDS = {
    'use':          lambda ctx, _arg: cmd_use(ctx),
    'use-remote':   lambda ctx, arg:  cmd_use_remote(ctx, arg),
    'ctx':          lambda ctx, _arg: cmd_ctx(ctx),
    'allow':        lambda ctx, _arg: cmd_allow(ctx),
    'deny':         lambda ctx, _arg: cmd_deny(ctx),
    'profile':      lambda ctx, arg:  cmd_profile(ctx, arg),
    'namespaces':   lambda ctx, _arg: cmd_namespaces(ctx),
    'ns':           lambda ctx, _arg: cmd_namespaces(ctx),
    'pods':         lambda ctx, arg:  cmd_pods(ctx, arg),
    'logs':         lambda ctx, arg:  cmd_logs(ctx, arg),
    'services':     lambda ctx, arg:  cmd_services(ctx, arg),
    'svc':          lambda ctx, arg:  cmd_services(ctx, arg),
    'secrets':      lambda ctx, arg:  cmd_secrets(ctx, arg),
    'cronjobs':     lambda ctx, arg:  cmd_cronjobs(ctx, arg),
    'cj':           lambda ctx, arg:  cmd_cronjobs(ctx, arg),
    'events':       lambda ctx, arg:  cmd_events(ctx, arg),
    'configmaps':   lambda ctx, _arg: cmd_configmaps(ctx),
    'cm':           lambda ctx, _arg: cmd_configmaps(ctx),
    'exec':         lambda ctx, arg:  cmd_exec(ctx, arg),
    'sh':           lambda ctx, arg:  cmd_exec(ctx, arg),
    'describe':     lambda ctx, arg:  cmd_describe(ctx, arg),
    'desc':         lambda ctx, arg:  cmd_describe(ctx, arg),
    'restart':      lambda ctx, arg:  cmd_restart(ctx, arg),
    'port-forward': lambda ctx, _arg: cmd_port_forward(ctx),
    'pf':           lambda ctx, _arg: cmd_port_forward(ctx),
    'app':          lambda ctx, _arg: cmd_app(ctx),
    'dashboard':    lambda ctx, _arg: cmd_dashboard(ctx),
    'status':       lambda ctx, _arg: cmd_status(ctx),
    'st':           lambda ctx, _arg: cmd_status(ctx),
}


def main() -> None:
    # Parse flags and positional args (command + optional arg)
    ns_override = ''
    follow = False
    new_token = False
    positional: list[str] = []
    show_help_flag = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '-n' and i + 1 < len(args):
            ns_override = args[i + 1]
            i += 2
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
    arg = positional[1] if len(positional) > 1 else ''

    if show_help_flag or not command:
        show_help()
        return

    handler = _COMMANDS.get(command)
    if not handler:
        print_error(f'Unknown command: {command}')
        print()
        show_help()
        sys.exit(1)

    ctx = AppContext(ns_override=ns_override, follow=follow, new_token=new_token)
    try:
        handler(ctx, arg)
    except KeyboardInterrupt:
        print()
    except RuntimeError as e:
        print_error(str(e))
        sys.exit(1)
