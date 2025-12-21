"""Common utility functions for data operations.

This module provides basic utility functions that are used across the project,
particularly for handling dicts.
"""

import re
import typing as t
from collections.abc import Iterable
from contextlib import suppress
from copy import deepcopy

from deepmerge import Merger


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


T = t.TypeVar("T")


def recurse(data: T, func: t.Callable[[t.Any], t.Any], what: t.Iterable[str] = ("value",)) -> T:
    """Recursively transform data elements

    :param T data: any serializable input data
    :param t.Callable[[t.Any], t.Any] func: to transform data elements with
    :param tuple what: Possible items are "value" and "key"
    :return T: transformed new data instance
    >>> recurse({1:2, 3:4}, str, ('key',))
    {'1': 2, '3': 4}
    >>> recurse({1:2, 3:4}, str)
    {1: '2', 3: '4'}
    >>> recurse({1:2, 3:4}, str, 'key')
    {'1': 2, '3': 4}
    >>> recurse({1:2, 3:4}, str, ('key', 'val'))
    Traceback (most recent call last):
    ...
    AssertionError: {'val', 'key'}
    >>> recurse({1:2, 3:4}, str, ('key', 'value'))
    {'1': '2', '3': '4'}
    >>> recurse([1, 2, {3}], lambda x: x * 10)
    [10, 20, {30}]
    """
    what = set(listify(what))
    assert what and not what - {"key", "value"}, what

    def _recurse(data: T, func: t.Callable[[t.Any], t.Any], what: set[str]) -> T:
        def apply(val, is_key: bool = False):
            if is_key and "key" in what:
                return func(val)
            if not is_key and "value" in what:
                return _recurse(val, func, what)
            return val

        if isinstance(data, dict):
            return type(data)({apply(k, is_key=True): apply(v) for k, v in data.items()})
        if isinstance(data, (list, tuple, set)):
            return type(data)(apply(item) for item in data)
        return func(data) if "value" in what else data

    return _recurse(data, func, what)


def merge_struct(data1: T, data2: T) -> T:
    """
    Deep-merge two JSON-like structures.

    Rules:
      - dict + dict   => deepmerge-style recursive merge
      - anything else => take the 2nd value (data2)

    Returns a NEW structure; does not mutate inputs.
    """
    base = deepcopy(data1)  # deepmerge mutates the first argument
    _merger = Merger(
        # Per-type strategies
        [
            (dict, ["merge"]),  # recursively merge dicts
        ],
        # Fallback strategies (for non-dict types: lists, ints, etc.)
        ["override"],  # use value from data2
        # Type conflict strategies (int vs dict, list vs dict, etc.)
        ["override"],  # use value from data2
    )
    return _merger.merge(base, data2)


def dict_only_keys(dic: dict, keys: t.Any, strict: bool = False, invert: bool = False) -> dict:
    keys = set(listify(keys))  # convert str, int, float, etc. to 1-element set; list, dict, tuple etc to set
    if strict and (should := [k for k in keys if k not in dic.keys()]):
        raise KeyError(f"Keys(s) {should} should be in {dic}")
    return {k: v for k, v in dic.items() if (k in keys) == (not invert)}


# def dict_without_keys(dic: dict, keys: t.Any, strict: bool = False) -> dict:
#     return dict_only_keys(dic, keys, strict, invert=True)


def validate(value, predicate: t.Callable[[t.Hashable, t.Any], bool] | list | set | tuple | dict | re.Pattern) -> bool:
    """Validate a value against a predicate.

    Args:
        value: The value to validate.
        predicate: A function that takes a key and value and returns True or False,
                   or a collection (list, set, tuple) to check membership,
                   or a dict to check value,
                   or a regex pattern to match strings.

    Returns:
        True if the value satisfies the predicate, False otherwise.
    """

    def _validate():  # pylint: disable=too-many-return-statements
        with suppress(Exception):
            if callable(predicate):
                return predicate(value)
            if isinstance(predicate, (list, set, tuple)):
                return value in predicate
            if isinstance(predicate, dict):
                return predicate.get(value)
            if isinstance(predicate, bool):
                return predicate
            if isinstance(predicate, (str, int, float)):
                return predicate == value
            if isinstance(predicate, re.Pattern):
                return bool(predicate.search(value))
        return None

    return bool(_validate())


def split_dict(
    dic: dict, predicate: t.Callable[[t.Hashable, t.Any], bool] | list | set | tuple | dict | re.Pattern
) -> tuple[dict, dict]:
    """Split a dictionary into two based on a predicate.

    Args:
        dic: The input dictionary to split.
        func: A function that takes a key and value and returns True or False.

    Returns:
        A tuple of two dictionaries: (dict_true, dict_false)
    """
    res = {True: {}, False: {}}
    for key, value in dic.items():
        res[validate(value, predicate)][key] = value
    return tuple(res.values())
