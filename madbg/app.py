from typing import TextIO, Optional
import threading

from prompt_toolkit import Application
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.widgets import RadioList, Dialog, Label, Button


def create_app(reader: TextIO, writer: TextIO, term_type: Optional[str] = None, threads_blacklist=None):
    if threads_blacklist is None:
        threads_blacklist = set()
    radio_list = RadioList([(t, t.name) for t in threading.enumerate() if t not in threads_blacklist and t.is_alive()])

    dialog = Dialog(
        title=[('fg:darkgreen', 'Madbg')],
        body=HSplit(
            [Label(text='Choose a thread:', dont_extend_height=True), radio_list],
            padding=1,
        ),
        buttons=[
            Button(text='Debug!', handler=lambda: app.exit(result=radio_list.current_value),
                   left_symbol='[', right_symbol=']'),
            Button(text='Exit', handler=lambda: app.exit(result=None), left_symbol='[', right_symbol=']'),
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
