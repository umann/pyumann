"""Common utility functions for data operations.

This module provides basic utility functions that are used across the project,
particularly for handling dicts.
"""

import re
import typing as t
from collections.abc import Iterable
from copy import deepcopy
from functools import lru_cache
from itertools import islice

import icu
from deepmerge import Merger

T_Predicate = t.Callable[[t.Hashable, t.Any], bool] | list | set | tuple | dict | re.Pattern

"""
Note: avoid top-level import of get_config to prevent circular import
with config.py. Import it lazily inside functions that need it.
"""
# pylint: disable=wrong-import-position, import-outside-toplevel
from umann.utils.encoding_utils import fix_str_encoding


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


def listify(data, none_to_empty_list: bool = False) -> list:
    """Ensure data is a list."""
    if isinstance(data, list):
        return data
    if isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
        return list(data)
    if data is None and none_to_empty_list:
        return []
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


def validate(value: t.Any, predicate: T_Predicate) -> bool:
    """Validate a key/value pair against a predicate."""

    def _validate():  # pylint: disable=too-many-return-statements
        if predicate is None:
            return True
        if callable(predicate):
            try:
                return predicate(value)
            except Exception:  # pylint: disable=broad-except
                return False
        if isinstance(predicate, (list, set, tuple)):
            return value in predicate
        if isinstance(predicate, dict):
            return predicate.get(value)
        if isinstance(predicate, bool):
            return predicate
        if isinstance(predicate, (str, int, float)):
            return predicate == value
        if isinstance(predicate, re.Pattern):
            return predicate.search(str(value))
        return None

    return bool(_validate())


def split_dict(dic: dict, predicate: t.Callable[[tuple[t.Hashable, t.Any]], bool]) -> tuple[dict, dict]:
    """Split a dictionary into two based on a predicate.

    Args:
        dic: The input dictionary to split.
        func: A function that takes a key and value and returns True or False.

    Returns:
        A tuple of two dictionaries: (dict_true, dict_false)
    """
    collect = {True: {}, False: {}}
    for key, value in dic.items():
        verdict_bool_key = validate(key, predicate)
        collect[verdict_bool_key][key] = value
    return tuple(collect.values())


def any_in(iterable: t.Iterable[str] | str, text: str) -> bool:
    """Check if any of the substrings in iterable is present in text.
    iterable: An iterable of substrings or a single string.
    text: The text to search within.

    >>> any_in(['foo', 'bar'], 'foobar')
    True
    >>> any_in(['baz', 'qux'], 'foobar')
    False
    >>> any_in('foo', 'foobar')
    True
    >>> any_in('baz', 'foobar')
    False
    """
    return any(substring in text for substring in listify(iterable))


def on_error(default: t.Any, msg) -> t.Any:
    if isinstance(default, Exception):
        raise default
    if isinstance(default, type):
        raise default(msg)
    return default


def iterable_not_str(data: t.Any) -> bool:
    """Check if data is an iterable but not a string or bytes."""
    return isinstance(data, Iterable) and not isinstance(data, (str, bytes))


def uniq_keep_order(seq: t.Iterable[t.Hashable]) -> list[t.Hashable]:
    """Return a list of unique items from seq, preserving the original order."""
    seen = set()
    uniq = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def deep_split(data: t.Any, pattern: str = r"\s*[,;]\s*", simplify: bool = True) -> list[str]:
    r"""_summary_

    :param t.Any data: _description_
    :param str pattern: _description_, defaults to r"\s*[,;]\s*"
    :param bool simplify: _description_, defaults to True
    :return list[str]: _description_

    >>> split_recursive("apple, banana; cherry")
    ['apple', 'banana', 'cherry']
    >>> split_recursive(["apple, banana", "cherry; date"])
    ['apple', 'banana', 'cherry', 'date']
    >>> split_recursive([["apple, banana"], ["cherry; date"]])
    ['apple', 'banana', 'cherry', 'date']
    >>> split_recursive(None)
    []
    >>> split_recursive([[[[["apple, banana"]]]], ["", None""])
    ['apple', 'banana']
    """

    def _split_recursive(data_: t.Any) -> list[str]:
        if data_ is None:
            return []
        if iterable_not_str(data_):
            ret = []
            for item in data_:
                ret.extend(_split_recursive(item))
            return ret
        return re.split(pattern, str(data_))

    splitted = _split_recursive(data)
    if simplify:
        splitted = uniq_keep_order(re.sub(r"\s+", " ", item).strip() for item in splitted)

    return [item for item in splitted if item != ""]


