from typing import Any


def rget(d: dict[str, Any], key: str) -> Any:
    """Reccursive get for dictionnaries using dotted key."""
    if "." in key:
        prefix, tail = key.split(".", 1)
    else:
        prefix, tail = key, ""
    v = d.get(prefix)
    if tail:
        if isinstance(v, dict):
            return rget(v, tail)
        else:
            return None
    else:
        return v


def force_string(value: str | list[str], sep: str = " ") -> str:
    if isinstance(value, str):
        return value
    else:
        return sep.join(x for x in value if x)
