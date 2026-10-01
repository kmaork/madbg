def test_post_mortem(port, debuggee, client):
    script = debuggee('post_mortem.py', port)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    assert 'divide' in c.run('p b')
    assert '\n0\r' in c.run('c')
    assert c.wait() == 0
    exit_code, output = script.wait()
    assert exit_code == 0
    assert 'RESULT done' in output
