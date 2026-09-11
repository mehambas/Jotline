import asyncio
from pathlib import Path
import tempfile
import unittest

from prompt_toolkit.document import Document
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.layout.processors import TransformationInput

from notes import LiveMarkdown, NoteFile, build_app, render_line


class RenderingTests(unittest.TestCase):
    def test_supported_markdown_and_offsets(self):
        for source, expected in [
            ("# MeowDoku Notları", "MeowDoku Notları"),
            ("## İkinci", "İkinci"), ("### Üçüncü", "Üçüncü"),
            ("- liste", "• liste"), ("  * alt", "  • alt"),
            ("- [ ] görev", "☐ görev"), ("- [x] bitti", "☑ bitti"),
            ("**kalın** ve *italik* ve `kod`", "kalın ve italik ve kod"),
            ("**kalın *eğik* metin**", "kalın eğik metin"),
            ("`**ham**`", "**ham**"), ("henüz **yarım", "henüz **yarım"),
            ("snake_case_test", "snake_case_test"),
            ("# Türkçe 界 🐱", "Türkçe 界 🐱"),
        ]:
            with self.subTest(source=source):
                result = render_line(source)
                self.assertEqual("".join(t for _, t in result.fragments), expected)
                for col in range(len(expected)):
                    original = result.display_to_source(col)
                    self.assertEqual(result.source_to_display(original), col)
                self.assertEqual(result.display_to_source(len(expected)), len(source))

    def test_active_line_is_raw(self):
        doc = Document("# başlık\n**yazıyorum**", 15)
        proc = LiveMarkdown()
        for row, expected in [(0, "başlık"), (1, "**yazıyorum**")]:
            ti = TransformationInput(None, doc, row, lambda x: x,
                                     [("", doc.lines[row])], 20, 10)
            self.assertEqual("".join(t for _, t in proc.apply_transformation(ti).fragments), expected)


class StorageTests(unittest.TestCase):
    def test_save_reopen_lock_and_external_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note.md"
            note = NoteFile(path)
            try:
                note.save("# Türkçe\n- [ ] görev")
                self.assertEqual(path.read_text(), "# Türkçe\n- [ ] görev")
                with self.assertRaises(OSError):
                    NoteFile(path)
                path.write_text("external")
                with self.assertRaises(OSError):
                    note.save("overwrite")
                self.assertEqual(path.read_text(), "external")
            finally:
                note.close()
            reopened = NoteFile(path)
            self.assertEqual(reopened.text, "external")
            reopened.close()


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_typing_paste_navigation_toggle_undo_and_quit(self):
        with tempfile.TemporaryDirectory() as folder, create_pipe_input() as pipe:
            path = Path(folder) / "note.md"
            note = NoteFile(path)
            app, buffer = build_app(note, input=pipe, output=DummyOutput())
            task = asyncio.create_task(app.run_async())
            try:
                await asyncio.sleep(.05)
                pipe.send_text("# MeowDoku Notları\r")
                await asyncio.sleep(.05)
                self.assertEqual(buffer.document.cursor_position_row, 1)
                pipe.send_text("\x1b[200~- [ ] görev\n**Türkçe** 界 🐱\x1b[201~")
                await asyncio.sleep(.05)
                self.assertEqual(path.read_text(), "# MeowDoku Notları\n- [ ] görev\n**Türkçe** 界 🐱")
                # SGR mouse: click rendered heading, wait for raw-line repaint,
                # then release. Hidden '# ' must not cause a phantom selection.
                pipe.send_text("\x1b[<0;1;1M")
                await asyncio.sleep(.05)
                self.assertEqual(buffer.cursor_position, 2)
                pipe.send_text("\x1b[<0;1;1m")
                await asyncio.sleep(.05)
                self.assertEqual(buffer.cursor_position, 2)
                self.assertIsNone(buffer.selection_state)
                pipe.send_text("\x1b[B\x1b[B")
                await asyncio.sleep(.05)
                pipe.send_text("\x1b[A\x14")
                await asyncio.sleep(.05)
                self.assertIn("- [x] görev", buffer.text)
                pipe.send_text("\x1a")
                await asyncio.sleep(.05)
                self.assertIn("- [ ] görev", buffer.text)
                pipe.send_text("\x11")
                await asyncio.wait_for(task, 2)
                self.assertEqual(path.read_text(), buffer.text)
            finally:
                if not task.done():
                    app.exit()
                    await task
                note.close()


if __name__ == "__main__":
    unittest.main()
