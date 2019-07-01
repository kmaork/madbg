import click
from madbg.client import debug
from madbg.consts import DEFAULT_PORT


@click.group()
def cli():
    pass


@click.command()
@click.argument('ip', type=str, default='127.0.0.1')
@click.argument('port', type=int, default=DEFAULT_PORT)
def connect(ip, port):
    debug(ip, port)


# TODO: add option to run packages with post mortem
cli.add_command(connect)
cli()
