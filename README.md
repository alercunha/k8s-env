# k8s-env

Interactive CLI for managing Kubernetes environments across microk8s, minikube, kubectl contexts, and remote hosts via SSH.

Pure Python 3 — no dependencies beyond the standard library.

## Installation

Clone the repo and add it to your PATH:

```bash
git clone https://github.com/alercunha/k8s-env.git
export PATH="$PATH:$(pwd)/k8s-env"
```

Or symlink the entry point somewhere already on your PATH:

```bash
ln -s /path/to/k8s-env/k8s-env ~/.local/bin/k8s-env
```

Requires Python 3.10+ and `kubectl` installed.

## Quick start

Discover local Kubernetes runtimes and pick a namespace:

```
k8s-env use
```

This probes microk8s, minikube, and all kubectl contexts in parallel, then presents an interactive picker. Your selection is saved to `.k8s-env` in the current directory.

For remote hosts via SSH:

```
k8s-env use-remote myhost
```

Check which environment is active:

```
k8s-env ctx
```

## Trust

The first time you use a `.k8s-env` file (or after it changes), you'll be prompted to trust it:

```
k8s-env allow
```

This prevents unexpected execution from modified config files. Remove trust with `k8s-env deny`.

## Commands

### Environment

| Command | Description |
|---|---|
| `use` | Discover local k8s runtimes and set active namespace |
| `use-remote <host>` | Discover runtimes on a remote host via SSH |
| `ctx` | Show active environment (no cluster queries) |
| `allow` | Trust `.k8s-env` in current directory |
| `deny` | Remove trust for `.k8s-env` |

### Profiles

Manage multiple environments per project:

| Command | Description |
|---|---|
| `profile` | List saved profiles |
| `profile init` | Convert single-file config to multi-profile mode |
| `profile activate` | Switch to a different profile |
| `profile delete` | Delete a saved profile |

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
| `-t` | Generate new token (used with `dashboard`) |
| `-h, --help` | Show help |

## Supported runtimes

- **microk8s** — detected via `microk8s kubectl`
- **minikube** — detected via `minikube status` + `kubectl --context minikube`
- **kubectl contexts** — all contexts from `kubectl config get-contexts`
- **SSH** — any of the above routed through SSH to a remote host
