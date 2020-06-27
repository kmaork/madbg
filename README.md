# madbg
![](https://github.com/kmaork/madbg/workflows/Python%20package/badge.svg)

A remote python debugger based on the IPython debugger (like ipdb) featuring a full remote TTY!

madbg:
- Provides a fully featured remote tty, allowing sending keyboard signals to the debugger,
tab completion, command history, line editing and more.
- Runs the IPython debugger with all its capabilities
- Allows you to connect preemptively to a running program
- Affects the debugged program [minimally](#possible-effects)
- Provides TTY features even when debugged program is a deamon

## Installation
`pip install git+https://github.com/kmaork/madbg#egg=madbg`

Soon on PYPI!

## Usage
Madbg provide both a python API and a CLI.

### Starting a debugger
#### Using the CLI
Run a python file with automatic post-mortem (the "..." are extra arguments to pass to your program):
```
madbg run path_to_your_script.py ...
```
Run a python module similarly to `python -m`:
```
madbg run -m module.name ...
```
Start a script, starting the debugger from the first line: 
```
madbg run --use-set-trace script.py ...
```

#### Using Python
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

#### Using Python
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
madbg connect A.B.C.D 1337
```
## Platforms

Currently, madbg doesn't support windows and Python 2, but it's hopefully not far from both.

Tested on linux with Python 3.


## Possible effects

What madbg does that might affect your program:
- Changes the pgid and sid of your process
- Changes the CTTY of your process
- Affects child processes in unknown ways (I have not checked yet)

What madbg doesn't do:
- Writes or reads from stdio
- Feeds your cat
