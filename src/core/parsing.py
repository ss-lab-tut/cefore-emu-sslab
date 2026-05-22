"""Shared parsing utilities."""


def parse_int_list(value):
    """Parse integer list from string or list input.

    Args:
        value: Comma-separated string or list of integers/strings.

    Returns:
        List of integers.
    """
    if value is None or value == "":
        return []
    items = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if item is None or item == "":
                continue
            if isinstance(item, str):
                parts = [part for part in item.split(",") if part.strip() != ""]
                items.extend(parts)
            else:
                items.append(item)
    elif isinstance(value, str):
        items = [part for part in value.split(",") if part.strip() != ""]
    else:
        items = [value]
    try:
        return [int(item) for item in items]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"expected list of ints or comma-separated string, got {value!r}"
        ) from exc
