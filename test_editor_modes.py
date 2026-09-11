import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.layout.processors import TransformationInput
from notes import MemoryNote, build_app
from pane_control import PaneController


class NoPane:
    enabled = False


class EditorModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_focus_reports_preview_help_and_memory_only(self):
        with tempfile.TemporaryDirectory() as folder, create_pipe_input() as pipe:
            note = MemoryNote()
            app, buffer = build_app(note, pane_controller=NoPane(), input=pipe, output=DummyOutput())
            control = app.layout.current_control
            proc = control.input_processors[0]
            def displayed():
                doc = buffer.document
                ti = TransformationInput(control, doc, 0, lambda x: x, [('', doc.lines[0])], 80, 20)
                return ''.join(t for _, t in proc.apply_transformation(ti).fragments)
            task = asyncio.create_task(app.run_async())
            try:
                await asyncio.sleep(.05)
                pipe.send_text('# Memory')
                await asyncio.sleep(.05)
                self.assertEqual(displayed(), '# Memory')
                pipe.send_text('\x1b[O')
                await asyncio.sleep(.05)
                self.assertEqual(displayed(), 'Memory')
                self.assertEqual(buffer.text, '# Memory')
                pipe.send_text('\x1b[I')
                await asyncio.sleep(.05)
                self.assertEqual(displayed(), '# Memory')
                pipe.send_text('\x1bOP')  # F1
                await asyncio.sleep(.05)
                self.assertEqual(buffer.text, '# Memory')
                pipe.send_text('\x1bOP\x13\x11')
                await asyncio.wait_for(task, 2)
                self.assertEqual(note.text, '# Memory')
                self.assertEqual(list(Path(folder).iterdir()), [])
            finally:
                if not task.done():
                    app.exit()
                    await task


class PaneTests(unittest.TestCase):
    def test_right_pane_collapses_by_growing_left_neighbor_and_restores(self):
        width = [500]
        calls = []
        def api(*args):
            calls.append(args)
            if args[0] == 'identify':
                return {'caller': {'surface_id': 'note', 'workspace_id': 'w', 'window_id': 'win'}, 'focused': {}}
            if args[0] == 'list-panes':
                return {'panes': [
                    {'id': 'left', 'surface_ids': ['editor'], 'pixel_frame': {'x': 0, 'y': 0, 'width': 1000-width[0], 'height': 800}},
                    {'id': 'right', 'surface_ids': ['note'], 'pixel_frame': {'x': 1000-width[0], 'y': 0, 'width': width[0], 'height': 800}}]}
            if args[0] == 'resize-pane':
                amount = int(args[-1])
                if args[args.index('--pane')+1] == 'left':
                    self.assertIn('-R', args)
                    width[0] -= amount
                else:
                    self.assertIn('-L', args)
                    width[0] += amount
                return {}
            raise AssertionError(args)
        controller = PaneController()
        with patch('pane_control.cmux', side_effect=api):
            self.assertTrue(controller.toggle(False))
            self.assertEqual(width[0], 72)
            self.assertFalse(controller.toggle(True))
            self.assertEqual(width[0], 500)