def map_recursive(data: t.Any, func: t.Callable[[t.Any], t.Any]) -> t.Any:
    """Recursively apply func to all non-iterable, non-string values in data."""
    typ = type(data)
    if isinstance(data, dict):
        return typ({k: map_recursive(v, func) for k, v in data.items()})
    if isinstance(data, (list, tuple, set)):
        return typ(map_recursive(item, func) for item in data)
    return func(data)


def fix_iptc_encoding(metadata: dict[str, t.Any], force_language: str | None = None) -> dict[str, t.Any]:
    """Fix IPTC encoding issues in metadata dictionary.
    Applies fix_iptc_encoding to all IPTC and MWG string fields.
    """
    if not isinstance(metadata, dict):
        return metadata

    iptc, non_iptc = split_dict(metadata, lambda key: key.startswith("IPTC:"))
    if not iptc:
        return metadata

    def func(value):
        return fix_str_encoding(value, force_language=force_language)

    return map_recursive(iptc, func) | non_iptc


@lru_cache
def get_collation_sort_key():
    from umann.config import get_config

    collator_class = getattr(icu, "Collator")
    locale_class = getattr(icu, "Locale")
    coll = collator_class.createInstance(locale_class(f"{get_config('default_lang')}_{get_config('default_country')}"))
    return coll.getSortKey


def locale_sorted(iterable: Iterable[str]) -> list[str]:
    return sorted(iterable, key=get_collation_sort_key())


# def any_in(items: t.Iterable[t.Any], container: t.Container[t.Any]) -> bool:
#     """Check if any item from items is in the container.

#     Args:
#         items: An iterable of items to check.
#         container: A container (like list, set, dict keys) to check against.
#     """
#     return any(item in container for item in items)


def flat1(data) -> str | None:
    if isinstance(data, (list, tuple)):
        data = data[0] if data else None
    return data


def flat_more(data) -> str | None:
    if isinstance(data, (list, tuple)):
        data = ", ".join(data) if data else None
    return data


def single_line(text: str, keep_quoted_spaces: bool = True) -> str:
    """Convert multi-line text to a single line by replacing newlines with spaces."""
    ret = text
    ret = re.sub(r"([(\{\[])\s*\n\s*", r"\1", ret)
    ret = re.sub(r"\s*\n\s*([)\}\]])", r"\1", ret)

    if not keep_quoted_spaces:
        return re.sub(r"\s+", " ", ret).strip()

    # Replace multiple whitespaces with single space, but preserve content in quotes
    def replacer(match):
        matched = match.group(0)
        # If it's a quoted string, return as-is
        if matched[0] in ('"', "'"):
            return matched
        # Otherwise, it's whitespace - compress to single space
        return " "

    # Match either quoted strings (with escaped quotes) or whitespace sequences
    ret = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|\s+', replacer, ret)
    return ret.strip()


def return_as_type(data: str | list[str], return_type: t.Type) -> str | list[str] | dict:
    """Convert data to the specified return type.

    Args:
        data: The input data to convert.
        return_type: The desired return type (e.g., str, list, dict).
        flatten: If True and return_type is str, flatten lists/tuples to single string.

    Returns:
        The data converted to the specified return type.
    """
    if isinstance(data, return_type):
        return data
    if return_type == str and isinstance(data, list):
        return "\n".join(data)
    if return_type == list and isinstance(data, str):
        return data.splitlines()
    raise TypeError(f"Cannot return {type(data)} as {return_type}")


def batch_iter(iterable: t.Iterable[t.Any], batch_size: int = 1000) -> t.Iterator[list[t.Any]]:
    """Yield batches of items from iterable.

    Args:
        iterable: Input iterable to batch
        batch_size: Number of elements per batch (default: 1000)

    Yields:
        Lists of up to batch_size elements
    """
    iterator = iter(iterable)
    while True:
        batch = list(islice(iterator, batch_size))
        if not batch:
            break
        yield batch


if __name__ == "__main__":
    print(deep_split(["boci,maci"]))
