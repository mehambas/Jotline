# Jotline

## Inline preview

### Heading three

#### Heading four

##### Heading five

###### Heading six

**Bold**, *italic*, ~~strikethrough~~ and `inline code`.

- [ ] Write a note
- [x] Keep the terminal theme

---

> A quote with **emphasis**.
>
>> A nested quote.

[Markdown documentation](https://www.markdownguide.org/)

![An example image](https://example.com/image.png "Image title")

## Code

```bash
# This stays a comment, not a heading.
echo "Hello from Jotline"
for file in *.md; do
  printf '%s\n' "$file"
done
```

```
# Literal Markdown
**Not bold**
```

## Table

| Feature | Status | Count |
|:---|:---:|---:|
| **Markdown** | Ready | 12 |
| Türkçe / 界 | *Supported* | 3 |
| [Link](https://example.com) | `inline code` | 100 |

## Footnotes and HTML

A note with a reference[^note].

[^note]: A **formatted** footnote.
    With a second line.

Inline HTML: <b>bold</b>, <i>italic</i>, <del>deleted</del>, <code>code</code>.

