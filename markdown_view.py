"""Document-aware Markdown rendering with source/display cursor mappings."""
from bisect import bisect_left
from difflib import SequenceMatcher
import re

from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from prompt_toolkit.layout.processors import Processor, Transformation
from pygments import lex
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Keyword, Name, Number, String
from pygments.util import ClassNotFound
from wcwidth import wcswidth

MD = MarkdownIt('commonmark').enable(['table', 'strikethrough']).use(footnote_plugin, move_to_end=False)
HEADINGS = {'h1': 'bold ansicyan', 'h2': 'bold ansimagenta', 'h3': 'bold ansiblue',
            'h4': 'bold', 'h5': 'italic ansicyan', 'h6': 'italic'}
INLINE = {'strong_open': 'bold', 'em_open': 'italic', 's_open': 'strike',
          'link_open': 'ansicyan underline'}
HTML = {'b': 'bold', 'strong': 'bold', 'i': 'italic', 'em': 'italic',
        's': 'strike', 'del': 'strike', 'u': 'underline', 'code': 'ansiyellow'}


def mapped(source, fragments):
    """Map visible characters, including inserted decorations, to source positions."""
    visible = ''.join(t for _, t in fragments)
    offsets = [0] * len(visible)
    for kind, a, b, c, d in SequenceMatcher(None, source, visible, autojunk=False).get_opcodes():
        for i in range(c, d):
            offsets[i] = a + i - c if kind == 'equal' else min(a, len(source))
    return Transformation(fragments,
        source_to_display=lambda pos: bisect_left(offsets, pos),
        display_to_source=lambda pos: offsets[max(0, pos)] if pos < len(offsets) else len(source))


def inline_rows(children, base=''):
    rows = [[]]
    stack = [base]
    html_stack = []
    for token in children or []:
        kind = token.type
        style = ' '.join(stack + [s for _, s in html_stack])
        if kind in INLINE:
            stack.append(INLINE[kind])
        elif kind in ('strong_close', 'em_close', 's_close', 'link_close'):
            if len(stack) > 1:
                stack.pop()
        elif kind in ('softbreak', 'hardbreak'):
            rows.append([])
        elif kind == 'code_inline':
            rows[-1].append((style + ' ansiyellow', token.content))
        elif kind == 'image':
            rows[-1].append((style + ' dim', '▧ ' + (token.content or 'Resim')))
        elif kind == 'footnote_ref':
            rows[-1].append((style + ' ansicyan', '[' + str(token.meta.get('label', token.meta['id'] + 1)) + ']'))
        elif kind == 'html_inline':
            match = re.fullmatch(r'<(/?)(\w+)\s*>', token.content)
            if match and match[2].lower() in HTML:
                tag = match[2].lower()
                if match[1]:
                    if html_stack and html_stack[-1][0] == tag:
                        html_stack.pop()
                else:
                    html_stack.append((tag, HTML[tag]))
            else:
                rows[-1].append((style, token.content))
        elif token.content:
            # Preserve physical lines even for unusual inline HTML.
            for j, part in enumerate(token.content.split('\n')):
                if j:
                    rows.append([])
                rows[-1].append((style, part))
    return rows


def code_rows(content, language):
    try:
        lexer = get_lexer_by_name(language, stripnl=False, ensurenl=False) if language else None
    except ClassNotFound:
        lexer = None
    rows = [[]]
    tokens = lex(content, lexer) if lexer else [(None, content)]
    for token, value in tokens:
        style = ''
        for family, candidate in ((Comment, 'dim italic'), (Keyword, 'ansimagenta bold'),
                                  (String, 'ansiyellow'), (Number, 'ansicyan'), (Name.Builtin, 'ansiblue')):
            if token is not None and token in family:
                style = candidate
                break
        for j, part in enumerate(value.split('\n')):
            if j:
                rows.append([])
            if part:
                rows[-1].append((style, part))
    return rows


