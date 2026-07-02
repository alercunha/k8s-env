"""The `status` command: a point-in-time health report for the active namespace.

Reads four cheap kubectl signals — nodes, pods, workloads, warning events — and
renders them answer-first: a coloured verdict, then what needs attention (with
the reason), then recent warnings, then summary counts.
"""

from __future__ import annotations

from k8s_env.context import AppContext
from k8s_env.ui import _BOLD, _DIM, _GREEN, _NC, _RED, _YELLOW, print_banner

# A pod is healthy in these phases; anything else needs attention.
_HEALTHY_POD = ('Running', 'Completed', 'Succeeded')
# Transient / in-progress states — a problem worth showing, but not a hard failure.
_SOFT_POD = ('Pending', 'ContainerCreating', 'PodInitializing')
_RESTART_WARN = 5


def _restarts(value: str) -> int:
    # RESTARTS column is already the leading token, but stay defensive.
    head = value.split()[0] if value else ''
    return int(head) if head.isdigit() else 0


def _pod_issue(ready: str, status: str, restarts: str) -> tuple[str, str] | None:
    """Classify a pod as ('hard'|'soft', reason), or None when healthy."""
    have, _, want = ready.partition('/')
    if status == 'Running':
        if want and have != want:
            return 'soft', 'not ready'
        if _restarts(restarts) >= _RESTART_WARN:
            return 'soft', 'flapping'
        return None
    # Completed/Succeeded are done (READY 0/1 expected); Terminating is rollout churn.
    if status in _HEALTHY_POD or status == 'Terminating':
        return None
    # "Init:1/2" is init progress (soft); "Init:Error"/"Init:CrashLoopBackOff" are failures.
    initializing = status.startswith('Init:') and status[5:6].isdigit()
    if status in _SOFT_POD or initializing:
        return 'soft', status
    return 'hard', status


def _pod_breakdown(pods: list[tuple]) -> str:
    counts: dict[str, int] = {}
    for _, _, status, _, _ in pods:
        counts[status.lower()] = counts.get(status.lower(), 0) + 1
    if len(counts) <= 1:
        return ''
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return '  ·  ' + ', '.join(f'{n} {s}' for s, n in ordered)


def _workload_counts(workloads: list[tuple]) -> str:
    counts: dict[str, int] = {}
    for kind, *_ in workloads:
        counts[kind] = counts.get(kind, 0) + 1
    if not counts:
        return '0'
    return ', '.join(f'{n} {kind}{"s" if n != 1 else ""}' for kind, n in sorted(counts.items()))


def _print_attention(pod_issues: list[tuple], degraded: list[tuple]) -> None:
    if not pod_issues and not degraded:
        return
    print(f'\n{_BOLD}Needs attention{_NC}')
    for severity, name, reason, restarts, age in pod_issues:
        mark = f'{_RED}✗{_NC}' if severity == 'hard' else f'{_YELLOW}⚠{_NC}'
        flap = f'  {_DIM}×{restarts}{_NC}' if restarts >= _RESTART_WARN else ''
        when = f'  {_DIM}{age}{_NC}' if age else ''
        print(f'  {mark} pod/{name}  {reason}{flap}{when}')
    for kind, name, ready, desired in degraded:
        print(f'  {_YELLOW}⚠{_NC} {kind}/{name}  {ready}/{desired} available')


def _classify_pods(pods: list[tuple]) -> list[tuple]:
    issues = []
    for name, ready, status, restarts, age in pods:
        issue = _pod_issue(ready, status, restarts)
        if issue:
            issues.append((issue[0], name, issue[1], _restarts(restarts), age))
    return issues


def _print_verdict(ns: str, count: int, hard: bool) -> None:
    if not count:
        print(f'{_GREEN}●{_NC}  {ns} is healthy')
        return
    color = _RED if hard else _YELLOW
    print(f'{color}●  {count} issue{"s" if count != 1 else ""} in {ns}{_NC}')


def _print_warnings(ctx: AppContext) -> None:
    # Best-effort: event reads can fail (e.g. RBAC) without invalidating the rest.
    try:
        events = ctx.kubectl.get_warning_events(ctx.namespace)
    except RuntimeError:
        return
    if not events:
        return
    print(f'\n{_BOLD}Recent warnings{_NC} {_DIM}(newest first){_NC}')
    for age, reason, obj, msg in events:
        if len(msg) > 80:
            msg = msg[:79] + '…'
        print(f'  {_DIM}{age:>4}{_NC}  {reason:<18} {obj}  {_DIM}{msg}{_NC}')


def cmd_status(ctx: AppContext) -> None:
    print_banner(ctx)
    ns = ctx.namespace
    k = ctx.kubectl

    nodes = k.get_nodes()
    pods = k.list_pod_status(ns)
    workloads = k.workload_health(ns)

    bad_nodes = [(name, st) for name, st in nodes if not st.startswith('Ready')]
    pod_issues = _classify_pods(pods)
    degraded = [w for w in workloads if w[2] < w[3]]

    # Verdict: red on any hard failure, yellow on soft-only issues, green when clean.
    # Count the leaf problems (pods + nodes); a degraded workload is the rollup of its
    # own bad pods, so counting both double-counts. Fall back to degraded only when a
    # workload is short with no bad pod to point at (e.g. replicas never scheduled).
    hard = bool(bad_nodes) or any(sev == 'hard' for sev, *_ in pod_issues)
    _print_verdict(ns, len(bad_nodes) + len(pod_issues) or len(degraded), hard)

    _print_attention(pod_issues, degraded)
    _print_warnings(ctx)

    print(f'\n{_BOLD}Summary{_NC}')
    print(f'  Nodes       {len(nodes) - len(bad_nodes)}/{len(nodes)} ready')
    print(f'  Pods        {len(pods)}{_pod_breakdown(pods)}')
    print(f'  Workloads   {_workload_counts(workloads)}')
