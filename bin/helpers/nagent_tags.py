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


def parse_element(text: str, pos: int = 0, *, capture_to_eof_if_unclosed: bool = False) -> TagNode:
    """Parse one element starting exactly at text[pos].

    With capture_to_eof_if_unclosed, a well-formed open tag whose close tag is
    missing captures the rest of the text as its body (end = len(text)) instead
    of raising. Used only for a trailing <nagent-response> an LLM left unclosed;
    a malformed *open* tag still raises.
    """
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
        if capture_to_eof_if_unclosed:
            return TagNode(
                name=name, attrs=attrs, content=text[pos:], self_closing=False, start=start, end=len(text)
            )
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


@dataclass
class IgnoredSpan:
    reason: str  # short label, e.g. "unknown tag <thought>"
    text: str  # the raw skipped text, for a snippet in the correction note
    start: int  # offset of the skipped text in its (sub-)document


def _read_tag_name(text: str, pos: int) -> str | None:
    """If text[pos:] opens a tag ('<' + a name), return the name; else None.

    A stray close tag ('</...') or a bare '<' followed by non-name characters
    is not a tag opening and returns None, so the caller treats it as text.
    """
    length = len(text)
    if pos >= length or text[pos] != "<":
        return None
    i = pos + 1
    if i >= length or text[i] not in NAME_START_CHARS:
        return None
    name_start = i
    while i < length and text[i] in NAME_CHARS:
        i += 1
    return text[name_start:i]


def scan_tag_document(
    text: str,
    known_names: frozenset[str],
    unwrap_names: frozenset[str],
    eof_capture_names: frozenset[str] = frozenset(),
) -> tuple[list[TagNode], list[IgnoredSpan]]:
    """Lenient counterpart to parse_tag_document.

    Collects well-formed elements whose name is in ``known_names``, recurses
    into ``unwrap_names`` wrappers (echoed log frames), and records everything
    else — prose, reasoning leaks like <thought>, unknown or malformed tags —
    as IgnoredSpans instead of failing. The strict ``parse_tag_document`` still
    exists for callers that want all-or-nothing.

    Raises TagParseError only when a *known* tag is present but malformed: that
    is a clear protocol mistake the caller should surface for correction, not
    silently drop. Unknown/malformed-unknown content is skipped to the next
    '<' (or end of document).
    """
    nodes: list[TagNode] = []
    ignored: list[IgnoredSpan] = []
    pos = 0
    length = len(text)
    while pos < length:
        if text[pos].isspace():
            pos += 1
            continue

        name = _read_tag_name(text, pos)
        if name is None:
            # Non-tag text (prose, a stray close tag). Skip to the next '<'.
            nxt = text.find("<", pos + 1)
            end = length if nxt == -1 else nxt
            ignored.append(IgnoredSpan("non-tag text", text[pos:end], pos))
            pos = end
            continue

        if name in known_names:
            # A known protocol tag: parse strictly. A malformed one propagates
            # as a hard error so the loop asks the model to fix it — except a
            # tag in eof_capture_names left unclosed, which captures to EOF.
            node = parse_element(text, pos, capture_to_eof_if_unclosed=(name in eof_capture_names))
            nodes.append(node)
            pos = node.end
            continue

        # Unknown tag name. Try to parse it as a well-formed element so we can
        # skip the whole thing (and, for wrappers, recurse into its body).
        try:
            node = parse_element(text, pos)
        except TagParseError:
            nxt = text.find("<", pos + 1)
            end = length if nxt == -1 else nxt
            ignored.append(IgnoredSpan(f"malformed <{name}>", text[pos:end], pos))
            pos = end
            continue

        if name in unwrap_names:
            inner_nodes, inner_ignored = scan_tag_document(
                node.content, known_names, unwrap_names, eof_capture_names
            )
            nodes.extend(inner_nodes)
            ignored.extend(inner_ignored)
        else:
            ignored.append(IgnoredSpan(f"unknown tag <{name}>", text[node.start : node.end], node.start))
        pos = node.end

    return nodes, ignored


def serialize_node(node: TagNode) -> str:
    """Re-serialize one parsed element to canonical, well-formed text."""
    attrs = "".join(f' {name}="{value}"' for name, value in node.attrs.items())
    if node.self_closing:
        return f"<{node.name}{attrs} />"
    return f"<{node.name}{attrs}>{node.content}</{node.name}>"


def serialize_nodes(nodes: list[TagNode]) -> str:
    """Canonical re-serialization of parsed nodes, one per line.

    Used to store a cleaned turn: only the valid tags survive, junk is gone, and
    a tag the model left unclosed (EOF-captured) comes back out well-formed.
    """
    return "\n".join(serialize_node(node) for node in nodes)


def dedupe_nodes(nodes: list[TagNode]) -> list[TagNode]:
    """Drop exact-duplicate tags within one turn, keeping the first occurrence.

    A model that stutters can emit the same action (read, shell, next, ...)
    several times in a turn; running and re-queuing each copy wastes work and,
    once stored, becomes precedent that reinforces the repetition. Two nodes are
    duplicates when their name, self-closing flag, attributes, and body all
    match. Distinct tags are untouched and order is preserved.
    """
    seen: set = set()
    out: list[TagNode] = []
    for node in nodes:
        key = (node.name, node.self_closing, tuple(sorted(node.attrs.items())), node.content)
        if key in seen:
            continue
        seen.add(key)
        out.append(node)
    return out


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
