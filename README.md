# madbg
A remote python debugger based on the IPython debugger (like ipdb) featuring a full remote TTY!

Currently doesn't support windows.

## Installation
`pip install git+https://github.com/kmaork/madbg#egg=madbg`

## Usage example
In a python script, add this code:
```python
import madbg
madbg.set_trace()
```
Then, in a different terminal, run

`madbg connect`

And voila! You have a remote debugger allowing line editing, tab comletion, signal handling and more :)

<br>

Of course, if you want to connect from a remote system you could use, for example:
```python
madbg.set_trace(ip='0.0.0.0', port=1337)
```
And

`madbg connect A.B.C.D 1337`
