"""Tests for calling_signature function."""

import pytest

from umann.utils.trace_utils import calling_signature

pytestmark = pytest.mark.unit


def test_calling_signature_with_positional_args():
    """Test calling_signature with only positional arguments."""

    def my_func(_a, _b, _c):
        return calling_signature()

    result = my_func(1, 2, 3)
    assert result == "my_func(1, 2, 3)"


def test_calling_signature_with_kwargs():
    """Test calling_signature with keyword arguments."""

    def my_func(_a, _b=None, _c=None):
        return calling_signature()

    result = my_func(1, _b=2, _c=3)
    assert result == "my_func(1, 2, 3)"


def test_calling_signature_with_mixed_args():
    """Test calling_signature with mixed positional and keyword arguments."""

    def my_func(_a, _b, _c=10, _d=20):
        return calling_signature()

    result = my_func(1, 2, _c=30)
    assert result == "my_func(1, 2, 30, 20)"


def test_calling_signature_with_strings():
    """Test calling_signature with string arguments."""

    def my_func(_name, _path):
        return calling_signature()

    result = my_func("test", "/path/to/file")
    assert result == "my_func('test', '/path/to/file')"


def test_calling_signature_with_complex_types():
    """Test calling_signature with complex argument types."""

    def my_func(_items, _mapping):
        return calling_signature()

    result = my_func([1, 2, 3], {"key": "value"})
    assert result == "my_func([1, 2, 3], {'key': 'value'})"


def test_calling_signature_no_args():
    """Test calling_signature with no arguments."""

    def my_func():
        return calling_signature()

    result = my_func()
    assert result == "my_func()"


def test_calling_signature_in_method():
    """Test calling_signature inside a class method (should exclude 'self')."""

    # pylint: disable=too-few-public-methods
    class MyClass:
        """Test class for calling_signature."""

        def my_method(self, _a, _b):
            return calling_signature()

    obj = MyClass()
    result = obj.my_method(10, 20)
    assert result == "my_method(10, 20)"


def test_calling_signature_with_none():
    """Test calling_signature with None values."""

    def my_func(_a, _b=None):
        return calling_signature()

    result = my_func(1, None)
    assert result == "my_func(1, None)"


def test_calling_signature_with_bool():
    """Test calling_signature with boolean values."""

    def my_func(_flag, _verbose=False):
        return calling_signature()

    result = my_func(True, _verbose=True)
    assert result == "my_func(True, True)"


def test_calling_signature_practical_example():
    """Test a practical example of using calling_signature for logging."""

    def process_data(_data, _validate=True, _transform=False):
        sig = calling_signature()
        # In a real scenario, you might log this
        return f"Called: {sig}"

    result = process_data([1, 2, 3], _validate=False)
    assert result == "Called: process_data([1, 2, 3], False, False)"
