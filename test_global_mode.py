import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from global_mode import Watcher, rightmost_pane, size_global_pane
from notes import NoteFile, build_app
from shared_note import SharedNote


class SharedStorageTests(unittest.TestCase):
    def test_refresh_conflict_recovery_and_exclusive_editor(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'global.md'
            a, b = SharedNote(path), SharedNote(path)
            try:
                with self.assertRaises(OSError):
                    NoteFile(path)
                a.save('first 🐱')
                self.assertTrue(b.refresh())
                self.assertEqual(b.text, 'first 🐱')
                b.save('second')
                with self.assertRaises(OSError):
                    a.save('local draft')
                self.assertEqual(path.read_text(), 'second')
                self.assertEqual(a.conflict_path.read_text(), 'local draft')
                with self.assertRaises(OSError):
                    a.save('updated local draft')
                self.assertEqual(path.read_text(), 'second')
                self.assertEqual(a.conflict_path.read_text(), 'updated local draft')
            finally:
                a.close()
                b.close()
            exclusive = NoteFile(path)
            try:
                with self.assertRaises(OSError):
                    SharedNote(path)
            finally:
                exclusive.close()


class SharedInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_live_views_and_stop(self):
        with tempfile.TemporaryDirectory() as folder, create_pipe_input() as p1, create_pipe_input() as p2:
            path = Path(folder) / 'shared.md'
            token = Path(folder) / 'enabled'
            token.touch()
            a, b = SharedNote(path), SharedNote(path)
            app1, buf1 = build_app(a, stop_token=token, input=p1, output=DummyOutput())
            app2, buf2 = build_app(b, stop_token=token, input=p2, output=DummyOutput())
            tasks = [asyncio.create_task(app.run_async()) for app in (app1, app2)]
            try:
                await asyncio.sleep(.05)
                p1.send_text('# Global 🐱')
                await asyncio.sleep(.3)
                self.assertEqual(buf2.text, '# Global 🐱')
                p2.send_text('\x1b[F\rSecond view')
                await asyncio.sleep(.3)
                self.assertEqual(buf1.text, '# Global 🐱\nSecond view')
                self.assertEqual(path.read_text(), buf1.text)
                token.unlink()
                await asyncio.wait_for(asyncio.gather(*tasks), 2)
            finally:
                for app, task in zip((app1, app2), tasks):
                    if not task.done():
                        app.exit()
                await asyncio.gather(*tasks, return_exceptions=True)
                a.close()
                b.close()


class WatcherTests(unittest.TestCase):
    def test_global_only_pane_is_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / 'enabled'
            token.touch()
            calls = []
            def api(*args):
                calls.append(args)
                if args[0] == 'list-workspaces':
                    return {'workspaces': [{'id': 'a'}]}
                if args[0] == 'list-panes':
                    return {'panes': [{'id': 'global-pane', 'surface_ids': ['global-surface'],
                                       'selected_surface_ref': 'surface:editor',
                                       'pixel_frame': {'x': 0, 'y': 0, 'width': 420, 'height': 800}}]}
                if args[0] == 'new-split':
                    return {'surface_id': 'global-surface'}
                return {}
            watcher = Watcher('window:1', Path(folder) / 'note.md', token)
            with patch('global_mode.cmux', side_effect=api):
                watcher.tick()
                watcher.tick()
            self.assertTrue(any(c[0] == 'close-surface' for c in calls))

    def test_global_pane_gets_fixed_width(self):
        width = [900]
        def api(*args):
            if args[0] == 'list-panes':
                return {'panes': [
                    {'id': 'left', 'surface_ids': ['editor'],
                     'pixel_frame': {'x': 0, 'y': 0, 'width': 1100 - width[0], 'height': 800}},
                    {'id': 'global', 'surface_ids': ['global'],
                     'pixel_frame': {'x': 1100 - width[0], 'y': 0, 'width': width[0], 'height': 800}}]}
            if args[0] == 'resize-pane':
                width[0] = 420
                return {}
            raise AssertionError(args)
        with patch('global_mode.cmux', side_effect=api):
            size_global_pane('window:1', 'workspace:1', 'global')
        self.assertEqual(width[0], 420)

    def test_existing_new_remote_workspaces_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / 'enabled'
            token.touch()
            workspaces = [{'id': 'a'}, {'id': 'remote', 'remote': {'enabled': True}}]
            calls = []
            def api(*args):
                calls.append(args)
                if args[0] == 'list-workspaces':
                    return {'workspaces': list(workspaces)}
                if args[0] == 'list-panes':
                    return {'panes': [
                        {'ref': 'pane:right', 'selected_surface_ref': 'surface:right',
                         'pixel_frame': {'x': 400, 'y': 0, 'width': 200}},
                        {'ref': 'pane:left', 'selected_surface_ref': 'surface:left',
                         'pixel_frame': {'x': 0, 'y': 0, 'width': 400}}]}
                if args[0] == 'new-split':
                    return {'surface_ref': 'surface:1'}
                return {}
            watcher = Watcher('window:1', Path(folder) / "a 'quoted'.md", token)
            with patch('global_mode.cmux', side_effect=api):
                watcher.tick()
                watcher.tick()
                workspaces.append({'id': 'b'})
                watcher.tick()
                self.assertEqual(sum(c[0] == 'new-split' for c in calls), 2)
                self.assertTrue(all(c[c.index('--surface') + 1] == 'surface:right' for c in calls if c[0] == 'new-split'))
                self.assertTrue(all('--focus' in c and c[-1] == 'false' for c in calls if c[0] == 'new-split'))
                token.unlink()
                workspaces.append({'id': 'c'})
                watcher.tick()
                self.assertEqual(sum(c[0] == 'new-split' for c in calls), 2)

    def test_launch_failure_does_not_repeat_pane_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / 'enabled'
            token.touch()
            def api(*args):
                if args[0] == 'list-workspaces':
                    return {'workspaces': [{'id': 'a'}]}
                if args[0] == 'list-panes':
                    return {'panes': [
                        {'ref': 'pane:right', 'selected_surface_ref': 'surface:right',
                         'pixel_frame': {'x': 400, 'y': 0, 'width': 200}},
                        {'ref': 'pane:left', 'selected_surface_ref': 'surface:left',
                         'pixel_frame': {'x': 0, 'y': 0, 'width': 400}}]}
                if args[0] == 'new-split':
                    return {'surface_ref': 'surface:1'}
                raise OSError('launch failed')
            watcher = Watcher('window:1', Path(folder) / 'note.md', token)
            with patch('global_mode.cmux', side_effect=api) as mocked:
                watcher.tick()
                watcher.tick()
                self.assertEqual(sum(c.args[0] == 'new-split' for c in mocked.call_args_list), 1)
                self.assertIn('a', watcher.errors)
