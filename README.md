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
uv tool install git+https://github.com/alercunha/k8s-env
```

This installs `k8s` into an isolated environment and adds it to your PATH. Append `@<branch>` to the URL to install a branch. Update with:

```bash
uv tool upgrade k8s-env
```

### With pipx

```bash
pipx install git+https://github.com/alercunha/k8s-env
```

### With pip

```bash
pip install git+https://github.com/alercunha/k8s-env
```

### From source

Clone the repo and either add it to your PATH or symlink the entry point:

```bash
git clone https://github.com/alercunha/k8s-env.git
ln -s "$(pwd)/k8s-env/k8s-env" ~/.local/bin/k8s-env
```

## Quick start

An **env** is a saved target: a tool (microk8s, minikube, or a kubectl context), where it runs (locally or over SSH), and a namespace. Every command runs against the active env.

Discover local Kubernetes runtimes, pick a namespace, and save it as an env:

```
k8s env add shop/dev
```

This probes microk8s, minikube, and all kubectl contexts in parallel, then presents an interactive picker. The env is saved in `~/.k8s-env/` and becomes the active one.

For remote hosts via SSH:

```
k8s env add-remote myhost shop/staging
```

Names are optional and unique. They use lowercase letters, digits, `-` and `_`, with an optional `project/` prefix to group envs per project. `k8s env` lists them, grouped by project:

```
$ k8s env
[k8s-kind-local-scratch]  k8s @ kind-local / scratch

shop
  dev                     microk8s @ local / shop
  prod                    k8s @ gke-prod / shop (active)
  staging                 microk8s @ myhost (ssh) / shop
```

Each line reads `<tool> @ <kubectl context, host (ssh), or local> / <namespace>`. Unnamed envs show their generated key in brackets. Every command prints the same line as a banner, tagged with the env name (yellow when running over SSH):

```
$ k8s pods
[shop/prod] k8s @ gke-prod / shop
```

Switch envs by name (or pick interactively without one):

```
k8s env set shop/dev
```

Run a single command against another env without switching, with `-e` or the `K8S_ENV` environment variable (`-e` wins):

```
k8s -e shop/prod pods
export K8S_ENV=shop/dev   # pin this shell to shop/dev
```

## Configuration

Envs live in `~/.k8s-env/`:

```
~/.k8s-env/
  envs/<key>.env    one file per env (key: <tool>-<context|host|local>-<namespace>)
  active            symlink to the active env
```

The directory is created with mode `0700` and env files with `0600`. `k8s` refuses to run if `~/.k8s-env` is not owned by you or is accessible by group/others.

## Commands

### Environments

| Command | Description |
|---|---|
| `env` | List saved envs |
| `env add [name]` | Add an env from a local namespace |
| `env add-remote [host] [name]` | Add an env from a remote namespace via SSH |
| `env set [name]` | Switch the active env (by name, or interactive picker) |
| `env del [name]` | Delete a saved env (by name, or interactive picker) |
| `env kubectl [name]` | Point your kubectl config (context + namespace) at an env (by name, or the active one) |
| `env rename [name]` | Rename the current env (the active one, or the one given with `-e`), or clear its name |

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
| `describe [filter]` | Describe a pod, deployment, service, or configmap (picker when several match) |

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
| `-e <env>` | Use this env instead of the active one for this invocation (default: `$K8S_ENV`) |
| `-n <namespace>` | Override the saved namespace for this invocation |
| `-h, --help` | Show help (also works per-command: `k8s logs --help`) |

## Supported runtimes

- **microk8s** — detected via `microk8s kubectl`
- **minikube** — detected via `minikube status` + `kubectl --context minikube`
- **kubectl contexts** — all contexts from `kubectl config get-contexts`
- **SSH** — any of the above routed through SSH to a remote host

## Development

Lint:

```
uvx --with pytest pylint k8s_env/ tests/
```

Tests run with pytest (a dev dependency). The integration test runs every command against a throwaway [kind](https://kind.sigs.k8s.io/) cluster seeded with `assets/seed.yaml`. It is marked `integration`, which plain `uv run pytest` deselects, and requires `docker`, `kind`, and `kubectl`:

```
uv run pytest -m integration -v
```

Set `K8S_ENV_IT_KEEP=1` to keep the cluster between runs.

The `Dockerfile` runs the same pipeline with only docker installed locally:

```
docker build -t k8s-env .                        # lint, unit tests, wheel
docker build --target dist -o dist .             # export the wheel to ./dist
docker run --rm --network host \
  -v /var/run/docker.sock:/var/run/docker.sock k8s-env   # integration test
```

## Bash alternative

A standalone Bash drop-in replacement is available in [`contrib/k8s`](contrib/) for systems where Python 3.10+ cannot be installed. It shares `~/.k8s-env/` with the Python version and covers the core commands, but only works with the active env and does not run parallel discovery. See [`contrib/README.md`](contrib/README.md) for details.
