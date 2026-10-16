# k8s-env

Kubernetes environment manager — interactive CLI for switching between k8s namespaces across microk8s, minikube, kubectl contexts, and remote hosts via SSH.

## Checks

Run before every commit. Must pass clean.

```
uvx --with pytest pylint k8s_env/ tests/
```

Tests run with pytest (dev dependency). The integration test is marked `integration` and deselected by default (`addopts` in pyproject.toml); it requires `docker`, `kind`, `kubectl`. Run it after changing CLI behavior:

```
uv run pytest -m integration -v
```

## Integration test

`tests/test_integration.py` (a module-scoped pytest fixture plus a `unittest.TestCase` scenario) creates a kind cluster `k8s-env-it`, applies `assets/seed.yaml`, and walks one scenario through every command except `env add-remote`, `dashboard`, `app`, and the interactive `exec` shell (SSH and browser/TTY flows are out of scope).

- The CLI runs as a subprocess with a sandboxed `HOME`, `KUBECONFIG` (written by `kind --kubeconfig`, never `~/.kube/config`), and a `PATH` holding only `kubectl`, so discovery sees just the kind context.
- `k8s()` gives the CLI a pty as stdin with picker/prompt answers typed ahead; `k8s_running()` handles commands that run until stopped (`pf`, `logs -f`) and kills the process group afterwards.
- `K8S_ENV_IT_KEEP=1` keeps the cluster; the next run reuses it (~10s instead of ~60s).

## Project structure

```
k8s-env              # Entry point script (#!/usr/bin/env python3)
k8s_env/             # Main package (stdlib only — no third-party imports)
  args.py            # Generic flag parser (parse_args, handle_help, first)
  app.py             # App — holds env/namespace overrides, resolves the effective env, lazy kubectl
  cli.py             # Command dispatcher, interactive picker, env subcommands, all cmd_* handlers
  k8s.py             # KubeCtl ABC + MicroK8s, MiniKube, K8sContext, SshKubeCtl implementations
  service.py         # Env class (load/save env files, key/label/describe), namespace discovery
  store.py           # EnvStore — env files and the active link in ~/.k8s-env
  utils.py           # Validators, constants (CONFIG_DIR, ENV_VAR, CMD, SYSTEM_NAMESPACES)
tests/
  test_integration.py  # End-to-end test against a kind cluster (pytest marker `integration`)
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
- **Home config**: All state lives in `~/.k8s-env/` (mode `0700`, env files `0600`). `EnvStore` refuses to load if the directory is not owned by the user or has any group/other permission bits. There is no per-directory config.

## Architecture notes

- `KubeCtl` (k8s.py) is an ABC with `run()` for captured output, `stream()` for inherited stdout, and `stream_tty()` for `os.execvp` replacement. `SshKubeCtl` is a decorator that wraps any KubeCtl to route commands through SSH.
- `k8s.get()` is a cached factory — returns the right KubeCtl subclass based on tool/context/host.
- Discovery (`service.py`) runs namespace probes in parallel via `ThreadPoolExecutor` with a 10-second timeout per probe.
- Terminology: an **env** is a saved k8s-env target (`Env`: tool, ssh_host, kubectl context, namespace, optional name, port-forwards). "context" always means a kubectl context (`Env.context`, `K8sContext`), never an env.
- `Env.key` (`<tool>-<ssh_host|context|local>-<namespace>`) is the storage id and filename; `Env.name` is the optional user-facing name; `Env.label` is name or key and is what messages show. `Env.target` (`<tool> @ <context|host (ssh)|local>`) and `Env.describe()` (`target / namespace`) are the one display format used by the banner, `env` list, pickers, and discovery group headers.
- Envs are stored as `~/.k8s-env/envs/<key>.env` with an `active` symlink. An `active` that is dangling or not a symlink reads as "no active env"; `env set` replaces it. `EnvStore.save` only writes, so saving a non-active env (e.g. under `-e`) never switches the active one. `EnvStore.add` (used by `env add`/`add-remote`) saves and activates, keeping an existing env's port-forwards and name.
- `-e <name>` (default: `$K8S_ENV`) overrides the env for one invocation. `App.env` resolves the effective env; `app.store.active_key` is the saved one, which `env` listings mark as active.
- Names match `segment` or `project/segment` where a segment is `[a-z0-9][-_a-z0-9]*`. The `project/` prefix is naming only; there is no project concept in code. Names must be unique — `EnvStore.save` rejects clashes. `env set`/`del`/`kubectl` accept a name to skip the interactive picker. The name is positional — `env add [name]` and `env add-remote [host] [name]` — and is prompted when absent. `env rename` sets, changes, or clears the name on the effective env (`App.env`: active, or `-e`).
- Discovery (`service.discover_local/remote`) returns unnamed `Env` objects, one per namespace found.
- `print_grouped()` (cli.py) renders item lists under group headers; `pick()` and `env` (list) both use it. `_env_items()` builds the sorted, aligned env rows (grouped by name prefix, ungrouped first) for `env` and the `env set`/`del` pickers.
- `-h/--help` is handled in one place — `main()` intercepts it for any command and renders help from the `_COMMANDS_META` table (cli.py). Both the `show_help()` overview and every per-command page are generated from that table, so they cannot drift. Aliases (`svc`, `ns`, `cm`, etc.) resolve to their primary entry; unknown commands fall back to the overview. Command handlers do not handle `--help` themselves.
- Errors use `SystemExit` for user-facing messages and `RuntimeError` for kubectl/SSH failures.
- ANSI color constants are defined in cli.py (`_RED`, `_GREEN`, `_YELLOW`, `_CYAN`, `_BOLD`, `_DIM`, `_NC`).

## Demo GIF

`README.md` embeds `assets/demo.gif`. Regenerate it with `assets/record.sh` (requires `minikube`, `kubectl`, `vhs`, `ttyd`, `ffmpeg`). The script:

- Starts an isolated minikube profile (`kdemo`), applies `assets/seed.yaml` (synthetic `shop`/`payments` namespaces with nginx/busybox workloads), and records `assets/demo.tape` with VHS.
- Runs the recording under a sandboxed `HOME`/`KUBECONFIG`/`PATH` so no real cluster, kubectl context, or `~/.k8s-env` is shown or touched. The kubeconfig context is renamed to `demo` for the recording.
- Snapshots `~/.kube/config` and the current context on entry and restores them on exit. This is required because `minikube start/stop/delete` mutate the real kubeconfig — on this setup `minikube stop` removes the `minikube` context entirely.

Constraints baked into `demo.tape` (changing them tends to regress the output):

- `Set Framerate 10` — at the gif resolution VHS drops frames at the default framerate, which compresses every `Sleep` and ruins the read pacing. Total runtime targets ~100s.
- The hidden setup block pre-adds `payments/dev` so the grouped `k8s env` list and the `-e payments/dev` scene have a second env.
- The minikube profile name is kept short (`kdemo`) because it becomes the node name in `kubectl get pods -o wide`; a long name overflows `Width` and wraps the table.
- `Width` is sized so the widest line (`pods -o wide`, ~119 columns) fits without wrapping.
