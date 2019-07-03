import sys

import click
from madbg.client import debug
from madbg.consts import DEFAULT_IP, DEFAULT_PORT
from madbg import run_with_debugging


@click.group()
def cli():
    pass


@click.command()
@click.argument('ip', type=str, default=DEFAULT_IP)
@click.argument('port', type=int, default=DEFAULT_PORT)
def connect(ip, port):
    debug(ip, port)


@click.command(context_settings=dict(ignore_unknown_options=True,
                                     allow_interspersed_args=False,
                                     allow_extra_args=True))
@click.option('-i', '--bind_ip', type=str, default=DEFAULT_IP, show_default=True)
@click.option('-p', '--port', type=int, default=DEFAULT_PORT, show_default=True)
@click.option('-p', '--port', type=int, default=DEFAULT_PORT, show_default=True)
@click.option('-n', '--no_post_mortem', is_flag=True, flag_value=True, default=False)
@click.option('-s', '--use_set_trace', is_flag=True, flag_value=True, default=False)
@click.option('-m', '--run_as_module', is_flag=True, flag_value=True, default=False)
@click.argument('py_file', type=str, required=True)
@click.pass_context
def run(context, bind_ip, port, run_as_module, py_file, no_post_mortem, use_set_trace):
    argv = [sys.argv[0]] + context.args
    run_with_debugging(bind_ip, port, py_file, run_as_module, argv, not no_post_mortem, use_set_trace)


# TODO: add option to run packages with post mortem
cli.add_command(connect)
cli.add_command(run)
cli()
