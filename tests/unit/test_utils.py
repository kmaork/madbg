from functools import wraps
from unittest.mock import Mock
from pytest import raises

from madbg.utils import Singleton


def function(callable):
    """
    Can be used to turn a mock into an unbound function.
    """

    @wraps(callable)
    def wrapper(*args, **kwargs):
        return callable(*args, **kwargs)

    return wrapper


def test_singleton():
    class Example(metaclass=Singleton):
        __new__ = function(Mock(side_effect=object.__new__, autospec=True))
        __init__ = function(Mock(side_effect=object.__init__, autospec=True))

    a = Example()
    b = Example()
    assert a is b
    Example.__new__.__wrapped__.assert_called_once_with(Example)
    Example.__init__.__wrapped__.assert_called_once_with(a)
    with raises(TypeError):
        Example(1)
