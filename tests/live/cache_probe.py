#!/usr/bin/env python3
"""Measure what a provider actually reads from its prompt cache.

NOT part of the unittest suite: it spends money and needs a live key. Run it by
hand when a caching claim needs checking — that is the only way to check one.

    OPENROUTER_API_KEY=... python3 tests/live/cache_probe.py [conversation-file]

It sends one real conversation four times through one Claude model with a
different cache_control layout each time, and prints the tokens read back. The
layouts are built by nagent's own conversation_cache_boundaries() and
cache_prefix_blocks(), so what is measured is what nagent sends.

Reading the output: "no cache_control at all" must read 0, or the provider is
caching on its own and nothing below means what it says. Each single-breakpoint
run shows the size of that prefix. A run whose read equals its prompt total read
everything.

Measured 2026-09-28, anthropic/claude-opus-5 via OpenRouter, 12572-token
conversation:

    no cache_control at all                        0
    one breakpoint: Instance                    7625
    one breakpoint: context_end                 7917
    both, as nagent ships them                  7917
    both + the file end marked                 12570   <- the mark does work
    both + the file end, sent again            12570
    grown message, its own end marked           7917   <- and buys nothing here

The last two lines are the whole argument for what nagent ships. Marking the file
end makes the entry readable, but only a byte-identical repeat reads it, and every
nagent turn appends — so the mark would be a cache write per turn against a read
that does not happen. Measured through OpenRouter because it is the only Claude
endpoint with credit on this machine; re-run against the Anthropic API when there
is one, and if the grown-message line rises, mark the file end in
conversation_cache_boundaries by appending len(text).
"""
import importlib.machinery, importlib.util, os, sys, uuid
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_loader("nagent", importlib.machinery.SourceFileLoader("nagent", str(REPO / "bin" / "nagent")))
mod = importlib.util.module_from_spec(spec); sys.modules["nagent"] = mod; spec.loader.exec_module(mod)
sys.path.insert(0, str(REPO / "bin" / "helpers"))
import nagent_llm
MODEL = os.environ.get("CACHE_PROBE_MODEL", "anthropic/claude-opus-5")
client = nagent_llm._openrouter_client()
DEFAULT = Path.home() / ".nagent" / "conversations"
target = Path(sys.argv[1]) if len(sys.argv) > 1 else max(
    (f for f in DEFAULT.glob("*") if f.is_file() and f.read_text(errors="ignore").startswith("<initial_context>")),
    key=lambda f: f.stat().st_size,
)
conv = target.read_text()
print(f"conversation: {target}  ({len(conv)} chars)\n")
b = mod.conversation_cache_boundaries(conv)

def send(boundaries, label):
    blocks = nagent_llm.cache_prefix_blocks(conv, boundaries)
    nblocks = len(blocks) if isinstance(blocks, list) else 1
    r = client.chat.completions.create(model=MODEL, max_tokens=16,
        messages=[{"role": "user", "content": blocks}],
        extra_body={"usage": {"include": True}})
    u = r.usage
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    print(f"{label:<44} prompt={u.prompt_tokens:>6} cached={cached:>6} blocks={nblocks}")

def send_text(text, boundaries, label):
    global conv
    keep, conv = conv, text
    try:
        send(boundaries, label)
    finally:
        conv = keep


send([], "no cache_control at all")
send([b[0]], "one breakpoint: Instance")
send([b[1]], "one breakpoint: context_end")
send(b, "both, as nagent ships them")
send(b + [len(conv)], "both + the file end marked")
send(b + [len(conv)], "both + the file end, sent again unchanged")

# The decisive one: a message that extends a message already sent, which is what
# every nagent turn is. If marking the file end paid off, this would read more
# than the "both" run above. Measured 2026-09-28: it does not.
# The appended text carries a nonce. Without one, a second run of this probe
# re-sends bytes the first run already cached and the line reads as a full hit —
# a false positive that says the file-end mark works when it does not.
nonce = uuid.uuid4().hex
grown = (
    conv
    + f'\n<nagent-shell-result status="ok" run="{nonce}">\n'
    + f"appended output line {nonce}\n" * 300
    + "</nagent-shell-result>\n"
)
send_text(grown, b + [len(grown)], "grown message, its own end marked")
