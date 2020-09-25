# madbg
[![Tests (GitHub Actions)](https://github.com/kmaork/madbg/workflows/Tests/badge.svg)](https://github.com/kmaork/madbg)
[![PyPI Supported Python Versions](https://img.shields.io/pypi/pyversions/madbg.svg)](https://pypi.python.org/pypi/madbg/)
[![PyPI version](https://badge.fury.io/py/madbg.svg)](https://badge.fury.io/py/madbg)
[![GitHub license](https://img.shields.io/github/license/kmaork/madbg)](https://github.com/kmaork/madbg/blob/master/LICENSE.txt)

A fully-featured remote debugger for python.

- Provides a full remote tty, allowing sending keyboard signals to the debugger,
tab completion, command history, line editing and more
- Runs the IPython debugger with all its capabilities
- Allows attaching to running programs preemptively (does not require gdb, unlike similar tools)
- Affects the debugged program [minimally](#possible-effects), although not yet recommended for use in production environment
- Provides TTY features even when debugged program is a deamon, or run outside a terminal.

## Installation
```
pip install madbg
```

## Usage
Madbg provide both a python API and a CLI.

### Attaching to a running process
```
madbg attach <pid>
```
Or
```python
import madbg
madbg.attach_to_process(pid)
```

### Starting a debugger
#### Using the CLI
Run a python file with automatic post-mortem:
```
madbg run path_to_your_script.py <args_for_script ...>
```
Run a python module similarly to `python -m`:
```
madbg run -m module.name <args_for_script ...>
```
Start a script, starting the debugger from the first line: 
```
madbg run --use-set-trace script.py <args_for_script ...>
```

#### Using the API
Start a debugger in the next line:
```python
madbg.set_trace()
```
Continue running the program until a client connects, then stop it and start a debugger:
```python
madbg.set_trace_on_connect()
```
After an exception has occurred, or in an exception context, start a debugger in the frame the exception was raised from:
```python
madbg.post_mortem()
```

### Connecting to a debugger
#### Using the CLI
```
madbg connect
```

#### Using the API
```python
madbg.connect_to_debugger()
```

### Connection
All madbg API functions and CLI entry points allow using a custom IP and port (the default is `127.0.0.1:3513`), for example:

```python
madbg.set_trace(ip='0.0.0.0', port=1337)
```
or
```
madbg connect 8.8.8.8 1337
```
## Platforms

Madbg supports linux with python>=3.7.

## Possible effects

What madbg does that might affect a debugged program:
- Changes the pgid and sid of the debugged process
- Changes the CTTY of the debugged process
- Affects child processes in unknown ways (Not tested yet)

What madbg doesn't do:
- Writes or reads from stdio
- Feeds your cat
