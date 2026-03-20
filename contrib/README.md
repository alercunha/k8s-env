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
| Trust system (`allow` / `deny`) | Yes | No |
| Multi-profile management (`profile`) | Yes | No |
| kubectl context discovery in `use` | Yes | Yes |
| Remote host discovery (`use-remote`) | Yes | Yes |
| Port-forward saved mappings | Yes | Yes |
| All inspection commands (`ctx`, `pods`, `logs`, `services`, `events`, etc.) | Yes | Yes |
| All action commands (`exec`, `restart`, `port-forward`, `app`, `dashboard`) | Yes | Yes |
| Command aliases (`ns`, `svc`, `cm`, `cj`, `pf`, `sh`, `st`, `desc`) | Yes | Yes |
| Filter argument on inspection commands | Yes | Yes |

In short: the bash script is a functional subset that handles day-to-day namespace switching and kubectl operations but does not support the trust model or profiles.
