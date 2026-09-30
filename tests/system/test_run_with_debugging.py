from .utils import SCRIPTS_PATH

SCRIPT = str(SCRIPTS_PATH / 'divide_with_zero.py')


def test_run_with_post_mortem(port, debuggee, client):
    script = debuggee('-m', 'madbg', 'run', '-p', port, SCRIPT, 'arg', '--flag')
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    output = c.run('p yo')
    assert 'ZeroDivisionError' in output
    assert '\n1\r' in c.run('c')
    assert c.wait() == 0
    exit_code, output = script.wait()
    assert exit_code != 0
    assert "ARGV ['arg', '--flag']" in output


def test_run_with_set_trace(port, debuggee, client):
    script = debuggee('-m', 'madbg', 'run', '-p', port, '--use-set-trace', '--no-post-mortem', SCRIPT)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    for _ in range(3):
        c.run('n')
    c.run('yo = 0')
    c.run('c')
    assert c.wait() == 0
    exit_code, output = script.wait()
    assert exit_code == 0
    assert 'ZeroDivisionError' not in output