class MarkdownDocument:
    def __init__(self, text, width=80):
        self.lines = text.split('\n')
        self.rows = [[('', line)] for line in self.lines]
        self.width = max(1, width)
        self.transformations = {}
        tokens = MD.parse(text)
        quotes = 0
        heading = ''
        table = None
        table_row = None
        cell_style = ''
        align = ''
        for token in tokens:
            kind = token.type
            if kind == 'blockquote_open':
                quotes += 1
                if token.map:
                    for row in range(*token.map):
                        if re.fullmatch(r'[ >]*', self.lines[row]):
                            self.rows[row] = [('dim', '│ ' * quotes)]
            elif kind == 'blockquote_close':
                quotes -= 1
            elif kind == 'heading_open':
                heading = HEADINGS[token.tag]
                if token.map and token.markup in ('=', '-'):
                    self.rows[token.map[1] - 1] = [('', '')]
            elif kind == 'heading_close':
                heading = ''
            elif kind == 'table_open':
                table = {'map': token.map, 'rows': []}
            elif kind == 'tr_open' and table is not None:
                table_row = [token.map[0], []]
                table['rows'].append(table_row)
            elif kind in ('th_open', 'td_open'):
                cell_style = 'bold' if kind == 'th_open' else ''
                align = (token.attrGet('style') or '').replace('text-align:', '')
            elif kind == 'table_close':
                self.render_table(table, quotes)
                table = None
            elif kind == 'inline' and token.map:
                parts = inline_rows(token.children, cell_style if table is not None else heading)
                if table is not None:
                    table_row[1].append((parts[0], align))
                    continue
                for j, row in enumerate(range(*token.map)):
                    if j >= len(parts):
                        break
                    prefix = [('dim', '│ ' * quotes)] if quotes else []
                    source = self.lines[row]
                    # Markdown parser identifies blocks; these only decorate their source prefixes.
                    leader = re.match(r'^(?: {0,3}> ?)*(\s*)(?:([-+*]) |(\d+[.)]) )', source)
                    if leader and j == 0:
                        prefix.append(('dim', leader[1] + ('• ' if leader[2] else leader[3] + ' ')))
                        if parts[j]:
                            s, value = parts[j][0]
                            box = re.match(r'^\[([ xX])\](?: |$)', value)
                            if box:
                                prefix[-1] = ('dim', leader[1])
                                prefix.append(('ansigreen' if box[1] != ' ' else 'dim', '☑ ' if box[1] != ' ' else '☐ '))
                                parts[j][0] = (s, value[box.end():])
                    foot = re.match(r'^\s*\[\^([^]]+)\]:\s*', source)
                    if foot:
                        prefix.append(('ansicyan', '[' + foot[1] + '] '))
                    self.rows[row] = prefix + parts[j]
            elif kind == 'hr' and token.map:
                self.rows[token.map[0]] = [('dim', '│ ' * quotes + '─' * max(1, self.width - quotes * 2 - 1))]
            elif kind in ('fence', 'code_block') and token.map:
                first, end = token.map
                start = first + (kind == 'fence')
                language = token.info.split()[0] if token.info.strip() else ''
                if kind == 'fence':
                    self.rows[first] = [('dim', '│ ' * quotes + '┌─ ' + (language or 'code'))]
                content_rows = code_rows(token.content, language)
                count = len(token.content.splitlines())
                for j in range(min(count, end - start)):
                    self.rows[start + j] = [('dim', '│ ' * (quotes + 1))] + content_rows[j]
                if kind == 'fence' and start + count < end:
                    self.rows[end - 1] = [('dim', '│ ' * quotes + '└─')]

    def render_table(self, table, quotes):
        rows = table['rows']
        columns = max(len(cells) for _, cells in rows)
        widths = [0] * columns
        for _, cells in rows:
            for j, (fragments, _) in enumerate(cells):
                widths[j] = max(widths[j], wcswidth(''.join(t for _, t in fragments)))
        # Reduce padding in narrow panes; never discard note content.
        budget = max(1, (self.width - 2 * quotes - 3 * columns - 1) // columns)
        widths = [min(w, budget) for w in widths]
        for row, cells in rows:
            result = [('dim', '│ ' * quotes + '│ ')]
            for j, (fragments, alignment) in enumerate(cells):
                gap = max(0, widths[j] - wcswidth(''.join(t for _, t in fragments)))
                left = gap if alignment == 'right' else gap // 2 if alignment == 'center' else 0
                result += [('', ' ' * left)] + fragments + [('', ' ' * (gap - left)), ('dim', ' │ ')]
            self.rows[row] = result
        separator = rows[0][0] + 1
        self.rows[separator] = [('dim', '│ ' * quotes + '├' + '┼'.join('─' * (w + 2) for w in widths) + '┤')]

    def transformation(self, row):
        if row not in self.transformations:
            self.transformations[row] = mapped(self.lines[row], self.rows[row])
        return self.transformations[row]


def render_line(text):
    return MarkdownDocument(text).transformation(0)


class LiveMarkdown(Processor):
    def __init__(self, editing=lambda: True):
        self.editing = editing
        self.key = None
        self.parsed = None

    def apply_transformation(self, ti):
        if self.editing() and ti.lineno == ti.document.cursor_position_row:
            return Transformation(ti.fragments)
        key = (ti.document.text, ti.width)
        if key != self.key:
            self.parsed = MarkdownDocument(*key)
            self.key = key
        return self.parsed.transformation(ti.lineno)
