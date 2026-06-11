#!/usr/bin/python3
"""Parser for the nagent structured tag protocol.

The protocol looks like XML but is not XML: tag bodies are raw text (shell
commands, file contents, prompts) with no entity escaping, and elements do
not nest. A real XML parser would reject valid protocol output, so this is a
small explicit parser for the grammar the protocol actually has:

    document    = (whitespace | element)*
    element     = "<" name attr* ws? "/>"                      self-closing
                | "<" name attr* ws? ">" raw-content "</" name ">"
    attr        = ws name "=" '"' [^"]* '"'
    raw-content = everything up to the FIRST matching close tag, verbatim

Raw content is never scanned for nested elements; the first literal close
tag wins. That is the protocol's contract, not a shortcut.
"""

import string
from dataclasses import dataclass

NAME_START_CHARS = frozenset(string.ascii_letters + "_")
NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_-")


class TagParseError(ValueError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset


@dataclass
class TagNode:
    name: str
    attrs: dict[str, str]
    content: str  # "" for self-closing elements
    self_closing: bool
    start: int  # offset of "<" in the source text
    end: int  # offset just past the element


def parse_element(text: str, pos: int = 0) -> TagNode:
    """Parse one element starting exactly at text[pos]."""
    start = pos
    length = len(text)
    if pos >= length or text[pos] != "<":
        raise TagParseError("expected '<'", pos)
    pos += 1
    if pos >= length or text[pos] not in NAME_START_CHARS:
        raise TagParseError("expected tag name after '<'", pos)
    name_start = pos
    while pos < length and text[pos] in NAME_CHARS:
        pos += 1
    name = text[name_start:pos]

    attrs: dict[str, str] = {}
    while True:
        ws_start = pos
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length:
            raise TagParseError(f"unterminated <{name}> tag", start)
        char = text[pos]
        if char == ">":
            pos += 1
            self_closing = False
            break
        if char == "/":
            if text.startswith("/>", pos):
                pos += 2
                self_closing = True
                break
            raise TagParseError(f"malformed <{name}> tag: expected '/>'", pos)
        if pos == ws_start:
            raise TagParseError(f"malformed <{name}> tag at {char!r}", pos)
        if char not in NAME_START_CHARS:
            raise TagParseError(f"expected attribute name in <{name}>, got {char!r}", pos)
        attr_start = pos
        while pos < length and text[pos] in NAME_CHARS:
            pos += 1
        attr_name = text[attr_start:pos]
        if not text.startswith('="', pos):
            raise TagParseError(f'attribute {attr_name} in <{name}> must use ="..."', pos)
        pos += 2
        value_end = text.find('"', pos)
        if value_end == -1:
            raise TagParseError(f"unterminated value for attribute {attr_name} in <{name}>", pos)
        if attr_name in attrs:
            raise TagParseError(f"duplicate attribute {attr_name} in <{name}>", attr_start)
        attrs[attr_name] = text[pos:value_end]
        pos = value_end + 1

    if self_closing:
        return TagNode(name=name, attrs=attrs, content="", self_closing=True, start=start, end=pos)

    close_tag = f"</{name}>"
    close_at = text.find(close_tag, pos)
    if close_at == -1:
        raise TagParseError(f"missing {close_tag}", start)
    return TagNode(
        name=name,
        attrs=attrs,
        content=text[pos:close_at],
        self_closing=False,
        start=start,
        end=close_at + len(close_tag),
    )


def parse_tag_document(text: str) -> list[TagNode]:
    """Parse a whole document: elements separated by nothing but whitespace."""
    nodes: list[TagNode] = []
    pos = 0
    length = len(text)
    while pos < length:
        if text[pos].isspace():
            pos += 1
            continue
        node = parse_element(text, pos)
        nodes.append(node)
        pos = node.end
    return nodes


def find_block_span(text: str, name: str) -> tuple[int, int] | None:
    """Span of the first literal <name>...</name> block, tags included.

    The open tag takes no attributes and the content is raw: the first close
    tag after the open tag ends the block.
    """
    open_tag = f"<{name}>"
    close_tag = f"</{name}>"
    start = text.find(open_tag)
    if start == -1:
        return None
    end = text.find(close_tag, start + len(open_tag))
    if end == -1:
        return None
    return start, end + len(close_tag)


def extract_block(text: str, name: str) -> str | None:
    """The first <name>...</name> block including its tags, or None."""
    span = find_block_span(text, name)
    if span is None:
        return None
    return text[span[0] : span[1]]


def replace_first_block(text: str, name: str, replacement: str) -> str:
    """Replace the first <name>...</name> block verbatim (no escape semantics)."""
    span = find_block_span(text, name)
    if span is None:
        return text
    return text[: span[0]] + replacement + text[span[1] :]


def remove_first_block(text: str, name: str) -> str:
    return replace_first_block(text, name, "")


def unwrap_whole_element(text: str, name: str) -> str | None:
    """If the entire text is one <name>...</name> element (plus surrounding
    whitespace), return its content; otherwise None. Used to strip accidental
    whole-output wrappers without touching inline examples."""
    stripped = text.strip()
    if not stripped.startswith(f"<{name}"):
        return None
    try:
        node = parse_element(stripped, 0)
    except TagParseError:
        return None
    if node.name != name or node.self_closing or node.attrs or node.end != len(stripped):
        return None
    return node.content
