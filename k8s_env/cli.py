from __future__ import annotations
import os
import sys

from k8s_env import service
from k8s_env.utils import AppContext, ENV_FILE

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


def print_banner(ctx: AppContext) -> None:
    if not ctx.kubectl:
        return
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

def _use_global(ctx: AppContext) -> bool:
    return ctx.global_mode or not os.path.isfile(ctx.env_path)


def _try_activate_existing(ctx: AppContext) -> bool:
    # In global mode, offer existing profiles before running discovery
    if not _use_global(ctx):
        return False
    profiles = service.list_profiles()
    if not profiles:
        return False
    items = profiles + ['+ Discover new...']
    choice = pick('Global profiles', items)[0]
    if choice[0] >= len(profiles):
        return False
    service.activate_profile(profiles[choice[0]])
    print()
    print_status(f'Activated global profile {_BOLD}{profiles[choice[0]]}{_NC}')
    return True


def _save_discovered(ctx: AppContext, env: service.Env, label: str) -> None:
    # After discovery, save to global profile or local .k8s-env
    if _use_global(ctx):
        name = input('\nProfile name (lowercase kebab-case): ').strip()
        service.save_global(env, name)
        print()
        print_status(f'Saved global profile {_BOLD}{name}{_NC} → {label}')
    else:
        service.save_env(env, ctx)
        print()
        print_status(f'Set to {label}')


def cmd_use(ctx: AppContext) -> None:
    if _try_activate_existing(ctx):
        return

    entries = service.discover_local()
    if not entries:
        raise SystemExit('No namespaces found (checked microk8s, minikube, and kubectl contexts)')

    labels = [e.namespace for e in entries]
    groups = [e.group for e in entries]
    selected = entries[pick('Available namespaces', labels, groups=groups)[0][0]]

    env = service.Env(tool=selected.tool, context=selected.context, namespace=selected.namespace)
    _save_discovered(ctx, env, f'{_BOLD}{selected.group}{_NC} namespace: {_BOLD}{selected.namespace}{_NC}')


def cmd_use_remote(ctx: AppContext, host: str) -> None:
    if not host and _try_activate_existing(ctx):
        return
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

    env = service.Env(tool=selected.tool, ssh_host=host, namespace=selected.namespace)
    _save_discovered(ctx, env, f'{_YELLOW}{selected.tool} ssh{_NC} host: {_BOLD}{host}{_NC} namespace: {_BOLD}{selected.namespace}{_NC}')


def cmd_ctx(ctx: AppContext) -> None:
    # Instant one-liner showing active environment source and target
    service.load_env(ctx)
    env = ctx.env
    profile = service.active_profile_name()
    source = profile if ctx.env_path != ENV_FILE else 'local'
    parts = [env.tool]
    if env.ssh_host:
        parts.append(f'on {env.ssh_host}')
    if env.context:
        parts.append(f'on context: {env.context}')
    if not env.ssh_host and not env.context:
        parts.append('on local')
    print(f'{_CYAN}[{source}]{_NC} {" ".join(parts)} / {_BOLD}{env.namespace}{_NC}')


def cmd_namespaces(ctx: AppContext) -> None:
    service.require_env(ctx)
    print_banner(ctx)
    print(ctx.kubectl.get_namespaces_all(), end='')


def cmd_pods(ctx: AppContext, filter_text: str) -> None:
    service.require_env(ctx)
    print_banner(ctx)
    ns = ctx.namespace
    print_status(f'Pods in {_BOLD}{ns}{_NC}')
    output = ctx.kubectl.get_pods(ns)
    print_filtered(output, filter_text)


# -- Help ---------------------------------------------------------------------

def show_help(ctx: AppContext) -> None:
    print(f'{_BOLD}k8s-env{_NC} — Kubernetes environment helper\n')
    print(f'{_BOLD}Usage:{_NC} k8s-env <command> [args] [-n namespace] [-g]\n')
    print(f'{_BOLD}Environment:{_NC}')
    print('  use                    Pick namespace (local .k8s-env or global profile)')
    print('  use-remote <host>      Pick namespace from remote microk8s/minikube via SSH')
    print('  ctx                    Show active environment (no cluster queries)')
    print()
    print(f'{_BOLD}Inspection:{_NC}')
    print('  pods [filter]          List pods (filter by name)')
    print('  namespaces             List all namespaces')
    print()
    print(f'{_BOLD}Options:{_NC}')
    print('  -g, --global           Force global profile mode')
    print('  -n <namespace>         Override saved namespace')
    print('  -h, --help             Show this help')
    print()
    # Show active environment if one is saved
    if not ctx.env and os.path.isfile(ctx.env_path):
        service.load_env(ctx)
    if ctx.env:
        print_banner(ctx)
    else:
        print(f'{_DIM}No active environment set. Run: k8s-env use{_NC}')


# -- Main ---------------------------------------------------------------------

_COMMANDS = {
    'use':        lambda ctx, _arg: cmd_use(ctx),
    'use-remote': lambda ctx, arg: cmd_use_remote(ctx, arg),
    'ctx':        lambda ctx, _arg: cmd_ctx(ctx),
    'namespaces': lambda ctx, _arg: cmd_namespaces(ctx),
    'ns':         lambda ctx, _arg: cmd_namespaces(ctx),
    'pods':       lambda ctx, arg: cmd_pods(ctx, arg),
}


def main() -> None:
    # Parse flags and positional args (command + optional arg)
    ns_override = ''
    global_mode = False
    positional: list[str] = []
    show_help_flag = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '-n' and i + 1 < len(args):
            ns_override = args[i + 1]
            i += 2
        elif args[i] in ('-g', '--global'):
            global_mode = True
            i += 1
        elif args[i] in ('-h', '--help'):
            show_help_flag = True
            i += 1
        else:
            positional.append(args[i])
            i += 1

    ctx = AppContext(ns_override=ns_override, global_mode=global_mode)
    command = positional[0] if positional else ''
    arg = positional[1] if len(positional) > 1 else ''

    if show_help_flag or not command:
        show_help(ctx)
        return

    handler = _COMMANDS.get(command)
    if not handler:
        print_error(f'Unknown command: {command}')
        print()
        show_help(ctx)
        sys.exit(1)

    try:
        handler(ctx, arg)
    except KeyboardInterrupt:
        print()
    except RuntimeError as e:
        print_error(str(e))
        sys.exit(1)
