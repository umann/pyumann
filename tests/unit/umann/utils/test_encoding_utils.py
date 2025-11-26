"""Module for testing encoding utilities."""

import pytest

from umann.utils.encoding_utils import fix_str_encoding

pytestmark = pytest.mark.unit


def test_fix_str_encoding_no_change_ascii():
    assert fix_str_encoding("Hello World") == "Hello World"


def test_fix_str_encoding_mojibake_hungarian():
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


def test_fix_str_encoding_passthrough_non_string():
    assert fix_str_encoding(123) == 123  # non-str returns as-is
    assert fix_str_encoding(None) is None
    assert fix_str_encoding("") == ""  # empty str returns as-is
