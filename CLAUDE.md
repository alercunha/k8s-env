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
  cli.py             # Command dispatcher, interactive picker, ctx subcommands, all cmd_* handlers
  context.py         # AppContext — holds namespace override, flags, trust check, lazy kubectl init
  k8s.py             # KubeCtl ABC + MicroK8s, MiniKube, K8sContext, SshKubeCtl implementations
  service.py         # Env config class (load/save .k8s-env files), namespace discovery
  profile.py         # Multi-profile management (EnvEntry, Profiles)
  trust.py           # SHA256-based trust system for .k8s-env files
  utils.py           # Validators, constants (ENV_FILE, CMD, SYSTEM_NAMESPACES)
contrib/
  k8s                # Standalone bash alternative (drop-in replacement, limited features)
  README.md          # Differences between bash and Python versions
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
- Errors use `SystemExit` for user-facing messages and `RuntimeError` for kubectl/SSH failures.
- ANSI color constants are defined in cli.py (`_RED`, `_GREEN`, `_YELLOW`, `_CYAN`, `_BOLD`, `_DIM`, `_NC`).
