# contrib/k8s — Bash drop-in replacement

A standalone Bash version of the `k8s` CLI. This was the original tool, later rewritten as the Python package `k8s-env`. It can be used as a drop-in replacement on systems where Python 3.10+ is not available.

No dependencies beyond Bash 4+, `kubectl`, and optionally `ssh`.

## Installation

Copy or symlink the script somewhere on your PATH:

```bash
ln -s "$(pwd)/contrib/k8s" ~/.local/bin/k8s
```

## Differences from the Python version

The bash script covers the same core inspection and action commands but lacks several features added in the Python rewrite:

| Feature | Python (`k8s`) | Bash (`contrib/k8s`) |
|---|---|---|
| Shared config in `~/.k8s-env/` | Yes | Yes (reads/writes the active env) |
| Show the active env (`env`) | Yes (lists all envs) | Yes |
| Multiple envs (`env set/del/rename`) | Yes | No |
| Per-command env override (`-e`, `K8S_ENV`) | Yes | No |
| kubectl context discovery (Python `env add` / bash `use`) | Yes | Yes |
| Remote host discovery (Python `env add-remote` / bash `use-remote`) | Yes | Yes |
| Port-forward saved mappings | Yes | Yes |
| All inspection commands (`pods`, `logs`, `services`, `events`, etc.) | Yes | Yes |
| All action commands (`exec`, `restart`, `port-forward`, `app`, `dashboard`) | Yes | Yes |
| Command aliases (`ns`, `svc`, `cm`, `cj`, `pf`, `sh`, `st`, `desc`) | Yes | Yes |
| Filter argument on inspection commands | Yes | Yes |

In short: the bash script is a functional subset that handles day-to-day namespace switching and kubectl operations but only works with the active env. Envs are added with `use` / `use-remote` instead of `env add` / `env add-remote`.
