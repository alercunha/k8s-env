# k8s-env

Kubernetes environment manager — interactive CLI for switching between k8s namespaces across microk8s, minikube, kubectl contexts, and remote hosts via SSH.

## Checks

Run before every commit. Must pass clean.

```
uvx pylint k8s_env/
```

## Project structure

```
k8s-env              # Entry point script (#!/usr/bin/env python3)
k8s_env/             # Main package (stdlib only — no third-party imports)
  args.py            # Generic flag parser (parse_args, with_help, first)
  cli.py             # Command dispatcher, interactive picker, ctx subcommands, cmd_* handlers
  status.py          # The `status` command — namespace health report (cmd_status)
  ui.py              # Terminal presentation: ANSI colors, print_* helpers, print_banner, _input
  context.py         # AppContext — holds namespace override, trust check, lazy kubectl init
  k8s.py             # KubeCtl ABC + MicroK8s, MiniKube, K8sContext, SshKubeCtl implementations
  service.py         # Env config class (load/save .k8s-env files), namespace discovery
  profile.py         # Multi-profile management (EnvEntry, Profiles)
  trust.py           # SHA256-based trust system for .k8s-env files
  utils.py           # Validators, constants (ENV_FILE, CMD, SYSTEM_NAMESPACES)
contrib/
  k8s                # Standalone bash alternative (drop-in replacement, limited features)
  README.md          # Differences between bash and Python versions
assets/
  demo.tape          # VHS script for the README demo gif
  record.sh          # Regenerates demo.gif against an isolated, seeded cluster
  seed.yaml          # Synthetic namespaces/workloads used by the demo
  demo.gif           # Rendered demo embedded in README.md
pyproject.toml       # Project metadata, pylint configuration
```

## Key constraints

- **Stdlib only**: The `k8s_env/` package and `k8s-env` entry point must use only Python 3.10+ standard library. No third-party runtime dependencies. The installed console script is `k8s` (see `[project.scripts]` in pyproject.toml).
- **uv for tooling**: Use `uv` / `uvx` for all dev tooling. Do not use pip.
- **Interactive CLI**: Most commands use an interactive picker (`pick()` in cli.py). Non-interactive stdin causes early exit.
- **Trust model**: `.k8s-env` files must be explicitly trusted via `allow` command before use. Trust is stored as SHA256 hashes in `~/.config/k8s-env/allowed/`.

## Architecture notes

- `KubeCtl` (k8s.py) is an ABC with `run()` for captured output, `stream()` for inherited stdout, and `stream_tty()` for `os.execvp` replacement. `SshKubeCtl` is a decorator that wraps any KubeCtl to route commands through SSH.
- `k8s.get()` is a cached factory — returns the right KubeCtl subclass based on tool/context/host.
- Discovery (`service.py`) runs namespace probes in parallel via `ThreadPoolExecutor` with a 10-second timeout per probe.
- Profiles support single-file mode (`.k8s-env` file) and multi-profile mode (`.k8s-env/profiles/` directory with `active` symlink). Auto-converts to multi-profile on second `ctx add`.
- Each context may have an optional `alias` (stored in the `.k8s-env` file). Aliases must be unique — `Profiles.save` rejects clashes. `ctx set`/`del`/`use` accept an alias argument to skip the interactive picker. The alias is positional everywhere — `ctx add [alias]` and `ctx add-remote [host] [alias]` — and is prompted when absent. `ctx alias` sets, changes, or clears the alias on the active context in place.
- `-h/--help` is handled in one place — `main()` intercepts it for any command and renders help from the `_COMMANDS_META` table (cli.py). Both the `show_help()` overview and every per-command page are generated from that table, so they cannot drift. Aliases (`svc`, `ns`, `cm`, etc.) resolve to their primary entry; unknown commands fall back to the overview. Command handlers do not handle `--help` themselves. Because help is resolved before the trust check, `ctx … --help` works in untrusted directories.
- Errors use `SystemExit` for user-facing messages and `RuntimeError` for kubectl/SSH failures.
- Presentation primitives live in `ui.py` (ANSI colors `_RED`/`_GREEN`/`_YELLOW`/`_CYAN`/`_BOLD`/`_DIM`/`_NC`, `print_status`/`print_warning`/`print_error`, `print_banner`, `_input`), imported by both `cli.py` and `status.py`. `ui.py` depends on nothing else in the package, so there is no import cycle. Color emission is gated on `sys.stdout.isatty()` and `NO_COLOR` via `_c()`, so redirected/piped output stays clean.
- `status` (status.py) reads four kubectl signals — nodes, pods (table; STATUS is kubectl's composite reason), workloads (`-o json`; ready/desired survives the omit-when-zero fields), warning events — and renders answer-first: coloured verdict (green healthy / yellow soft issues / red hard failures), then needs-attention, recent warnings, summary.

## Demo GIF

`README.md` embeds `assets/demo.gif`. Regenerate it with `assets/record.sh` (requires `minikube`, `kubectl`, `vhs`, `ttyd`, `ffmpeg`). The script:

- Starts an isolated minikube profile (`kdemo`), applies `assets/seed.yaml` (synthetic `shop`/`payments` namespaces with nginx/busybox workloads), and records `assets/demo.tape` with VHS.
- Runs the recording under a sandboxed `HOME`/`KUBECONFIG`/`PATH` so no real cluster, kubectl context, or trust file is shown or touched. The kubeconfig context is renamed to `demo` for the recording.
- Snapshots `~/.kube/config` and the current context on entry and restores them on exit. This is required because `minikube start/stop/delete` mutate the real kubeconfig — on this setup `minikube stop` removes the `minikube` context entirely.

Constraints baked into `demo.tape` (changing them tends to regress the output):

- `Set Framerate 10` — at the gif resolution VHS drops frames at the default framerate, which compresses every `Sleep` and ruins the read pacing. Total runtime targets ~90s.
- The minikube profile name is kept short (`kdemo`) because it becomes the node name in `kubectl get pods -o wide`; a long name overflows `Width` and wraps the table.
- `Width` is sized so the widest line (`pods -o wide`, ~119 columns) fits without wrapping.
