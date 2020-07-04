import time
from contextlib import contextmanager
from itertools import count

from madbg.utils import use_context, loop_in_thread


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


def test_loop_in_thread():
    c = count()
    with loop_in_thread(c.__next__):
        time.sleep(0.05)
    assert next(c) > 3
