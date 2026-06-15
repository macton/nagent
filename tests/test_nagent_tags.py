#!/usr/bin/python3

import sys
import unittest
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "bin" / "helpers"
sys.path.insert(0, str(HELPERS))
from nagent_tags import (
    TagParseError,
    extract_block,
    find_block_span,
    parse_element,
    parse_tag_document,
    remove_first_block,
    replace_first_block,
    scan_tag_document,
    serialize_nodes,
    dedupe_nodes,
    unwrap_whole_element,
)

KNOWN = frozenset({"keep"})
UNWRAP = frozenset({"frame"})


class ParseElementTests(unittest.TestCase):
    def test_content_element(self):
        node = parse_element("<nagent-shell>echo hi</nagent-shell>")
        self.assertEqual(node.name, "nagent-shell")
        self.assertEqual(node.content, "echo hi")
        self.assertFalse(node.self_closing)
        self.assertEqual(node.attrs, {})
        self.assertEqual((node.start, node.end), (0, 36))

    def test_self_closing_with_attribute(self):
        node = parse_element('<nagent-read path="/tmp/foo" />')
        self.assertTrue(node.self_closing)
        self.assertEqual(node.attrs, {"path": "/tmp/foo"})
        self.assertEqual(node.content, "")

    def test_self_closing_without_space_before_slash(self):
        node = parse_element('<nagent-read path="/tmp/foo"/>')
        self.assertTrue(node.self_closing)
        self.assertEqual(node.attrs, {"path": "/tmp/foo"})

    def test_multiple_attributes(self):
        node = parse_element('<conv a="1" b="2">x</conv>')
        self.assertEqual(node.attrs, {"a": "1", "b": "2"})

    def test_raw_content_keeps_unescaped_specials(self):
        body = 'if [ "$a" < "$b" ] && grep -q "<tag>" f.xml; then echo "&"; fi'
        node = parse_element(f"<nagent-shell>{body}</nagent-shell>")
        self.assertEqual(node.content, body)

    def test_first_close_tag_wins(self):
        text = "<t>alpha</t>beta</t>"
        node = parse_element(text)
        self.assertEqual(node.content, "alpha")
        self.assertEqual(node.end, len("<t>alpha</t>"))

    def test_content_spans_newlines(self):
        node = parse_element("<nagent-write path=\"/tmp/f\">line1\nline2\n</nagent-write>")
        self.assertEqual(node.content, "line1\nline2\n")

    def test_errors(self):
        cases = [
            ("plain text", "expected '<'"),
            ("<1tag>x</1tag>", "expected tag name"),
            ("<t>unclosed", "missing </t>"),
            ("<t attr>x</t>", 'must use ="..."'),
            ('<t a="unterminated>x</t>', "unterminated value"),
            ('<t a="1" a="2">x</t>', "duplicate attribute"),
            ('<t a="1"', "unterminated <t> tag"),
            ("<t/ >x</t>", "expected '/>'"),
        ]
        for text, message in cases:
            with self.assertRaises(TagParseError, msg=text) as ctx:
                parse_element(text)
            self.assertIn(message, str(ctx.exception), text)

    def test_error_carries_offset(self):
        with self.assertRaises(TagParseError) as ctx:
            parse_element("junk", 0)
        self.assertEqual(ctx.exception.offset, 0)


class ParseDocumentTests(unittest.TestCase):
    def test_elements_separated_by_whitespace(self):
        nodes = parse_tag_document('\n<a>1</a>\n\t<b x="y" />  <c>2</c>\n')
        self.assertEqual([n.name for n in nodes], ["a", "b", "c"])
        self.assertEqual(nodes[1].attrs, {"x": "y"})

    def test_empty_document(self):
        self.assertEqual(parse_tag_document("   \n\t "), [])

    def test_text_between_elements_is_an_error(self):
        with self.assertRaises(TagParseError) as ctx:
            parse_tag_document("<a>1</a> oops <b>2</b>")
        self.assertEqual(ctx.exception.offset, 9)


class ScanDocumentTests(unittest.TestCase):
    def test_keeps_known_ignores_unknown_and_prose(self):
        nodes, ignored = scan_tag_document(
            "prose <other>x</other> <keep>do</keep> trailing", KNOWN, UNWRAP
        )
        self.assertEqual([n.name for n in nodes], ["keep"])
        self.assertEqual(nodes[0].content, "do")
        reasons = [s.reason for s in ignored]
        self.assertIn("non-tag text", reasons)
        self.assertIn("unknown tag <other>", reasons)

    def test_malformed_unknown_tag_is_skipped_to_next(self):
        # "<bad Oops, ..." parses as a bad attribute; skip it, keep the next tag.
        nodes, ignored = scan_tag_document("<bad Oops, words.\n<keep>go</keep>", KNOWN, UNWRAP)
        self.assertEqual([n.name for n in nodes], ["keep"])
        self.assertEqual(ignored[0].reason, "malformed <bad>")

    def test_malformed_known_tag_raises(self):
        with self.assertRaises(TagParseError):
            scan_tag_document("<keep>unclosed", KNOWN, UNWRAP)

    def test_eof_capture_recovers_unclosed_named_tag(self):
        nodes, ignored = scan_tag_document(
            "<keep>body running to the end", KNOWN, UNWRAP, frozenset({"keep"})
        )
        self.assertEqual([n.name for n in nodes], ["keep"])
        self.assertEqual(nodes[0].content, "body running to the end")
        self.assertEqual(ignored, [])
        # A malformed *open* tag still raises even with capture enabled.
        with self.assertRaises(TagParseError):
            scan_tag_document('<keep bad=x>body', KNOWN, UNWRAP, frozenset({"keep"}))

    def test_eof_capture_only_applies_to_named_tags(self):
        # "keep" is not in the eof-capture set here, so an unclosed one raises.
        with self.assertRaises(TagParseError):
            scan_tag_document("<keep>unclosed", KNOWN, UNWRAP, frozenset({"other"}))

    def test_unwraps_wrapper_and_recurses(self):
        nodes, ignored = scan_tag_document(
            "<frame>\n<keep>inner</keep>\n</frame>", KNOWN, UNWRAP
        )
        self.assertEqual([n.name for n in nodes], ["keep"])
        self.assertEqual(ignored, [])

    def test_stray_close_tag_is_text(self):
        nodes, ignored = scan_tag_document("</keep> <keep>ok</keep>", KNOWN, UNWRAP)
        self.assertEqual([n.name for n in nodes], ["keep"])
        self.assertEqual(ignored[0].reason, "non-tag text")


