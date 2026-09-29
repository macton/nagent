#!/usr/bin/env python3
"""Does nagent-decide's reported `confidence` separate right answers from wrong?

Issue 0003 question 1. This one spends nothing: it scores the run outputs already
committed under examples/monitor-github/runs/ against expected.json, reusing that
example's own matcher so the comparison is the same one the example makes.

    python3 tests/live/decide_confidence_calibration.py

Result 2026-09-28, over both committed model runs — 68 answers carrying a
confidence value:

    low (<0.90)         1/1   correct
    mid (0.90-0.96)    22/23  correct  (96%)
    high (>=0.97)      44/44  correct  (100%)

The buckets are ordered the right way, and that is all that can be said: there is
exactly ONE wrong answer in the whole corpus, so the ordering rests on n=1. This
does not calibrate the field and must not be quoted as if it did. To settle it,
run the example requests enough times to accumulate tens of errors and re-run this;
until then `confidence` stays documented as an uncalibrated self-report.
"""
import collections
import glob
import importlib.machinery
import importlib.util
import json
from pathlib import Path
HERE = Path("/home/macton/nagent/examples/monitor-github")
loader = importlib.machinery.SourceFileLoader("cmp", str(HERE/"compare.py"))
spec = importlib.util.spec_from_loader("cmp", loader)
cmp = importlib.util.module_from_spec(spec); loader.exec_module(cmp)

exp = json.loads((HERE/"expected.json").read_text())
rows = []
for f in sorted(glob.glob(str(HERE/"runs/*/*.json"))):
    name = Path(f).name
    if not (name.endswith(".decide.json") or name.endswith(".classify.json")): continue
    base = name.split(".")[0] + ".json"
    want = exp.get(base)
    if not isinstance(want, dict): continue
    d = json.loads(Path(f).read_text())
    conf = {}
    for dec in d.get("decisions", []):
        for qid, ans in (dec.get("answers") or {}).items():
            if isinstance(ans, dict) and ans.get("confidence") is not None:
                conf[(dec["item"], qid)] = float(ans["confidence"])
    flat = cmp.flatten(d.get("decisions", []))
    for item_id, wanted in want.items():
        if item_id.startswith("_"): continue
        for key, w in wanted.items():
            qid = key[:-len("_includes")] if key.endswith("_includes") else key
            got = flat.get(item_id, {}).get(qid)
            if key.endswith("_includes"):
                ok = isinstance(got, list) and all(e in got for e in w)
                ok_loose = isinstance(cmp.loosen(got), list) and all(e in cmp.loosen(got) for e in cmp.loosen(w))
            else:
                ok = cmp.matches(got, w)
                ok_loose = cmp.matches(cmp.loosen(got), cmp.loosen(w))
            c = conf.get((item_id, qid))
            if c is None: continue
            rows.append((Path(f).parent.name, c, ok, ok_loose))

def report(label, idx):
    b = collections.Counter(); h = collections.Counter()
    for _run, c, ok, ok_loose in rows:
        key = "high (>=0.97)" if c >= 0.97 else ("mid (0.90-0.96)" if c >= 0.90 else "low (<0.90)")
        b[key] += 1; h[key] += int((ok, ok_loose)[idx])
    print(f"\n{label}")
    for key in ("low (<0.90)", "mid (0.90-0.96)", "high (>=0.97)"):
        if b[key]: print(f"  {key:<17} {h[key]:>3}/{b[key]:<3} correct  ({h[key]/b[key]:.0%})")
print(f"answers carrying a confidence value: {len(rows)}")
report("scored strictly (decision AND usable form):", 0)
report("scored loosely (decision right, form allowed to be verbose):", 1)
