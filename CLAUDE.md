# k8s-env

Kubernetes environment manager — pure Python 3 CLI with no external dependencies.

## Tooling

Uses [uv](https://docs.astral.sh/uv/) for tooling. Do not use pip.

### Type checking

```
uvx ty check
```

### Linting

```
uvx ruff check
```

Auto-fix lint issues:

```
uvx ruff check --fix
```

## Code guidelines

- The script itself (`k8s-env` and `k8s_env/` package) must remain pure Python 3 with no added libraries — stdlib only.
- All tooling (type checking, linting) runs via `uvx` without installing into the project.
- Run both `uvx ty check` and `uvx ruff check` before committing and ensure they pass clean.
