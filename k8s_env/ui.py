"""Terminal presentation primitives shared by the CLI and the status report."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from k8s_env.context import AppContext

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
