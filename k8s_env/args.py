from __future__ import annotations


def handle_help(args: list[str], help_fn) -> bool:
    """If -h/--help is in args, call help_fn and return True."""
    if '-h' in args or '--help' in args:
        help_fn()
        return True
    return False


def _parse_value(arg: str, raw: str, default):
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            raise SystemExit(f'{arg} requires an integer, got: {raw}') from None
    return raw


def parse_args(argv: list[str], spec: dict) -> tuple:
    """Parse flags from argv according to spec.

    Spec keys are flag names (e.g. '-f', '--tail') or tuples of aliases
    (e.g. ('-h', '--help')).
    Spec values are defaults that also determine the type:
      - False       → boolean toggle, no value consumed
      - int value   → consumes next arg, converts to int
      - str value   → consumes next arg, keeps as string

    Returns (*flag_values, remaining_positional_args) in spec key order.
    """
    # Build lookup: flag string → spec key
    lookup: dict[str, tuple | str] = {}
    for key in spec:
        if isinstance(key, tuple):
            for alias in key:
                lookup[alias] = key
        else:
            lookup[key] = key

    flags = dict(spec)
    rest: list[str] = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg not in lookup:
            rest.append(arg)
            i += 1
            continue
        key = lookup[arg]
        default = spec[key]
        if default is False:
            flags[key] = True
            i += 1
        else:
            if i + 1 >= len(argv):
                raise SystemExit(f'{arg} requires a value')
            flags[key] = _parse_value(arg, argv[i + 1], default)
            i += 2

    return (*flags.values(), rest)


def first(args: list[str]) -> str:
    return args[0] if args else ''
