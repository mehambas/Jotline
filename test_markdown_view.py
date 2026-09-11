import unittest

from markdown_view import MarkdownDocument, LiveMarkdown
from prompt_toolkit.document import Document
from prompt_toolkit.layout.processors import TransformationInput
from prompt_toolkit.styles import Style
from wcwidth import wcswidth


def text(doc, row):
    return ''.join(t for _, t in doc.rows[row])


class DocumentTests(unittest.TestCase):
    def test_headings_strike_code_links_images_html(self):
        source = '\n\n'.join('#' * n + ' Level ' + str(n) for n in range(1, 7))
        doc = MarkdownDocument(source)
        for n in range(6):
            self.assertEqual(text(doc, n * 2), 'Level ' + str(n + 1))
        doc = MarkdownDocument('~~gone~~ `literal **code**` [label](https://example.com/a_(b)) ![Alt](img.png "title") <b>bold</b>')
        self.assertEqual(text(doc, 0), 'gone literal **code** label ▧ Alt bold')
        self.assertTrue(any('strike' in s for s, _ in doc.rows[0]))
        self.assertTrue(any('underline' in s and t == 'label' for s, t in doc.rows[0]))
        for style, _ in doc.rows[0]:
            Style.from_dict({'test': style}).get_attrs_for_style_str('class:test')

    def test_fenced_indented_and_unclosed_code(self):
        source = '```bash\n# not a heading\necho "hi"\n```\n\n    # indented\n\n~~~unknown\n**literal**'
        doc = MarkdownDocument(source)
        self.assertEqual(text(doc, 1), '│ # not a heading')
        self.assertEqual(text(doc, 2), '│ echo "hi"')
        self.assertEqual(text(doc, 5), '│ # indented')
        self.assertEqual(text(doc, 8), '│ **literal**')
        self.assertTrue(any('ansiyellow' in s for s, _ in doc.rows[2]))
        self.assertFalse(any('bold' in s for s, _ in doc.rows[1]))

    def test_quotes_rules_and_setext(self):
        doc = MarkdownDocument('> quote\n>\n>> **nested**\n\n---\n\nTitle\n=====', 30)
        self.assertEqual(text(doc, 0), '│ quote')
        self.assertEqual(text(doc, 1), '│ ')
        self.assertEqual(text(doc, 2), '│ │ nested')
        self.assertEqual(text(doc, 4), '─' * 29)
        self.assertEqual(text(doc, 6), 'Title')
        self.assertIn('bold', doc.rows[6][0][0])

    def test_multiline_inline_style_and_references(self):
        doc = MarkdownDocument('**first\nsecond**\n\n[site][target]\n\n[target]: https://example.com\n\nnote[^a]\n\n[^a]: **explanation**\n    continued')
        self.assertEqual(text(doc, 0), 'first')
        self.assertEqual(text(doc, 1), 'second')
        self.assertIn('bold', doc.rows[1][0][0])
        self.assertEqual(text(doc, 3), 'site')
        self.assertEqual(text(doc, 7), 'note[a]')
        self.assertEqual(text(doc, 9), '[a] explanation')
        self.assertEqual(text(doc, 10), 'continued')

    def test_table_alignment_unicode_and_narrow_pane(self):
        source = '| Left | Center | Right |\n|:---|:---:|---:|\n| 界 | *text* | 10 |\n| Longer | mid | 100 |'
        doc = MarkdownDocument(source, 80)
        widths = [wcswidth(text(doc, row)) for row in (0, 2, 3)]
        self.assertEqual(len(set(widths)), 1)
        self.assertIn('│    10 │', text(doc, 2))
        self.assertNotIn('*', text(doc, 2))
        self.assertTrue(text(doc, 1).startswith('├'))
        narrow = MarkdownDocument(source, 12)
        self.assertIn('Longer', text(narrow, 3))
        self.assertIn('100', text(narrow, 3))

    def test_mapping_on_visible_text(self):
        for source, word in [
            ('## heading', 'heading'), ('~~removed~~', 'removed'),
            ('[Label](https://example.com)', 'Label'),
            ('> quoted', 'quoted'), ('![Picture](image.png)', 'Picture'),
            ('| **Feature** | Value |\n|---|---|', 'Feature'),
        ]:
            doc = MarkdownDocument(source)
            display = text(doc, 0)
            transformation = doc.transformation(0)
            for j in range(len(word)):
                self.assertEqual(transformation.display_to_source(display.index(word) + j), source.index(word) + j)
            offsets = [transformation.display_to_source(i) for i in range(len(display) + 1)]
            self.assertEqual(offsets, sorted(offsets))

    def test_active_rows_and_cache_invalidation(self):
        source = '```\n# literal\n```\n\n---'
        processor = LiveMarkdown()
        for active in range(5):
            doc = Document(source, sum(len(s) + 1 for s in source.split('\n')[:active]))
            ti = TransformationInput(None, doc, active, lambda x: x, [('', doc.lines[active])], 20, 10)
            self.assertEqual(''.join(t for _, t in processor.apply_transformation(ti).fragments), doc.lines[active])
        for width in (20, 10):
            ti = TransformationInput(None, Document(source, 0), 4, lambda x: x, [('', '---')], width, 10)
            self.assertEqual(len(''.join(t for _, t in processor.apply_transformation(ti).fragments)), width - 1)

    def test_unknown_html_remains_visible(self):
        doc = MarkdownDocument('<script>alert(1)</script>\n\ntext <span class="x">kept</span>')
        self.assertEqual(text(doc, 0), '<script>alert(1)</script>')
        self.assertIn('<span class="x">', text(doc, 2))


if __name__ == '__main__':
    unittest.main()
