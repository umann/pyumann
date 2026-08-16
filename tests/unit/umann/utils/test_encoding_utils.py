"""Module for testing encoding utilities."""

import pytest

from umann.utils.encoding_utils import fix_str_encoding

pytestmark = pytest.mark.unit


def test_fix_str_encoding_no_change_ascii():
    assert fix_str_encoding("Hello World") == "Hello World"


def test_fix_str_encoding_mojibake_hungarian():
    # cspell:words MagyarorszÃ
    # 'Magyarország' UTF-8 mis-decoded as Latin1 becomes 'MagyarorszÃ¡g'
    assert fix_str_encoding("MagyarorszÃ¡g") == "Magyarország"


def test_fix_str_encoding_mojibake_cafe():
    # 'Café' UTF-8 bytes mis-decoded as Latin1/CP1252 => 'CafÃ©'
    assert fix_str_encoding("CafÃ©") == "Café"


def test_fix_str_encoding_error_unfixable():
    # Sequence 'Ã\x82' decodes back to 'Â' (still suspicious) for all attempted source encodings,
    # original contains a lead + continuation pattern so ValueError should be raised.
    with pytest.raises(ValueError):
        fix_str_encoding("FooÃ\x82Bar")


def test_fix_str_encoding_converts_numbers_to_strings():
    assert fix_str_encoding(123) == "123"
    assert fix_str_encoding(1.5) == "1.5"


def test_fix_str_encoding_passes_through_bool_and_none():
    assert fix_str_encoding(True) is True
    assert fix_str_encoding(False) is False
    assert fix_str_encoding(None) is None


def test_fix_str_encoding_empty_string():
    assert fix_str_encoding("") == ""  # empty str returns as-is


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["MagyarorszÃ¡g", 123], ["Magyarország", "123"]),
        (("CafÃ©", None), ("Café", None)),
        ({"CafÃ©", "Hello"}, {"Café", "Hello"}),
        ({"place": "MagyarorszÃ¡g", "count": 123}, {"place": "Magyarország", "count": "123"}),
    ],
)
def test_fix_str_encoding_recursively_converts_collections(value, expected):
    assert fix_str_encoding(value) == expected


def test_fix_str_encoding_preserves_dictionary_keys():
    assert fix_str_encoding({"CafÃ©": "MagyarorszÃ¡g"}) == {"CafÃ©": "Magyarország"}


def test_fix_str_encoding_rejects_unsupported_types():
    with pytest.raises(TypeError, match="Expected str or list/tuple/set of str"):
        fix_str_encoding(object())
