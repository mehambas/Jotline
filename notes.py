"""A single-buffer Markdown scratchpad. The file always contains original Markdown."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
from pathlib import Path
import re
import sys
import tempfile

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window, ConditionalContainer
from prompt_toolkit.filters import Condition
from prompt_toolkit.keys import Keys
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.styles import Style
from prompt_toolkit.mouse_events import MouseEventType


from markdown_view import LiveMarkdown, render_line

VERSION = (Path(__file__).with_name('VERSION').read_text().strip()
           if Path(__file__).with_name('VERSION').exists() else '0.1.0')

HELP = """Jotline — inline Markdown scratchpad

Commands
  jotline                 Open the shared scratchpad (auto-saved)
  jotline NOTE.md         Open or create a Markdown file
  jotline -t              Open a temporary note (memory only)
  jotline -g [NOTE.md]    Open one shared note in every cmux workspace
  jotline -gs             Stop the global watcher and close its views
  jotline --global-stop   Same as -gs
  jotline --help          Show command-line help

Keys
  F1 / Esc                Show or hide this help
  Ctrl+Q                  Save and quit
  Ctrl+S                  Save now
  Ctrl+Z / Ctrl+Y         Undo / redo
  Ctrl+T                  Toggle the checkbox on the current line
  Ctrl+B or click >/<     Collapse or restore a cmux note pane
  Mouse                   Move the cursor, select text, or scroll

