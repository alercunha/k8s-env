# k8s-env

Interactive CLI for managing Kubernetes environments across microk8s, minikube, kubectl contexts, and remote hosts via SSH.

Pure Python 3 — no dependencies beyond the standard library.

![k8s-env demo](assets/demo.gif)

## Prerequisites

- Python 3.10+
- `kubectl`
- At least one of: microk8s, minikube, or a configured kubectl context

## Installation

### With uv (recommended)

Install as a global tool using [uv](https://docs.astral.sh/uv/):

```bash
uv tool install "k8s-env @ git+ssh://git@github.com/alercunha/k8s-env.git"
```

This installs `k8s` into an isolated environment and adds it to your PATH. Update with:

```bash
uv tool upgrade k8s-env
```

### With pipx

```bash
pipx install git+ssh://git@github.com/alercunha/k8s-env.git
```

### With pip

```bash
pip install git+ssh://git@github.com/alercunha/k8s-env.git
```

### From source

Clone the repo and either add it to your PATH or symlink the entry point:

```bash
git clone https://github.com/alercunha/k8s-env.git
ln -s "$(pwd)/k8s-env/k8s-env" ~/.local/bin/k8s-env
```

## Quick start

Discover local Kubernetes runtimes and pick a namespace:

```
k8s ctx add
```

This probes microk8s, minikube, and all kubectl contexts in parallel, then presents an interactive picker. Your selection is saved as a context in `~/.k8s-env/` and becomes the active one.

For remote hosts via SSH:

```
k8s ctx add-remote myhost
```

Show saved contexts:

```
k8s ctx
```

Switch between contexts with `k8s ctx set`.

Give a context a unique alias to skip the interactive picker. Aliases use lowercase letters, digits, `-` and `_`, with an optional `project/` prefix to group environments per project:

```
k8s ctx add shop/dev
k8s ctx set shop/prod
k8s ctx use shop/prod
```

Run a single command against another context without switching, with `-c` or the `K8S_ENV_CONTEXT` environment variable (`-c` wins):

```
k8s -c billing/prod pods
export K8S_ENV_CONTEXT=shop/dev   # pin this shell to shop/dev
```

## Configuration

Contexts live in `~/.k8s-env/`:

```
~/.k8s-env/
  profiles/<name>.env    one file per context
  active                 symlink to the active profile
```

The directory is created with mode `0700` and profile files with `0600`. `k8s` refuses to run if `~/.k8s-env` is not owned by you or is accessible by group/others.

## Commands

### Context

| Command | Description |
|---|---|
| `ctx` | Show saved contexts |
| `ctx add [alias]` | Add local k8s namespace as context |
| `ctx add-remote [host] [alias]` | Add remote k8s namespace via SSH |
| `ctx set [alias]` | Switch active context (by alias, or interactive picker) |
| `ctx del [alias]` | Delete a saved context (by alias, or interactive picker) |
| `ctx use [alias]` | Apply a context to kubectl config (by alias, or the active one) |
| `ctx alias [alias]` | Set, change, or clear the alias on the active context |

### Inspection

All inspection commands support an optional filter argument to narrow results by name.

| Command | Description |
|---|---|
| `pods [filter]` | List pods |
| `logs [filter] [-f] [--tail N]` | Show pod logs (`-f` to follow, `--tail N` lines, default 20) |
| `services [filter]` | List services |
| `namespaces` | List all namespaces |
| `events [filter]` | Show recent events |
| `configmaps [filter]` | List configmaps (interactive viewer) |
| `secrets [filter]` | List secret names |
| `cronjobs [filter]` | List cronjobs |
| `status` | Show cluster and namespace stats |
| `describe [resource]` | Describe a resource (picker if omitted) |

### Actions

| Command | Description |
|---|---|
| `exec [filter]` | Open a shell in a pod, or run a command after `--` |
| `restart [filter]` | Restart deployments (multi-select) |
| `port-forward [filter]` | Forward a service port to localhost |
| `app [filter]` | Open a NodePort service in the browser |
| `dashboard [-t]` | Open Headlamp dashboard (`-t` for new token) |

Everything after `--` is passed to the pod verbatim, so its own flags are not parsed by `k8s` (e.g. `k8s exec api -- tail -n 100 /var/log/app.log`). Command output goes to stdout while interactive chrome (banners, pickers, prompts) goes to stderr, so results pipe cleanly: `k8s exec api -- cat config.json | jq .`.

### Global options

| Flag | Description |
|---|---|
| `-c <alias>` | Use this context instead of the active one for this invocation (default: `$K8S_ENV_CONTEXT`) |
| `-n <namespace>` | Override the saved namespace for this invocation |
| `-h, --help` | Show help (also works per-command: `k8s logs --help`) |

## Supported runtimes

- **microk8s** — detected via `microk8s kubectl`
- **minikube** — detected via `minikube status` + `kubectl --context minikube`
- **kubectl contexts** — all contexts from `kubectl config get-contexts`
- **SSH** — any of the above routed through SSH to a remote host

## Bash alternative

A standalone Bash drop-in replacement is available in [`contrib/k8s`](contrib/) for systems where Python 3.10+ cannot be installed. It shares `~/.k8s-env/` with the Python version and covers the core commands, but does not manage multiple contexts or run parallel discovery. See [`contrib/README.md`](contrib/README.md) for details.
