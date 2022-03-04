import struct
from typing import Tuple, Union

STDIN_FILENO = 0
STDOUT_FILENO = 1
STDERR_FILENO = 2

DEFAULT_ADDR = ('127.0.0.1', 0xdb9)
DEFAULT_CONNECT_TIMEOUT = 10.

MESSAGE_LENGTH_FMT = 'I'
MESSAGE_LENGTH_LENGTH = struct.calcsize(MESSAGE_LENGTH_FMT)

Addr = Union[str, Tuple[str, int]]