When the note pane loses focus, every line is rendered as Markdown and the
cursor is hidden. Returning to the pane restores the editable line.
Temporary notes are never written to disk; copy anything you want to keep.
"""


class MemoryNote:
    temporary = True
    path = Path('Temporary note')
    text = ''

    def save(self, text):
        self.text = text

    def close(self):
        pass


class NoteControl(BufferControl):
    """A click may reveal syntax between mouse-down and mouse-up."""
    _press_position = None

    def mouse_handler(self, event):
        if event.event_type == MouseEventType.MOUSE_DOWN:
            self._press_position = event.position
        elif event.event_type == MouseEventType.MOUSE_UP:
            press = self._press_position
            self._press_position = None
            if press == event.position:
                return None
        return super().mouse_handler(event)


class NoteFile:
    def __init__(self, path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_name(self.path.name + ".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise OSError("This note is already open in another pane. Choose a different file.")
        try:
            self.last_bytes = self.path.read_bytes() if self.path.exists() else None
            self.text = self.last_bytes.decode("utf-8") if self.last_bytes is not None else ""
        except (OSError, UnicodeError):
            self.lock.close()
            raise

    def save(self, text):
        data = text.encode("utf-8")
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.last_bytes:
            raise OSError("The file changed externally; it was not overwritten. Copy the text elsewhere.")
        if data == self.last_bytes:
            return
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".jotline-", delete=False) as out:
                name = out.name
                if self.path.exists():
                    os.fchmod(out.fileno(), self.path.stat().st_mode & 0o777)
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
            self.last_bytes = data
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def close(self):
        self.lock.close()


def build_app(note, stop_token=None, pane_controller=None, **kwargs):
    from pane_control import PaneController
    pane_controller = pane_controller or PaneController()
    pane_state_path = stop_token.with_suffix('.pane-state') if stop_token else None
    state = {"error": "", "saved": True, "refreshing": False, "focused": True, "focus_events": 0,
             "collapsed": False, "resizing": False, "help": False, "notice": ""}
    buffer = Buffer(document=Document(note.text, len(note.text)), multiline=True,
                    read_only=Condition(lambda: state["help"]))

    def save(_=None):
        if state["refreshing"]:
            return True
        try:
            note.save(buffer.text)
            state.update(error="", saved=True)
            return True
        except OSError as error:
            state.update(error=str(error), saved=False)
            return False

    # Immediate atomic saving keeps even short scratchpad sessions durable.
    buffer.on_text_changed += save
    keys = KeyBindings()
    # Keep terminal focus reports out of the text buffer.
    ANSI_SEQUENCES['\x1b[I'] = Keys.Ignore
    ANSI_SEQUENCES['\x1b[O'] = Keys.Ignore

    @keys.add(Keys.Ignore)
    def terminal_focus(event):
        if event.data in ('\x1b[I', '\x1b[O'):
            state['focused'] = event.data == '\x1b[I'
            state['focus_events'] += 1
            event.app.invalidate()

    @keys.add('f1')
    def help_toggle(event):
        state['help'] = not state['help']
        event.app.layout.focus(help_control if state['help'] else rail if state['collapsed'] else control)

    @keys.add('escape', filter=Condition(lambda: state['help']))
    def help_close(event):
        state['help'] = False
        event.app.layout.focus(rail if state['collapsed'] else control)

    def publish_pane_state(collapsed):
        if not pane_state_path:
            return
        try:
            pane_state_path.write_text('collapsed\n' if collapsed else 'expanded\n')
        except OSError:
            pass

    async def resize_note(publish=True):
        if state['resizing']:
            return
        if not pane_controller.enabled:
            if pane_state_path:
                state['collapsed'] = not state['collapsed']
                publish_pane_state(state['collapsed'])
                app.invalidate()
                return
            state['notice'] = 'Pane resizing requires cmux; use your terminal controls elsewhere.'
            app.invalidate()
            return
        state['resizing'] = True
        try:
            state['collapsed'] = await asyncio.to_thread(pane_controller.toggle, state['collapsed'])
            if publish:
                publish_pane_state(state['collapsed'])
            state['notice'] = ''
            app.layout.focus(rail if state['collapsed'] else control)
        except (OSError, KeyError, StopIteration) as error:
            state['notice'] = str(error)
        finally:
            state['resizing'] = False
            app.invalidate()

    @keys.add('c-b')
    def collapse_toggle(event):
        event.app.create_background_task(resize_note())

    def arrow_click(event):
        if event.event_type == MouseEventType.MOUSE_UP:
            app.create_background_task(resize_note())


    @keys.add("c-q")
    def quit_app(event):
        if save() or getattr(note, "conflict_saved", False):
            event.app.exit()

    @keys.add("c-s")
    def save_now(event):
        save()

    @keys.add("c-z")
    def undo(event):
        buffer.undo()

    @keys.add("c-y")
    def redo(event):
        buffer.redo()

    @keys.add("tab")
    def tab(event):
        buffer.insert_text("    ")

    @keys.add("c-c")
    def copy(event):
        if buffer.selection_state:
            event.app.clipboard.set_data(buffer.copy_selection())

    @keys.add("c-v")
    def paste(event):
        buffer.paste_clipboard_data(event.app.clipboard.get_data())

    @keys.add("c-t")
    def toggle(event):
        doc = buffer.document
        match = re.match(r"^\s*[-+*] +\[([ xX])\]", doc.current_line)
        if match:
            pos = doc.translate_row_col_to_index(doc.cursor_position_row, match.start(1))
            value = "x" if match[1] == " " else " "
            buffer.document = Document(buffer.text[:pos] + value + buffer.text[pos + 1:], buffer.cursor_position)

    def status():
        if state["error"]:
            return [("ansired", " Save failed: " + state["error"])]
        if state['notice']:
            return [('dim', state['notice'])]
        arrow = [('dim', ' < ' if state['collapsed'] else ' > ', arrow_click)] if pane_controller.enabled else []
        if getattr(note, 'temporary', False):
            return arrow + [('dim', ' Temporary · not saved · F1 help · Ctrl+Q quit')]
        return arrow + [("dim", f" {note.path.name} · {'global · ' if getattr(note, 'shared', False) else ''}auto-save · F1 help · Ctrl+Q quit")]

    control = NoteControl(buffer=buffer, input_processors=[LiveMarkdown(lambda: state['focused'])], include_default_input_processors=True)
    help_control = BufferControl(buffer=Buffer(document=Document(HELP), read_only=True))
    rail = FormattedTextControl(lambda: [('dim', ' < ', arrow_click)], focusable=True)
    root = HSplit([
        ConditionalContainer(Window(help_control, wrap_lines=True, always_hide_cursor=True), Condition(lambda: state['help'])),
        ConditionalContainer(Window(control, wrap_lines=True,
            always_hide_cursor=Condition(lambda: not state['focused'])),
            Condition(lambda: not state['collapsed'] and not state['help'])),
        ConditionalContainer(Window(rail, always_hide_cursor=True),
            Condition(lambda: state['collapsed'] and not state['help'])),
        Window(FormattedTextControl(status), height=1),
    ])

    async def terminal_lifecycle():
        app.output.write_raw('\x1b[?1004h')
        app.output.flush()
        try:
            if pane_controller.enabled:
                sequence = state['focus_events']
                try:
                    focused = await asyncio.to_thread(pane_controller.focused)
                    if sequence == state['focus_events']:
                        state['focused'] = focused
                        app.invalidate()
                except (OSError, KeyError):
                    pass
            while True:
                await asyncio.sleep(.4)
                if pane_controller.enabled:
                    try:
                        focused = await asyncio.to_thread(pane_controller.focused)
                        if focused != state['focused']:
                            state['focused'] = focused
                            app.invalidate()
                    except (OSError, KeyError):
                        pass
                if pane_state_path and pane_state_path.exists() and not state['resizing']:
                    try:
                        desired = pane_state_path.read_text().strip() == 'collapsed'
                        if desired != state['collapsed']:
                            state['resizing'] = True
                            try:
                                # PaneController.toggle receives the current
                                # state and returns the opposite state.
                                state['collapsed'] = await asyncio.to_thread(
                                    pane_controller.toggle, state['collapsed'])
                                app.layout.focus(rail if state['collapsed'] else control)
                            finally:
                                state['resizing'] = False
                            app.invalidate()
                    except (OSError, UnicodeError, KeyError, StopIteration):
                        pass
        finally:
            app.output.write_raw('\x1b[?1004l')
            app.output.flush()

    async def refresh_shared():
        while True:
            await asyncio.sleep(.2)
            if stop_token and not stop_token.exists():
                if save() or getattr(note, 'conflict_saved', False):
                    app.exit()
                    if pane_state_path:
                        pane_state_path.unlink(missing_ok=True)
                    return
            if state['error']:
                continue
            try:
                if note.refresh():
                    state['refreshing'] = True
                    try:
                        # Remote updates reset undo so undo cannot revert another view's work.
                        doc = buffer.document
                        updated = Document(note.text)
                        pos = updated.translate_row_col_to_index(
                            min(doc.cursor_position_row, updated.line_count - 1), doc.cursor_position_col)
                        buffer.reset(Document(note.text, pos))
                    finally:
                        state['refreshing'] = False
                    app.invalidate()
            except (OSError, UnicodeError) as error:
                state.update(error=str(error), saved=False)
                app.invalidate()

    def start_shared(app):
        app.create_background_task(refresh_shared())

    app = Application(
        layout=Layout(root, focused_element=control), key_bindings=keys,
        full_screen=True, mouse_support=True,
        style=Style.from_dict({"": "fg:default bg:default", "selected": "reverse"}),
        include_default_pygments_style=False, **kwargs,
    )
    app.pre_run_callables.append(lambda: app.create_background_task(terminal_lifecycle()))
    if getattr(note, "shared", False):
        app.pre_run_callables.append(lambda: start_shared(app))
    return app, buffer


def main():
    parser = argparse.ArgumentParser(prog="jotline", description="An inline Markdown scratchpad for your terminal.",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=HELP)
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    parser.add_argument("file", nargs="?", type=Path, help="Markdown file to open or create")
    parser.add_argument("-t", "--temporary", action="store_true", help="Keep the note in memory only")
    parser.add_argument('-g', '--global', dest='global_mode', action='store_true', help='Open one shared note in every workspace of this cmux window')
    parser.add_argument('-gs', '--global-stop', action='store_true', help='Stop the global watcher and close its views')
    parser.add_argument('--shared', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--global-worker', help=argparse.SUPPRESS)
    parser.add_argument('--global-token', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.temporary and (args.file or args.global_mode or args.global_stop or args.shared or args.global_worker):
        parser.error('--temporary cannot be combined with a file, global mode, or global stop')
    if args.file is None:
        args.file = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'jotline/scratch.md' 
    if args.global_mode or args.global_stop or args.global_worker:
        from global_mode import dispatch
        try:
            dispatch(args)
        except (OSError, ValueError) as error:
            parser.exit(1, f'jotline: {error}\n')
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.exit(1, "jotline must run in an interactive terminal.\n")
    note = None
    try:
        if args.temporary:
            note = MemoryNote()
        elif args.shared:
            from shared_note import SharedNote
            note = SharedNote(args.file)
        else:
            note = NoteFile(args.file)
        app, _ = build_app(note, stop_token=args.global_token)
        app.run()
    except (OSError, UnicodeError) as error:
        parser.exit(1, f"jotline: {error}\n")
    finally:
        if note:
            note.close()


if __name__ == "__main__":
    main()
