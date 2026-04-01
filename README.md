# k8s-env

Interactive CLI for managing Kubernetes environments across microk8s, minikube, kubectl contexts, and remote hosts via SSH.

Pure Python 3 — no dependencies beyond the standard library.

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

This probes microk8s, minikube, and all kubectl contexts in parallel, then presents an interactive picker. Your selection is saved to `.k8s-env` in the current directory.

For remote hosts via SSH:

```
k8s ctx add-remote myhost
```

Show saved contexts:

```
k8s ctx
```

Adding a second context automatically converts to multi-profile mode (`.k8s-env/` directory). Switch between contexts with `k8s ctx set`.

## Trust

The first time you use a `.k8s-env` file (or after it changes), you'll be prompted to trust it:

```
k8s allow
```

This prevents unexpected execution from modified config files. Remove trust with `k8s deny`.

## Commands

### Context

| Command | Description |
|---|---|
| `ctx` | Show saved contexts |
| `ctx add` | Add local k8s namespace as context |
| `ctx add-remote [host]` | Add remote k8s namespace via SSH |
| `ctx set` | Switch active context |
| `ctx del` | Delete a saved context |
| `allow` | Trust `.k8s-env` in current directory |
| `deny` | Remove trust for `.k8s-env` |

### Inspection

All inspection commands support an optional filter argument to narrow results by name.

| Command | Description |
|---|---|
| `pods [filter]` | List pods |
| `logs [filter] [-f]` | Show last 20 log lines per pod (`-f` to follow) |
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
| `exec [filter]` | Open a shell in a pod |
| `restart [filter]` | Restart deployments (multi-select) |
| `port-forward [filter]` | Forward a service port to localhost |
| `app [filter]` | Open a NodePort service in the browser |
| `dashboard [-t]` | Open Headlamp dashboard (`-t` for new token) |

### Options

| Flag | Description |
|---|---|
| `-n <namespace>` | Override the saved namespace for this invocation |
| `-f` | Follow logs (used with `logs`) |
| `--tail <lines>` | Number of log lines to show (default 20, -1 for all) |
| `-t` | Generate new token (used with `dashboard`) |
| `-h, --help` | Show help |

## Supported runtimes

- **microk8s** — detected via `microk8s kubectl`
- **minikube** — detected via `minikube status` + `kubectl --context minikube`
- **kubectl contexts** — all contexts from `kubectl config get-contexts`
- **SSH** — any of the above routed through SSH to a remote host

## Bash alternative

A standalone Bash drop-in replacement is available in [`contrib/k8s`](contrib/) for systems where Python 3.10+ cannot be installed. It covers the core commands but does not support the trust system, profiles, or parallel discovery. See [`contrib/README.md`](contrib/README.md) for details.
