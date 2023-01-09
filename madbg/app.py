import sys
from typing import TextIO, Optional
import threading

from prompt_toolkit import Application
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.widgets import RadioList, Dialog, Label, Button


def create_app(reader: TextIO, writer: TextIO, term_type: Optional[str] = None):
    current_thread = threading.current_thread()
    radio_list = RadioList([(t, t.name) for t in threading.enumerate() if t is not current_thread and t.is_alive()])

    dialog = Dialog(
        title='Choose thread to debug',
        body=HSplit(
            [Label(text='Choosing a thread will not attach to it', dont_extend_height=True), radio_list],
            padding=1,
        ),
        buttons=[
            Button(text='Debug!', handler=lambda: app.exit(result=radio_list.current_value)),
            Button(text='Exit', handler=lambda: app.exit(result=None)),
        ],
        with_background=True,
    )

    bindings = KeyBindings()
    bindings.add("tab")(focus_next)
    bindings.add("s-tab")(focus_previous)
    term_input = Vt100Input(reader)
    term_output = Vt100_Output.from_pty(writer)
    term_input.term = term_type
    term_output.term = term_type
    app = Application(
        layout=Layout(dialog),
        key_bindings=bindings,
        mouse_support=True,
        full_screen=True,
        input=term_input,
        output=term_output,
    )
    return app


if __name__ == '__main__':
    from threading import Thread
    from time import sleep

    Thread(target=sleep, args=(10,), daemon=True, name='Sleeper').start()
    print(create_app(sys.stdin, sys.stdout).run())
