"""Common utility functions for data operations.

This module provides basic utility functions that are used across the project,
particularly for handling dicts.
"""

from collections.abc import Iterable


class NotSpecified:  # pylint: disable=too-few-public-methods
    """Sentinel class to distinguish between None and no default value provided."""


def get_multi(data, path: str | list[str], default=NotSpecified):
    """Get a value from nested dictionary using a dot-separated path.

    Args:
        data: Dictionary or nested dictionary to retrieve value from.
        path: Dot-separated string path (e.g., 'key1.key2.key3') or list of keys.
        default: Default value to return if path not found. If NotSpecified, raises exception.

    Returns:
        The value at the specified path.

    Raises:
        KeyError: If path not found and default is NotSpecified.
        TypeError: If intermediate value is not subscriptable.
    """
    if isinstance(path, str):
        path = path.split(".")
    try:
        return get_multi(data[path[0]], path[1:], default) if path else data
    except (KeyError, TypeError) as e:
        if default == NotSpecified:
            raise type(e)(f"{data=} {path=} {e!r}") from e
        return default


def set_multi(data, path: str | list[str], value):
    """Set a value in nested dictionary using a dot-separated path.

    Args:
        data: Dictionary or nested dictionary to set value in.
        path: Dot-separated string path (e.g., 'key1.key2.key3') or list of keys.
        value: Value to set at the specified path.

    Note:
        Creates intermediate dictionaries as needed using setdefault.
    """
    assert path
    if isinstance(path, str):
        path = path.split(".")

    head, tail = path[0], path[1:]
    if not tail:
        data[head] = value
        return
    set_multi(data.setdefault(head, {}), tail, value)


def pop_multi(
    data, path: str | list[str], default=NotSpecified, pop_list_items: bool = False, val_to_del=NotSpecified
):
    """Remove and return a value from nested dictionary using a dot-separated path.

    Args:
        data: Dictionary or nested dictionary to pop value from.
        path: Dot-separated string path or list of keys. Use '[]' to operate on list items.
        default: Default value to return if path not found. If NotSpecified, raises exception.
        pop_list_items: If True and path contains '[]', operate on list items.
        val_to_del: If specified, only delete items matching this value.

    Returns:
        The popped value or default if not found.

    Raises:
        KeyError: If path not found and default is NotSpecified.
        TypeError: If intermediate value is not subscriptable.

    Note:
        Empty intermediate dictionaries are automatically removed after popping.
    """
    print(f"{path=} {default=} {pop_list_items=} {val_to_del=} {data=}")

    def pop(dat, key):
        try:
            return dat.pop(key)
        except KeyError:
            if default == NotSpecified:
                raise
            return default

    if isinstance(path, str):
        path = path.split(".")
    if path:
        head, tail = path[0], path[1:]

        def _recurse(dat):
            return pop_multi(dat, tail, default, pop_list_items, val_to_del)

        if pop_list_items and head == "[]" and isinstance(data, list):
            ret = [_recurse(item) for item in data if val_to_del is NotSpecified or item not in listify(val_to_del)]
            data[:] = [item for item in data if item]  # remove empty items
            return ret
        if not tail:  # empty list means we're at the leaf of the tree
            return pop(data, head)
        try:
            data_head = data[head]
        except KeyError as e:
            if default == NotSpecified:
                raise type(e)(f"{head=} {path=} {data=}") from e
            return default
        except TypeError as e:
            raise type(e)(f"{head=} {path=} {data=}") from e
        ret = _recurse(data_head)
        if not data[head]:
            pop(data, head)
        return ret
    if default == NotSpecified:
        raise KeyError(f"{path=}")
    return default


def listify(data):
    """Ensure data is a list."""
    if isinstance(data, list):
        return data
    if isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
        return list(data)
    return [data]
