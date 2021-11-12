import sys
from click import ClickException, group, argument, option, pass_context

from madbg.client import connect_to_debugger
from madbg.consts import DEFAULT_IP, DEFAULT_PORT, DEFAULT_CONNECT_TIMEOUT
from madbg import run_with_debugging, attach_to_process

port_argument = argument('port', type=int, default=DEFAULT_PORT)
connect_timeout_option = option('-t', '--timeout', type=float, default=DEFAULT_CONNECT_TIMEOUT, show_default=True,
                                help='Connection timeout in seconds')


@group(context_settings=dict(help_option_names=['-h', '--help']))
def cli():
    pass


@cli.command()
@argument('ip', type=str, default=DEFAULT_IP)
@port_argument
@connect_timeout_option
def connect(ip, port, timeout):
    try:
        connect_to_debugger(ip, port, timeout=timeout)
    except ConnectionRefusedError:
        raise ClickException('Connection refused - did you use the right port?')


@cli.command()
@argument('pid', type=int)
@port_argument
@connect_timeout_option
def attach(pid, port, timeout):
    attach_to_process(pid, port, connect_timeout=timeout)


@cli.command(help='Run the given script or module with debugging features. '
                  'Flags given after the script name will be passed to the script as is.',
             context_settings=dict(ignore_unknown_options=True,
                                   allow_interspersed_args=False,
                                   allow_extra_args=True))
@option('-i', '--bind_ip', type=str, default=DEFAULT_IP, show_default=True)
@option('-p', '--port', type=int, default=DEFAULT_PORT, show_default=True)
@option('-n', '--no-post-mortem', is_flag=True, flag_value=True, default=False)
@option('-s', '--use-set-trace', is_flag=True, flag_value=True, default=False)
@option('-m', '--run-as-module', is_flag=True, flag_value=True, default=False, help='Works the same as python -m')
@argument('py_file', type=str, required=True)
@pass_context
def run(context, bind_ip, port, run_as_module, py_file, no_post_mortem, use_set_trace):
    argv = [sys.argv[0], *context.args]
    run_with_debugging(py_file, run_as_module=run_as_module, argv=argv, use_post_mortem=not no_post_mortem,
                       use_set_trace=use_set_trace, ip=bind_ip, port=port)


if __name__ == '__main__':
    cli()
