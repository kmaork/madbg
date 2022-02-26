from contextlib import contextmanager
from functools import wraps
from unittest.mock import Mock

from pytest import raises

from madbg.utils import use_context, Singleton


def test_use_context():
    val1 = 'simbala'
    val2 = 'sortego'
    vals_added_on_exit = []

    @contextmanager
    def ctx_mgr(val):
        yield val
        vals_added_on_exit.append(val)

    val, exit_stack = use_context(ctx_mgr(val1))
    assert val is val1
    val, exit_stack2 = use_context(ctx_mgr(val2), exit_stack)
    assert exit_stack2 is exit_stack
    assert val is val2
    exit_stack.close()
    assert vals_added_on_exit == [val2, val1]


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
