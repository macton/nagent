#!/usr/bin/python3

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

TARGET_BYTES_DEFAULT = 32 * 1024

Line = tuple[int, str]
ScoreFn = Callable[[int, list[Line], int], int]

SPLIT_TYPES = ("txt", "md", "cpp", "py", "xml", "js", "ts", "json", "yaml", "go", "rs", "java")

EXTENSIONS_BY_TYPE = {
    "txt": (".txt", ".text", ".log", ".csv", ".tsv"),
    "md": (".md", ".markdown", ".mdown", ".mkd", ".mdx"),
    "cpp": (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".h++", ".ipp", ".inl"),
    "py": (".py", ".pyw", ".pyi"),
    "xml": (".xml", ".html", ".htm", ".xhtml", ".svg", ".rss", ".atom"),
    "js": (".js", ".mjs", ".cjs", ".jsx"),
    "ts": (".ts", ".tsx", ".mts", ".cts"),
    "json": (".json", ".jsonc", ".json5"),
    "yaml": (".yaml", ".yml"),
    "go": (".go",),
    "rs": (".rs",),
    "java": (".java",),
}

EXTENSION_MAP = {
    extension: split_type
    for split_type, extensions in EXTENSIONS_BY_TYPE.items()
    for extension in extensions
}

SPLIT_TYPE_ALIASES = {
    **{split_type: split_type for split_type in SPLIT_TYPES},
    **{extension.lstrip("."): split_type for extension, split_type in EXTENSION_MAP.items()},
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "file"


def default_output_dir(source: Path) -> Path:
    return Path("/tmp") / f"{slugify(source.stem)}-{uuid.uuid4()}"


def source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lines(source: Path) -> list[Line]:
    data = source.read_bytes()
    if not data:
        return []

    text = data.decode("utf-8")
    lines: list[Line] = []
    line_no = 1
    start = 0
    for match in re.finditer(r"\n|\r\n|\r", text):
        end = match.end()
        lines.append((line_no, text[start:end]))
        line_no += 1
        start = end
    if start < len(text):
        lines.append((line_no, text[start:]))
    return lines


def write_segment(output_dir: Path, source: Path, index: int, content: str) -> Path:
    segment_name = f"{source.stem}-{index:04d}{source.suffix}"
    segment_path = output_dir / segment_name
    segment_path.write_bytes(content.encode("utf-8"))
    return segment_path


def chunk_lines(
    lines: list[Line],
    target_bytes: int,
    score_break: ScoreFn,
    *,
    natural: bool = False,
) -> list[tuple[int, int, str]]:
    if not lines:
        return []

    chunks: list[tuple[int, int, str]] = []
    start_idx = 0

    while start_idx < len(lines):
        chunk_bytes = 0
        end_idx = start_idx
        best_break = start_idx
        best_score = -1
        split_at: int | None = None

        while end_idx < len(lines):
            _, text = lines[end_idx]
            chunk_bytes += len(text.encode("utf-8"))
            score = score_break(end_idx, lines, start_idx)

            if score >= 0:
                best_break = end_idx + 1
                best_score = score

            if natural and score >= 0 and best_break > start_idx:
                split_at = best_break
                break

            if chunk_bytes >= target_bytes:
                if best_score >= 0 and best_break > start_idx:
                    split_at = best_break
                else:
                    split_at = end_idx + 1
                break

            end_idx += 1
        else:
            split_at = len(lines)

        if split_at is None:
            split_at = len(lines)

        if split_at <= start_idx:
            split_at = min(start_idx + 1, len(lines))

        segment_lines = lines[start_idx:split_at]
        content = "".join(text for _, text in segment_lines)
        start_line = segment_lines[0][0]
        end_line = segment_lines[-1][0]
        chunks.append((start_line, end_line, content))
        start_idx = split_at

    return chunks


def split_to_segments(
    source: Path,
    output_dir: Path,
    target_bytes: int,
    score_break: ScoreFn,
    *,
    natural: bool = False,
) -> list[dict]:
    lines = read_lines(source)
    chunks = chunk_lines(lines, target_bytes, score_break, natural=natural)
    segments: list[dict] = []

    for index, (start_line, end_line, content) in enumerate(chunks, start=1):
        segment_path = write_segment(output_dir, source, index, content)
        segments.append(
            {
                "segment_index": index,
                "start_line_num": start_line,
                "end_line_num": end_line,
                "path": str(segment_path),
            }
        )
    return segments


def build_index(
    source: Path,
    segments: list[dict],
    split_type: str,
    target_bytes: int,
    *,
    natural: bool = False,
    created_at: str | None = None,
) -> dict:
    lines = read_lines(source)
    return {
        "source_path": str(source.resolve()),
        "source_sha256": source_sha256(source),
        "source_size_bytes": source.stat().st_size,
        "source_line_count": len(lines),
        "split_type": split_type,
        "target_bytes": target_bytes,
        "natural": natural,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "segment_count": len(segments),
        "segments": segments,
    }


def write_index_file(index_path: Path, index: dict) -> Path:
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index_path


def normalize_split_type(split_type: str) -> str:
    normalized = split_type.lower().lstrip(".")
    if normalized not in SPLIT_TYPE_ALIASES:
        supported = ", ".join(sorted(SPLIT_TYPE_ALIASES))
        raise ValueError(f"unknown split type: {split_type} (supported: {supported})")
    return SPLIT_TYPE_ALIASES[normalized]


def detect_split_type(path: Path) -> str:
    return EXTENSION_MAP.get(path.suffix.lower(), "txt")


def load_index(index_path: Path) -> dict:
    if not index_path.is_file():
        raise FileNotFoundError(f"index not found: {index_path}")
    return json.loads(index_path.read_text(encoding="utf-8"))


def refresh_split(
    index_path: Path,
    score_break: ScoreFn,
) -> dict:
    index = load_index(index_path)
    source = Path(index["source_path"])
    if not source.is_file():
        raise FileNotFoundError(f"source file not found: {source}")

    output_dir = index_path.parent
    target_bytes = int(index.get("target_bytes", TARGET_BYTES_DEFAULT))
    natural = bool(index.get("natural", False))
    split_type = normalize_split_type(index.get("split_type", detect_split_type(source)))

    segments = split_to_segments(
        source,
        output_dir,
        target_bytes,
        score_break,
        natural=natural,
    )
    refreshed = build_index(
        source,
        segments,
        split_type,
        target_bytes,
        natural=natural,
    )
    write_index_file(index_path, refreshed)
    return refreshed


def emit_segments(segments: list[dict]) -> None:
    print(json.dumps(segments, indent=2))


def helper_main(score_break: ScoreFn) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Split a file into structure-aware segments.")
    parser.add_argument("--file", required=True, type=Path, help="Source file path.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for split files.")
    parser.add_argument(
        "--target-bytes",
        type=int,
        default=TARGET_BYTES_DEFAULT,
        help="Approximate target size per segment in bytes.",
    )
    parser.add_argument(
        "--natural",
        action="store_true",
        help="Split at every natural boundary for this type (still respects --target-bytes max).",
    )
    args = parser.parse_args()

    if not args.file.is_file():
        raise SystemExit(f"Error: file not found: {args.file}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    segments = split_to_segments(
        args.file,
        args.output_dir,
        args.target_bytes,
        score_break,
        natural=args.natural,
    )
    emit_segments(segments)


def blank_line_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    _, text = lines[end_idx]
    if text.strip() == "":
        return 100
    return -1


def md_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "":
        return 100
    if stripped.startswith("#"):
        return 90
    return -1


def py_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    _, text = lines[end_idx]
    if text.strip() == "":
        return 100
    if end_idx + 1 < len(lines):
        next_line = lines[end_idx + 1][1]
        if next_line and next_line[0] not in (" ", "\t"):
            next_stripped = next_line.strip()
            if next_stripped.startswith(("def ", "class ", "async def ")):
                return 95
    return -1


# Depth arrays are a pure function of the full lines list, but score functions
# are called once per line. Compute each depth array once per lines list and
# reuse it; the cached lines list is pinned by the entry, so an `is` check is
# a safe identity test (one entry per depth function, bounded by one file).
_depth_cache: dict[Callable[[list[Line]], list[int]], tuple[list[Line], list[int]]] = {}


def _depths_for(lines: list[Line], compute: Callable[[list[Line]], list[int]]) -> list[int]:
    entry = _depth_cache.get(compute)
    if entry is not None and entry[0] is lines:
        return entry[1]
    depths = compute(lines)
    _depth_cache[compute] = (lines, depths)
    return depths


def brace_depth(lines: list[Line]) -> list[int]:
    depths: list[int] = []
    depth = 0
    for _, text in lines:
        depths.append(depth)
        for char in text:
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(depth - 1, 0)
    return depths


def cpp_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    depths = _depths_for(lines, brace_depth)
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "" and depths[end_idx] == 0:
        return 100
    if stripped == "}" and depths[end_idx] == 0:
        return 95
    if end_idx + 1 < len(lines) and depths[end_idx + 1] == 0:
        next_stripped = lines[end_idx + 1][1].strip()
        if next_stripped.startswith(("#", "class ", "struct ", "namespace ", "template")):
            return 90
    return -1


def js_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    depths = _depths_for(lines, brace_depth)
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "" and depths[end_idx] == 0:
        return 100
    if stripped == "}" and depths[end_idx] == 0:
        return 95
    if end_idx + 1 < len(lines) and depths[end_idx + 1] == 0:
        next_stripped = lines[end_idx + 1][1].strip()
        if next_stripped.startswith(
            ("export ", "function ", "class ", "const ", "let ", "var ", "async function ", "interface ", "type ")
        ):
            return 90
    return -1


def json_depth(lines: list[Line]) -> list[int]:
    depths: list[int] = []
    depth = 0
    for _, text in lines:
        depths.append(depth)
        for char in text:
            if char in "{[":
                depth += 1
            elif char in "}]":
                depth = max(depth - 1, 0)
    return depths


def json_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    depths = _depths_for(lines, json_depth)
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "" and depths[end_idx] == 0:
        return 100
    if stripped in ("}", "},") and depths[end_idx] == 0:
        return 95
    if stripped == "]" and depths[end_idx] == 0:
        return 95
    return -1


def yaml_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "":
        return 100
    if stripped == "---":
        return 95
    if end_idx + 1 < len(lines):
        next_line = lines[end_idx + 1][1]
        if next_line and next_line[0] not in (" ", "\t") and not next_line.lstrip().startswith("#"):
            return 90
    return -1


def go_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "":
        return 100
    if end_idx + 1 < len(lines):
        next_line = lines[end_idx + 1][1]
        if next_line and next_line[0] not in (" ", "\t"):
            next_stripped = next_line.strip()
            if next_stripped.startswith(("func ", "type ", "package ", "import ")):
                return 95
    return -1


def rs_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    depths = _depths_for(lines, brace_depth)
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "" and depths[end_idx] == 0:
        return 100
    if stripped == "}" and depths[end_idx] == 0:
        return 95
    if end_idx + 1 < len(lines) and depths[end_idx + 1] == 0:
        next_stripped = lines[end_idx + 1][1].strip()
        if next_stripped.startswith(("fn ", "pub fn ", "struct ", "enum ", "impl ", "mod ", "use ", "trait ")):
            return 90
    return -1


def java_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    depths = _depths_for(lines, brace_depth)
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "" and depths[end_idx] == 0:
        return 100
    if stripped == "}" and depths[end_idx] == 0:
        return 95
    if end_idx + 1 < len(lines) and depths[end_idx + 1] == 0:
        next_stripped = lines[end_idx + 1][1].strip()
        if next_stripped.startswith(
            ("package ", "import ", "public class ", "class ", "interface ", "enum ", "record ", "@")
        ):
            return 90
    return -1


def xml_depth(lines: list[Line]) -> list[int]:
    depths: list[int] = []
    depth = 0
    tag_pattern = re.compile(r"<\s*(/)?\s*([A-Za-z_][\w:.-]*)\b[^<>]*>")
    for _, text in lines:
        depths.append(depth)
        for match in tag_pattern.finditer(text):
            is_close = match.group(1) == "/"
            if is_close:
                depth = max(depth - 1, 0)
            elif not match.group(0).endswith("/>"):
                depth += 1
    return depths


def xml_score(end_idx: int, lines: list[Line], start_idx: int) -> int:
    depths = _depths_for(lines, xml_depth)
    _, text = lines[end_idx]
    stripped = text.strip()
    if stripped == "":
        return 100
    if stripped.startswith("</") and depths[end_idx] == 0:
        return 95
    if end_idx + 1 < len(lines) and depths[end_idx + 1] == 0:
        next_stripped = lines[end_idx + 1][1].strip()
        if next_stripped.startswith("<") and not next_stripped.startswith("</"):
            return 90
    return -1


SCORE_BY_TYPE: dict[str, ScoreFn] = {
    "txt": blank_line_score,
    "md": md_score,
    "cpp": cpp_score,
    "py": py_score,
    "xml": xml_score,
    "js": js_score,
    "ts": js_score,
    "json": json_score,
    "yaml": yaml_score,
    "go": go_score,
    "rs": rs_score,
    "java": java_score,
}


def score_for_type(split_type: str) -> ScoreFn:
    return SCORE_BY_TYPE.get(normalize_split_type(split_type), blank_line_score)