class SerializeNodesTests(unittest.TestCase):
    def test_drops_junk_keeps_valid_tags(self):
        nodes, _ = scan_tag_document(
            'prose <other>x</other> <keep>do</keep> <self a="1" />', KNOWN, UNWRAP
        )
        # <self .../> is unknown here, so only <keep> survives.
        self.assertEqual(serialize_nodes(nodes), "<keep>do</keep>")

    def test_eof_captured_tag_serializes_closed(self):
        nodes, _ = scan_tag_document("<keep>unclosed body", KNOWN, UNWRAP, frozenset({"keep"}))
        self.assertEqual(serialize_nodes(nodes), "<keep>unclosed body</keep>")

    def test_self_closing_and_attrs_roundtrip(self):
        node = parse_element('<thing path="/tmp/x" />')
        self.assertEqual(serialize_nodes([node]), '<thing path="/tmp/x" />')


class DedupeNodesTests(unittest.TestCase):
    def test_collapses_exact_duplicates_keeping_first_order(self):
        nodes, _ = scan_tag_document(
            "<a>x</a><b>y</b><a>x</a><b>y</b><a>x</a>", frozenset({"a", "b"}), UNWRAP
        )
        deduped = dedupe_nodes(nodes)
        self.assertEqual([(n.name, n.content) for n in deduped], [("a", "x"), ("b", "y")])

    def test_distinct_content_or_attrs_not_deduped(self):
        nodes, _ = scan_tag_document(
            '<a>x</a><a>z</a><c p="1" /><c p="2" />', frozenset({"a", "c"}), UNWRAP
        )
        self.assertEqual(len(dedupe_nodes(nodes)), 4)


class BlockHelperTests(unittest.TestCase):
    def test_find_extract_replace_remove(self):
        text = "header\n<ctx>old body</ctx>\ntail"
        self.assertEqual(find_block_span(text, "ctx"), (7, 26))
        self.assertEqual(extract_block(text, "ctx"), "<ctx>old body</ctx>")
        self.assertEqual(
            replace_first_block(text, "ctx", "<ctx>new</ctx>"),
            "header\n<ctx>new</ctx>\ntail",
        )
        self.assertEqual(remove_first_block(text, "ctx"), "header\n\ntail")

    def test_replacement_is_verbatim_no_escape_semantics(self):
        text = "<ctx>old</ctx>"
        replaced = replace_first_block(text, "ctx", "<ctx>uses \\s and \\g<0></ctx>")
        self.assertEqual(replaced, "<ctx>uses \\s and \\g<0></ctx>")

    def test_first_block_only_and_missing_block(self):
        text = "<ctx>a</ctx><ctx>b</ctx>"
        self.assertEqual(replace_first_block(text, "ctx", "X"), "X<ctx>b</ctx>")
        self.assertEqual(replace_first_block("no block", "ctx", "X"), "no block")
        self.assertIsNone(find_block_span("<ctx>unterminated", "ctx"))


class UnwrapTests(unittest.TestCase):
    def test_unwraps_whole_output_wrapper(self):
        self.assertEqual(
            unwrap_whole_element("  <nagent-response>Hi</nagent-response>\n", "nagent-response"),
            "Hi",
        )

    def test_refuses_partial_wrapper(self):
        text = "<nagent-response>a</nagent-response> trailing"
        self.assertIsNone(unwrap_whole_element(text, "nagent-response"))

    def test_refuses_ambiguous_nested_close(self):
        # The "wrapper" content contains its own close tag: not a whole-output
        # wrapper, so it must be left alone.
        text = "<nagent-response>a</nagent-response> mid <nagent-response>b</nagent-response>"
        self.assertIsNone(unwrap_whole_element(text, "nagent-response"))

    def test_refuses_wrong_name_attrs_and_self_closing(self):
        self.assertIsNone(unwrap_whole_element("<other>x</other>", "nagent-response"))
        self.assertIsNone(
            unwrap_whole_element('<nagent-response a="1">x</nagent-response>', "nagent-response")
        )
        self.assertIsNone(unwrap_whole_element("<nagent-response />", "nagent-response"))
        self.assertIsNone(unwrap_whole_element("not a tag", "nagent-response"))


if __name__ == "__main__":
    unittest.main()
