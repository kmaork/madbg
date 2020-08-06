import sys
from click import ClickException, group, argument, option, pass_context

from madbg.api import attach_to_process
from madbg.client import connect_to_debugger
from madbg.consts import DEFAULT_IP, DEFAULT_PORT
from madbg import run_with_debugging, attach_to_process


@group()
def cli():
    pass


@cli.command()
@argument('ip', type=str, default=DEFAULT_IP)
@argument('port', type=int, default=DEFAULT_PORT)
def connect(ip, port):
    try:
        connect_to_debugger(ip, port)
    except ConnectionRefusedError:
        raise ClickException('Connection refused :(')


@cli.command()
@argument('pid', type=int)
@argument('port', type=int, default=DEFAULT_PORT)
def attach(pid, port):
    attach_to_process(pid, port)


@cli.command(context_settings=dict(ignore_unknown_options=True,
                                   allow_interspersed_args=False,
                                   allow_extra_args=True))
@option('-i', '--bind_ip', type=str, default=DEFAULT_IP, show_default=True)
@option('-p', '--port', type=int, default=DEFAULT_PORT, show_default=True)
@option('-n', '--no-post-mortem', is_flag=True, flag_value=True, default=False)
@option('-s', '--use-set-trace', is_flag=True, flag_value=True, default=False)
@option('-m', '--run-as-module', is_flag=True, flag_value=True, default=False)
@argument('py_file', type=str, required=True)
@pass_context
def run(context, bind_ip, port, run_as_module, py_file, no_post_mortem, use_set_trace):
    argv = [sys.argv[0], *context.args]
    run_with_debugging(bind_ip, port, py_file, run_as_module, argv, not no_post_mortem, use_set_trace)


if __name__ == '__main__':
    cli()
