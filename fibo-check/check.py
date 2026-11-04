#!/usr/bin/env python3
"""Run two Konclude builds side by side on small cases and on FIBO, and write a Markdown table.

  check.py --build master=PATH --build branch=PATH --fibo closure.ofn [--hermit hermit.json]
           --out summary.md

Each row states the answer expected from a build with the fixes; the run fails if the branch
build does not give it.
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERDICT = re.compile(r"Ontology '.*' is (consistent|inconsistent)\.")
NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


def run(cmd, timeout):
    start = time.monotonic()
    try:
        p = subprocess.run(["/usr/bin/time", "-f", "maxrss=%M", *cmd], capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        out, code = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["pkill", "-9", "-f", cmd[0]], check=False)
        return {"text": "timeout", "verdict": None, "exit": None, "errors": None}
    signal = re.search(r"terminated by signal (\d+)", out)
    if signal:
        code = 128 + int(signal.group(1))
    rss = re.findall(r"maxrss=(\d+)", out)
    verdicts = VERDICT.findall(out)
    errors = sum(1 for line in out.splitlines() if "{error}" in line)
    r = {"verdict": verdicts[-1] if verdicts else None, "exit": code, "errors": errors,
         "seconds": round(time.monotonic() - start, 1), "mb": round(int(rss[-1]) / 1024) if rss else None}
    if code is not None and code >= 128:
        r["text"] = f"crash (exit {code})"
    else:
        r["text"] = f"{r['verdict'] or 'no answer'}, exit {code}"
    if errors:
        r["text"] += f", {errors} error lines"
    return r


def consistency(binary, path, timeout=300):
    return run([binary, "consistency", "-w", "1", "-i", str(path)], timeout)


def unsatisfiable(binary, path, timeout=1800):
    out = Path(tempfile.mkdtemp()) / "hierarchy.owl.xml"
    r = run([binary, "classification", "-w", "1", "-i", str(path), "-o", str(out)], timeout)
    if out.exists() and r["exit"] == 0:
        found = set()
        for e in ET.parse(out).getroot().iter():
            if e.tag.endswith("EquivalentClasses"):
                iris = [c.get("IRI") for c in e if c.tag.endswith("Class")]
                if NOTHING in iris:
                    found.update(i for i in iris if i != NOTHING)
        r["unsat"] = len(found)
        r["text"] = f"{len(found)} unsatisfiable classes, exit 0"
        if r["errors"]:
            r["text"] += f", {r['errors']} error lines"
    return r


def with_axioms(closure, axioms):
    text = closure.read_text().rstrip()
    assert text.endswith(")")
    path = Path(tempfile.mkdtemp()) / "closure-plus.ofn"
    path.write_text(text[:-1] + axioms.strip() + "\n)\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="append", required=True)
    ap.add_argument("--fibo", type=Path)
    ap.add_argument("--hermit", type=Path)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    builds = dict(b.split("=", 1) for b in args.build)
    hermit = json.loads(args.hermit.read_text()) if args.hermit and args.hermit.exists() else {}

    work = Path(tempfile.mkdtemp()) / "cases"
    shutil.copytree(HERE / "cases", work)
    for template in work.glob("*.in"):
        template.with_suffix("").write_text(template.read_text().replace("@DIR@", str(work)))

    # (fix, what, expected with the fixes, how to run)
    rows = [
        ("A", "dateTimeStamp data max cardinality + any object max cardinality (`1-crash.ofn`)",
         "consistent, exit 0", lambda b: consistency(b, work / "1-crash.ofn")),
        ("A", "the same with two dateTimeStamp values on an individual of C (`1-dtstamp-inconsistent.ofn`)",
         "inconsistent, exit 0", lambda b: consistency(b, work / "1-dtstamp-inconsistent.ofn")),
        ("B", "`Declaration(AnnotationProperty(:note))` in an inconsistent ontology (`5-annotation-property.ofn`)",
         "inconsistent, exit 0", lambda b: consistency(b, work / "5-annotation-property.ofn")),
        ("C", "a functional-syntax file missing two `)` (`4-unparseable.ofn`)",
         "no answer, exit 1", lambda b: consistency(b, work / "4-unparseable.ofn")),
        ("C", "an empty file (`4-empty.ofn`)", "no answer, exit 1", lambda b: consistency(b, work / "4-empty.ofn")),
        ("C", "a file that does not exist", "no answer, exit 1", lambda b: consistency(b, work / "no-such-file.ofn")),
        ("C", "a valid file whose import does not exist (`4-import-missing.ofn`)",
         "no answer, exit 1", lambda b: consistency(b, work / "4-import-missing.ofn")),
        ("-", "control: a file whose import exists, inconsistent with it (`4-import-ok.ofn`)",
         "inconsistent, exit 0", lambda b: consistency(b, work / "4-import-ok.ofn")),
        ("-", "control: consistent (`control-consistent.ofn`)", "consistent, exit 0",
         lambda b: consistency(b, work / "control-consistent.ofn")),
        ("-", "control: inconsistent (`control-inconsistent.ofn`)", "inconsistent, exit 0",
         lambda b: consistency(b, work / "control-inconsistent.ofn")),
    ]
    if args.fibo:
        unsat = hermit.get("terms_unsatisfiable")
        rows += [
            ("A, B", "FIBO closure: consistency", "consistent, exit 0",
             lambda b: consistency(b, args.fibo, 1800)),
            ("A, B", "FIBO closure: classification", f"{unsat if unsat is not None else '?'} unsatisfiable classes, exit 0",
             lambda b: unsatisfiable(b, args.fibo)),
        ]
        for name, what in (("disjoint", "an entity asserted in a class disjoint with its own"),
                           ("superclass", "a new class over PubliclyHeldCompany placed under NotForProfitCorporation"),
                           ("functional", "two distinct values of a functional property")):
            axioms = (HERE / "injections" / f"{name}.ofn").read_text()
            rows.append(("A", f"FIBO closure + {what} (`injections/{name}.ofn`)", "inconsistent, exit 0",
                         lambda b, a=axioms: consistency(b, with_axioms(args.fibo, a), 1800)))

    names = list(builds)
    lines = ["| fix | input | expected with the fixes | " + " | ".join(names) + " |",
             "|---|---|---|" + "---|" * len(names)]
    failures = []
    results = []
    for fix, what, expected, how in rows:
        print(what, flush=True)
        cells = {n: how(builds[n]) for n in names}
        results.append({"fix": fix, "input": what, "expected": expected, **{n: cells[n] for n in names}})
        shown = []
        for n in names:
            c = cells[n]
            t = c["text"]
            if c.get("seconds") is not None and args.fibo and "FIBO" in what:
                t += f" ({c['seconds']} s, {c['mb']} MB)"
            shown.append(t)
        got = cells[names[-1]]["text"]
        if got != expected:
            failures.append(f"{what}: {names[-1]} gave '{got}', expected '{expected}'")
        lines.append(f"| {fix} | {what} | {expected} | " + " | ".join(shown) + " |")

    text = "\n".join(lines) + "\n\n"
    text += ("**The branch gives every expected answer.**\n" if not failures
             else "**Unexpected:**\n" + "\n".join(f"- {f}" for f in failures) + "\n")
    Path(args.out).write_text(text)
    Path(args.out).with_suffix(".json").write_text(json.dumps(results, indent=1))
    print(text)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
