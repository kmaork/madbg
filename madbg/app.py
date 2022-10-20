from prompt_toolkit import Application
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.widgets import RadioList, Dialog, Label, Button

from .tty_utils import PTY


def create(values, pty: PTY):
    radio_list = RadioList(values)

    dialog = Dialog(
        title='Choose thread to debug',
        body=HSplit(
            [Label(text='bla', dont_extend_height=True), radio_list],
            padding=1,
        ),
        buttons=[
            Button(text='OK', handler=lambda: app.exit(result=radio_list.current_value)),
            Button(text='Cancel', handler=lambda: app.exit(result=None)),
        ],
        with_background=True,
    )

    bindings = KeyBindings()
    bindings.add("tab")(focus_next)
    bindings.add("s-tab")(focus_previous)

    app = Application(
        layout=Layout(dialog),
        key_bindings=bindings,
        mouse_support=True,
        full_screen=True,
        input=Vt100Input(pty.slave_reader),
        output=Vt100_Output.from_pty(pty.slave_writer),
    )
    return app
