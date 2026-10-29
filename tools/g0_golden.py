#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""G0: golden check for partitor builds and CLI behaviour (version 2).

Purpose: prove that a change that must not alter behaviour (scrub, move,
module split, a deployment change) did not alter it. It runs the engine on fixed
inputs and stores what it produces; `check` runs again and reports every
difference.

Usage (use the engine's venv python):
  g0_golden.py record    --engine ENGINE --tests tests/test_partitor.py --golden golden.json
  g0_golden.py check     --engine ENGINE --tests tests/test_partitor.py --golden golden.json
  g0_golden.py selfcheck --engine ENGINE --tests tests/test_partitor.py --golden golden.json
  options: --only a,b      run cases whose name starts with one of these
           --workers N     cases run in parallel (default 2)
           --corpus DIR    optional local corpus (see below)
           --fixtures DIR  stored input PDFs (default <golden>-fixtures)
ENGINE is a file (run as `python ENGINE ...`) or a command string such as
"python -m partitor" for the later modular layout.

What is recorded, per case
  pdf     every output PDF: page count; per page size and SHA-256 of the grey
          pixels at 100 dpi. PDF file bytes are never hashed (they carry dates).
  text    normalised stdout (and layout.yaml / score.yaml): ANSI codes, dates,
          times, durations, temp paths, version and item ids are replaced.
  names   sorted file names of an output folder (the library layout contract).

Case groups
  build:*   `detect` + `build` on synthetic PDFs: sizes, paper, ink, scale,
            page count, dpi, duplex, large print, bar numbers, title page,
            re-flow, a long score (title page, page turns), a raster scan,
            and 2 workers (must equal 1 worker: invariant).
  pieces:*  the `pieces` command on a two-piece PDF.
  help:*    `--help` of the program and of every subcommand (CLI surface).
  lib:*     a scripted library session (new, show, set, rebuild, groups,
            partial rebuild, paper, parts, bars, proof, expand, contract,
            analyse, re-flow, repage, list, rename). Steps and prompts are in
            LIB_STEPS.
  corpus:*  optional. DIR/corpus.yaml lists PDFs; a missing PDF or manifest is
            skipped, never a failure:
              items:
                - {name: komm, pdf: komm.pdf, pages: "1-2", build: ["--paper","a4"]}

Fixtures: built once at `record` (generator output embeds a timestamp) and
stored; `check` reuses them. Golden values depend on pymupdf, OpenCV, numpy,
tesseract and fonts: record and check in the same environment.

Exit code: 0 same, 1 differences or invariant failure, 2 usage or run error.
"""
import argparse
import concurrent.futures as cf
import difflib
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
import yaml

DPI = 100
STEP_TIMEOUT = 1800

# name -> (make_score_pdf kwargs, extra detect args, build options)
SYNTH = {
    "base":         ({}, [], []),
    "four-staves":  ({"systems": 3, "staves": 4, "labels": ("S", "A", "T", "B")}, [], []),
    "curved":       ({"curve": 2.0}, [], []),
    "no-lyrics":    ({"lyrics": False}, [], []),
    "rests":        ({"systems": 2, "quiet": {(1, 1)}}, [], []),
    "no-labels":    ({"labels": ("", "", ""), "title": ""}, [], []),
    "one-system":   ({"systems": 1, "staves": 2, "labels": ("Alto", "Bass"), "title": ""}, [], []),
    "a4":           ({}, [], ["--paper", "a4"]),
    "darker":       ({}, [], ["--ink", "darker"]),
    "scale":        ({}, [], ["--scale", "1.2"]),
    "pages2":       ({"systems": 2}, [], ["--page-count", "2"]),
    "dpi300":       ({}, ["--dpi", "300"], []),
    "duplex":       ({}, [], ["--duplex", "on", "--gutter", "20"]),
    "large-off":    ({}, [], ["--large", "off"]),
    "bars-none":    ({}, [], ["--bar-numbers", "none"]),
    "reflow":       ({}, [], ["--reflow", "on"]),
    "margins":      ({}, [], ["--margin-top", "30", "--margin-bottom", "25", "--margin-side", "10"]),
}
# built from the long fixture (14 pages), name -> (detect args, build options, env)
LONG = {
    "long-default": ([], [], {}),
    "long-pages5":  ([], ["--page-count", "5"], {}),
    "long-duplex":  ([], ["--duplex", "on", "--page-count", "5"], {}),
    "long-notitle": ([], ["--duplex", "on", "--page-count", "5", "--title-page", "off"], {}),
    "long-jobs2":   ([], [], {"PARTITOR_JOBS": "2"}),
}
# a score whose second page has fewer staves: the missing part gets rest lines
LIB_STEPS_REDUCED = [
    ("new",        ["new"], "1\n\nReduced Chorale\nJ. H. Schein\n\n\n\n", True),
    ("groups",     ["groups", "1"], "Low=1,3\n\n", False),
    ("rebuild",    ["rebuild", "1"], "\n\n", True),
    ("rebuild-low", ["rebuild", "1", "Low"], "\n\n", True),
    ("show",       ["show", "1"], "", False),
]
LONG_INVARIANT = ("build:long-jobs2", "build:long-default")     # same output expected

SUBCOMMANDS = ["menu", "new", "list", "show", "rebuild", "repage", "proof", "bars", "parts",
               "groups", "meta", "analyse", "set", "expand", "contract", "reid", "rename",
               "pieces", "detect", "build"]

# (label, args, stdin, snapshot the item folder after this step)
LIB_STEPS = [
    ("new",        ["new"], "1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n", True),
    ("show1",      ["show", "1"], "", False),
    ("set1",       ["set", "1", "A:ambitus=C4-F5", "T:gap=12", "large=off", "title=Other Title"], "", False),
    ("rebuild1",   ["rebuild", "1"], "\n\n", True),
    ("groups",     ["groups", "1"], "Low=2,3\n\n", False),
    ("rebuild2",   ["rebuild", "1"], "\n\n", True),
    ("rebuild-low", ["rebuild", "1", "Low"], "\n\n", True),
    ("paper-a4",   ["set", "1", "paper=a4", "--build"], "\n\n", True),
    ("parts",      ["parts", "1"], "1=Soprano\n\n", False),
    ("rebuild3",   ["rebuild", "1"], "\n\n", True),
    ("bars",       ["bars", "1"], "m 2 3\n\n", False),
    ("proof",      ["proof", "1"], "\n", True),
    ("expand",     ["expand", "1"], "", False),
    ("contract",   ["contract", "1"], "", False),
    ("analyse",    ["analyse", "1", "--yes"], "\n", False),
    ("rebuild4",   ["rebuild", "1"], "\n\n", True),
    ("reflow-on",  ["set", "1", "reflow=on", "--build"], "\n\n", True),
    ("repage",     ["repage", "1"], "\n\n", True),
    ("list",       ["list"], "", False),
    ("rename",     ["rename", "1"], "\n", True),
    ("show2",      ["show", "1"], "", False),
]

# ---------------------------------------------------------------- normalising
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ITEM_ID = re.compile(r"\b(?:19|20)\d\d-\d\d-\d{4}\b")
DATE_TIME = re.compile(r"\b(?:19|20)\d\d-\d\d-\d\d(?:[ T]\d\d:\d\d(?::\d\d)?(?: ?[A-Z]{3,4})?)?\b")
DURATION = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|min)\b")
MEMORY = re.compile(r"\b\d+(?:\.\d+)?\s?(?:MB|MiB|GB|GiB)\b")
VERSION = re.compile(r"(partitor )\d+\.\d+\.\d+\S*")


def norm(text, tmp=None):
    t = ANSI.sub("", text).replace("\r", "")
    if tmp:
        t = t.replace(str(tmp), "<TMP>")
    t = re.sub(r"/tmp/[^\s'\"]*g0-[A-Za-z0-9_]+", "<TMP>", t)
    t = ITEM_ID.sub("<ID>", t)
    t = DATE_TIME.sub("<DATE>", t)
    t = DURATION.sub("<T>", t)
    t = MEMORY.sub("<MEM>", t)
    t = VERSION.sub(r"\1<VERSION>", t)
    return "\n".join(l.rstrip() for l in t.splitlines()).strip() + "\n"


def norm_name(name):
    return ITEM_ID.sub("<ID>", name)


# ------------------------------------------------------------------- hashing
def pdf_hash(path):
    doc = pymupdf.open(path)
    pages = []
    for p in doc:
        pix = p.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY, alpha=False)
        pages.append([round(p.rect.width, 1), round(p.rect.height, 1),
                      hashlib.sha256(pix.samples).hexdigest()])
    return {"pdf": pages}


def artifacts(folder, prefix="", tmp=None, skip=("source",)):
    """pdf hashes, normalised yaml text and the file-name list of a folder."""
    res = {}
    folder = Path(folder)
    names = []
    for f in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = f.relative_to(folder).as_posix()
        names.append(norm_name(rel))
        if any(s in f.name for s in skip) and f.suffix == ".pdf":
            continue
        if f.suffix == ".pdf":
            res[f"{prefix}pdf:{norm_name(rel)}"] = pdf_hash(f)
        elif f.suffix in (".yaml", ".yml"):
            res[f"{prefix}text:{norm_name(rel)}"] = {"text": norm(f.read_text(), tmp)}
    res[f"{prefix}names"] = {"names": sorted(names)}
    return res


# ------------------------------------------------------------------- running
def load_tests(path):
    ld = importlib.machinery.SourceFileLoader("g0_tests", str(path))
    sp = importlib.util.spec_from_loader("g0_tests", ld)
    m = importlib.util.module_from_spec(sp)
    sys.modules["g0_tests"] = m
    sys.path.insert(0, str(Path(path).parent))
    ld.exec_module(m)
    return m


def base_env(extra=None, share=None):
    env = dict(os.environ)
    if os.geteuid() == 0:
        env["PARTITOR_ALLOW_ROOT"] = "1"          # tests only (engine refuses root)
    env.update({"PARTITOR_JOBS": "1", "PARTITOR_COLOR": "0", "PYTHONUNBUFFERED": "1",
                "COLUMNS": "100", "LC_ALL": "C.UTF-8", "TZ": "UTC"})
    # Both names: PARTITOR_SHARE is what engines before 0.4.0 read. A run against
    # an old engine must never reach a real library; without a share, point both
    # at a folder that does not exist.
    lib = str(share) if share else "/nonexistent-g0-library"
    env["PARTITOR_LIBRARY"] = lib
    env["PARTITOR_SHARE"] = lib
    env.update(extra or {})
    return env


def run(engine_cmd, args, cwd, env, stdin=""):
    r = subprocess.run(engine_cmd + args, cwd=cwd, env=env, input=stdin,
                       capture_output=True, text=True, timeout=STEP_TIMEOUT)
    return r.returncode, r.stdout + r.stderr


def case_build(engine_cmd, pdf, detect_args=(), build_opts=(), env_extra=None, pages=None):
    with tempfile.TemporaryDirectory(prefix="g0-") as td:
        td = Path(td)
        shutil.copy(pdf, td / Path(pdf).name)          # relative path: layout.yaml
        name = Path(pdf).name                          # records `source:` verbatim
        env = base_env(env_extra)
        pg = ["--pages", pages] if pages else []
        rc, out = run(engine_cmd, ["detect", name, "--out", "out", *pg, *detect_args], td, env)
        if rc != 0:
            return {"error": f"detect exit {rc}: {norm(out, td)[-300:]}"}
        rc, out = run(engine_cmd, ["build", name, "--out", "out", *pg, *build_opts], td, env)
        if rc != 0:
            return {"error": f"build exit {rc}: {norm(out, td)[-300:]}"}
        res = artifacts(td / "out", tmp=td, skip=())
        res["text:build-stdout"] = {"text": norm(out, td)}
        return {"artifacts": res}


def case_pieces(engine_cmd, pdf):
    with tempfile.TemporaryDirectory(prefix="g0-") as td:
        td = Path(td)
        shutil.copy(pdf, td / Path(pdf).name)
        rc, out = run(engine_cmd, ["pieces", Path(pdf).name], td, base_env())
        return {"artifacts": {"text:pieces": {"text": f"exit {rc}\n" + norm(out, td)}}}


def case_help(engine_cmd, sub):
    with tempfile.TemporaryDirectory(prefix="g0-") as td:
        rc, out = run(engine_cmd, ([sub] if sub else []) + ["--help"], td, base_env())
        out = re.sub(r"usage: \S+", "usage: PROG", out)
        out = re.sub(r"\n\S*partitor\S* ", "\nPROG ", out)
        return {"artifacts": {"text:help": {"text": f"exit {rc}\n" + norm(out, td)}}}


def case_lib(engine_cmd, fixture, steps=None):
    with tempfile.TemporaryDirectory(prefix="g0-") as td:
        td = Path(td)
        share = td / "share"
        for d in ("inbox", "library"):
            (share / d).mkdir(parents=True)
        shutil.copy(fixture, share / "inbox" / "chorale.pdf")
        env = base_env(share=share)
        res = {}
        for label, args, stdin, snap in (steps or LIB_STEPS):
            rc, out = run(engine_cmd, args, td, env, stdin)
            res[f"{label}:text:stdout"] = {"text": f"exit {rc}\n" + norm(out, td)}
            items = sorted((share / "library").glob("*"))
            if snap and items:
                res.update(artifacts(items[-1], prefix=f"{label}:", tmp=td))
            elif items:
                res[f"{label}:names"] = {"names": sorted(
                    norm_name(p.relative_to(items[-1]).as_posix())
                    for p in items[-1].rglob("*") if p.is_file())}
        res["share-names"] = {"names": sorted(norm_name(p.relative_to(share).as_posix())
                                              for p in share.rglob("*") if p.is_file()
                                              and "/library/" in "/" + p.relative_to(share).as_posix())}
        return {"artifacts": res}


# ------------------------------------------------------------------ fixtures
def make_fixtures(tests, fx):
    fx.mkdir(parents=True, exist_ok=True)
    made = []

    def need(name):
        p = fx / name
        if p.exists():
            return None
        made.append(name)
        return p
    for name, (kw, _d, _b) in SYNTH.items():
        p = need(f"{name}.pdf")
        if p:
            tests.make_score_pdf(str(p), **kw)
    p = need("long.pdf")
    if p:
        tmp = fx / "_page.pdf"
        out = pymupdf.open()
        for k in range(14):
            tests.make_score_pdf(str(tmp), systems=2, title="Long Chorale" if k == 0 else "")
            out.insert_pdf(pymupdf.open(tmp))
        out.save(p)
        tmp.unlink()
    p = need("scan.pdf")
    if p:
        src = fx / "_scan_src.pdf"
        tests.make_score_pdf(str(src))
        tests.rasterize(str(src), str(p), dpi=200, angle=0.8, curve_px=9)
        src.unlink()
    p = need("reduced.pdf")
    if p:
        out = pymupdf.open()
        tmp = fx / "_page.pdf"
        tests.make_score_pdf(str(tmp), systems=1, title="Reduced Chorale")
        out.insert_pdf(pymupdf.open(tmp))
        tests.make_score_pdf(str(tmp), systems=2, staves=2, labels=("Alto", "Bass"), title="")
        out.insert_pdf(pymupdf.open(tmp))
        out.save(p)
        tmp.unlink()
    p = need("multi.pdf")
    if p:
        out = pymupdf.open()
        tmp = fx / "_page.pdf"
        for t in ("First Chorale", "Second Chorale"):
            tests.make_score_pdf(str(tmp), title=t)
            out.insert_pdf(pymupdf.open(tmp))
        out.save(p)
        tmp.unlink()
    return made


# ------------------------------------------------------------------- driver
def build_cases(args, fx, engine_cmd):
    """-> list of (name, callable)."""
    cases = []
    for name, (_kw, dargs, bopts) in SYNTH.items():
        cases.append((f"build:{name}", lambda n=name, d=dargs, b=bopts:
                      case_build(engine_cmd, fx / f"{n}.pdf", d, b)))
    for name, (dargs, bopts, env) in LONG.items():
        cases.append((f"build:{name}", lambda d=dargs, b=bopts, e=env:
                      case_build(engine_cmd, fx / "long.pdf", d, b, e)))
    cases.append(("build:scan", lambda: case_build(engine_cmd, fx / "scan.pdf")))
    cases.append(("build:scan-a4", lambda: case_build(engine_cmd, fx / "scan.pdf", (), ["--paper", "a4"])))
    cases.append(("build:pages-range", lambda: case_build(engine_cmd, fx / "long.pdf", (), (), None, "2-5")))
    cases.append(("pieces:multi", lambda: case_pieces(engine_cmd, fx / "multi.pdf")))
    for sub in [""] + SUBCOMMANDS:
        cases.append((f"help:{sub or 'main'}", lambda s=sub: case_help(engine_cmd, s)))
    cases.append(("build:reduced", lambda: case_build(engine_cmd, fx / "reduced.pdf")))
    cases.append(("lib:session", lambda: case_lib(engine_cmd, fx / "base.pdf")))
    cases.append(("lib:reduced", lambda: case_lib(engine_cmd, fx / "reduced.pdf", LIB_STEPS_REDUCED)))
    if args.corpus:
        man = Path(args.corpus) / "corpus.yaml"
        if man.is_file():
            for it in (yaml.safe_load(man.read_text()) or {}).get("items", []):
                pdf = Path(args.corpus) / it["pdf"]
                if pdf.is_file():
                    cases.append((f"corpus:{it['name']}", lambda p=pdf, i=it:
                                  case_build(engine_cmd, p, (), i.get("build", []), None, i.get("pages"))))
                else:
                    cases.append((f"corpus:{it['name']}", lambda: {"skipped": "pdf not present"}))
        else:
            print("g0: no corpus.yaml in corpus dir: corpus cases skipped", file=sys.stderr)
    if args.only:
        keys = args.only.split(",")
        cases = [c for c in cases if any(c[0].startswith(k) for k in keys)]
    return cases


def run_all(args):
    tests = load_tests(args.tests)
    engine_cmd = shlex.split(args.engine)
    if len(engine_cmd) == 1:                      # a file: run with this python
        engine_cmd = [sys.executable, str(Path(engine_cmd[0]).resolve())]
    fx = Path(args.fixtures or (Path(args.golden).with_suffix("").as_posix() + "-fixtures"))
    if args.mode == "record" or not fx.exists():
        if args.mode != "record":
            raise SystemExit(f"g0: fixtures missing: {fx} (run record first)")
        make_fixtures(tests, fx)
    cases = build_cases(args, fx, engine_cmd)
    results = {}
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fn): name for name, fn in cases}
        for f in cf.as_completed(futs):
            name = futs[f]
            try:
                results[name] = f.result()
            except Exception as e:                # noqa: BLE001
                results[name] = {"error": f"runner: {e}"}
    out = {"version": 2, "dpi": DPI, "cases": dict(sorted(results.items()))}
    out["invariants"] = check_invariants(out)
    return out


def check_invariants(res):
    bad = []
    a, b = (res["cases"].get(k) for k in LONG_INVARIANT)
    if a and b and "artifacts" in a and "artifacts" in b:
        for k in sorted(set(a["artifacts"]) | set(b["artifacts"])):
            if k.startswith("text:build-stdout"):
                continue
            if a["artifacts"].get(k) != b["artifacts"].get(k):
                bad.append(f"{LONG_INVARIANT[0]} differs from {LONG_INVARIANT[1]}: {k}")
    return bad


# ---------------------------------------------------------------- comparing
def describe(k, x, y):
    if x is None or y is None:
        return f"{k}: {'new' if x is None else 'missing'}"
    if "pdf" in x and "pdf" in y:
        if len(x["pdf"]) != len(y["pdf"]):
            return f"{k}: page count {len(x['pdf'])} -> {len(y['pdf'])}"
        bad = [i + 1 for i, (p, q) in enumerate(zip(x["pdf"], y["pdf"])) if p != q]
        return f"{k}: pages differ {bad}"
    if "names" in x and "names" in y:
        a, b = set(x["names"]), set(y["names"])
        return f"{k}: names: +{sorted(b - a)[:6]} -{sorted(a - b)[:6]}"
    if "text" in x and "text" in y:
        d = list(difflib.unified_diff(x["text"].splitlines(), y["text"].splitlines(),
                                      "golden", "run", lineterm="", n=0))
        return f"{k}: text differs\n" + "\n".join("      " + l for l in d[2:12])
    return f"{k}: changed"


def compare(old, new):
    diffs = []
    for k in sorted(set(old["cases"]) | set(new["cases"])):
        a, b = old["cases"].get(k), new["cases"].get(k)
        if a is None or b is None:
            diffs.append(f"{k}: case {'not in golden' if a is None else 'not run'}")
            continue
        if "skipped" in a or "skipped" in b:
            continue
        if "error" in a or "error" in b:
            if a != b:
                diffs.append(f"{k}: error state differs: {a.get('error')} / {b.get('error')}")
            continue
        for f in sorted(set(a["artifacts"]) | set(b["artifacts"])):
            x, y = a["artifacts"].get(f), b["artifacts"].get(f)
            if x != y:
                diffs.append(f"{k}: " + describe(f, x, y))
    return diffs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["record", "check", "selfcheck"])
    ap.add_argument("--engine", required=True)
    ap.add_argument("--tests", default="tests/test_partitor.py")
    ap.add_argument("--corpus")
    ap.add_argument("--golden", default="golden.json")
    ap.add_argument("--fixtures")
    ap.add_argument("--only")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    try:
        if a.mode == "selfcheck":
            a.mode = "record"
            r1 = run_all(a)
            a.mode = "check"
            r2 = run_all(a)
            d = compare(r1, r2) + r1["invariants"]
            print("selfcheck:", "deterministic" if not d else "NOT deterministic")
            for x in d:
                print("  ", x)
            return 1 if d else 0
        res = run_all(a)
        errs = [k for k, c in res["cases"].items() if "error" in c]
        if a.mode == "record":
            Path(a.golden).write_text(json.dumps(res, indent=1, sort_keys=True))
            n = sum(1 for c in res["cases"].values() if "artifacts" in c)
            print(f"recorded {n} cases to {a.golden}; errors: {errs or 'none'}; "
                  f"invariants: {res['invariants'] or 'ok'}")
            return 1 if res["invariants"] else 0
        old = json.loads(Path(a.golden).read_text())
        if a.only:
            old["cases"] = {k: v for k, v in old["cases"].items()
                            if any(k.startswith(p) for p in a.only.split(","))}
        d = compare(old, res) + res["invariants"]
        print(f"g0 check: {len(res['cases'])} cases, {len(d)} difference(s)")
        for x in d:
            print("  ", x)
        return 1 if d else 0
    except SystemExit:
        raise
    except Exception as e:                        # noqa: BLE001
        print(f"g0: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
