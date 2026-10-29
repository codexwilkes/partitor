#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""M0: static dependency map of the partitor engine (read-only).

Usage: python3 -I m0_depmap.py ENGINE_FILE OUT_DIR

Parses ENGINE_FILE with ast (never imports or runs it). Writes to OUT_DIR:
  depmap.json   functions, classes, globals, edges, clusters
  M0-REPORT.md  human report

Method
 1. Nodes: top-level def, class, and module-level assignments (constants/state).
 2. Edges: function -> function/class/global names used inside its body
    (ast.Name loads; attribute calls on known module names are ignored).
 3. Mutable shared state: module-level names that are (a) declared `global`
    inside a function and assigned, or (b) bound to a mutable literal/call
    (list, dict, set, ...) and mutated by a method call or item/attr store.
 4. Clusters: Louvain community detection (networkx) on the function call
    graph (undirected, weighted); constants attach to the cluster that uses
    them most. Cluster names are suggestions from the most frequent word in
    function names, to be reviewed by a human.
 5. Cycle report: strongly connected components between clusters.
"""
import ast
import collections
import json
import re
import sys
from pathlib import Path

import networkx as nx

MUTATORS = {"append", "extend", "add", "update", "pop", "clear", "insert",
            "remove", "setdefault", "discard", "popitem", "sort", "reverse"}


def load(path):
    src = Path(path).read_text(encoding="utf-8")
    return src, ast.parse(src, filename=str(path))


def top_level(tree):
    funcs, classes, assigns = {}, {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        assigns[n.id] = node
    return funcs, classes, assigns


def names_used(node, known):
    """Names from `known` that appear as loads inside node."""
    used = collections.Counter()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in known:
            used[n.id] += 1
    return used


def mutable_value(node):
    v = getattr(node, "value", None)
    if isinstance(v, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    if isinstance(v, ast.Call):
        f = v.func
        nm = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
        return nm in {"list", "dict", "set", "defaultdict", "OrderedDict", "Counter", "deque"}
    return False


def shared_state(funcs, classes, assigns):
    """Return {name: {"writers": [...], "kind": ...}} for module-level state."""
    state = collections.defaultdict(lambda: {"writers": set(), "kinds": set()})
    for fname, fn in funcs.items():
        declared = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Global):
                declared.update(n.names)
        for n in ast.walk(fn):
            # rebinding a declared global
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                tg = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in tg:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name) and x.id in declared:
                            state[x.id]["writers"].add(fname)
                            state[x.id]["kinds"].add("rebound via global")
            # mutation of a module-level mutable
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                base = n.func.value
                if (isinstance(base, ast.Name) and base.id in assigns
                        and n.func.attr in MUTATORS and mutable_value(assigns[base.id])):
                    state[base.id]["writers"].add(fname)
                    state[base.id]["kinds"].add(f"mutated .{n.func.attr}()")
            if isinstance(n, (ast.Assign, ast.AugAssign)):
                tg = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in tg:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                        b = t.value.id
                        if b in assigns and mutable_value(assigns[b]):
                            state[b]["writers"].add(fname)
                            state[b]["kinds"].add("item store")
    return state


def build_graph(funcs, classes, assigns):
    callable_names = set(funcs) | set(classes)
    all_names = callable_names | set(assigns)
    edges = collections.defaultdict(collections.Counter)
    for name, node in list(funcs.items()) + list(classes.items()):
        for used, cnt in names_used(node, all_names).items():
            if used != name:
                edges[name][used] += cnt
    return edges


def cluster(funcs, classes, edges):
    g = nx.Graph()
    callables = set(funcs) | set(classes)
    g.add_nodes_from(callables)
    for a, nbrs in edges.items():
        for b, w in nbrs.items():
            if a in callables and b in callables:
                prev = g.get_edge_data(a, b, {"weight": 0})["weight"]
                g.add_edge(a, b, weight=prev + w)
    comms = nx.community.louvain_communities(g, weight="weight", seed=1, resolution=1.0)
    return [sorted(c) for c in sorted(comms, key=len, reverse=True)]


def label(members):
    words = collections.Counter()
    for m in members:
        for w in re.split(r"[_]+", m.strip("_").lower()):
            if len(w) > 2 and w not in {"the", "get", "set", "and", "for", "make", "new", "add"}:
                words[w] += 1
    return "-".join(w for w, _ in words.most_common(3)) or "misc"


def main(engine, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    src, tree = load(engine)
    funcs, classes, assigns = top_level(tree)
    edges = build_graph(funcs, classes, assigns)
    state = shared_state(funcs, classes, assigns)
    comms = cluster(funcs, classes, edges)

    owner = {}
    for i, c in enumerate(comms):
        for m in c:
            owner[m] = i

    # constants/state: attach to the cluster that uses them most
    used_by = collections.defaultdict(collections.Counter)
    for caller, nbrs in edges.items():
        for callee, w in nbrs.items():
            if callee in assigns and caller in owner:
                used_by[callee][owner[caller]] += w
    const_cluster = {}
    cross_const = []
    for const, cnt in used_by.items():
        const_cluster[const] = cnt.most_common(1)[0][0]
        if len(cnt) > 1:
            cross_const.append((const, dict(cnt)))

    # inter-cluster call edges
    inter = collections.Counter()
    for a, nbrs in edges.items():
        for b, w in nbrs.items():
            if a in owner and b in owner and owner[a] != owner[b]:
                inter[(owner[a], owner[b])] += w
    dg = nx.DiGraph()
    dg.add_nodes_from(range(len(comms)))
    for (a, b), w in inter.items():
        dg.add_edge(a, b, weight=w)
    sccs = [sorted(s) for s in nx.strongly_connected_components(dg) if len(s) > 1]

    lines_of = lambda n: (n.end_lineno - n.lineno + 1)
    cl = []
    for i, c in enumerate(comms):
        loc = sum(lines_of(funcs[m] if m in funcs else classes[m]) for m in c)
        consts = sorted(k for k, v in const_cluster.items() if v == i)
        cl.append({"id": i, "label": label(c), "functions": c, "loc": loc,
                   "constants": consts})

    report = {
        "engine": str(engine),
        "totals": {"lines": src.count("\n") + 1, "functions": len(funcs),
                   "classes": len(classes), "module_level_names": len(assigns)},
        "clusters": cl,
        "shared_mutable_state": {k: {"writers": sorted(v["writers"]),
                                     "kinds": sorted(v["kinds"])}
                                 for k, v in sorted(state.items())},
        "constants_used_by_several_clusters": cross_const,
        "inter_cluster_edges": {f"{a}->{b}": w for (a, b), w in inter.most_common()},
        "cluster_cycles": sccs,
    }
    (out / "depmap.json").write_text(json.dumps(report, indent=1))

    md = []
    t = report["totals"]
    md.append("# M0 — partitor engine dependency map\n")
    md.append(f"Engine: `{engine}`. {t['lines']} lines, {t['functions']} functions, "
              f"{t['classes']} classes, {t['module_level_names']} module-level names.\n")
    md.append("Method: static `ast` parse, no import. Louvain communities on the call graph "
              "(seed 1, resolution 1.0). Labels are guesses from function names. "
              "A human must review every cluster.\n")
    md.append("## Clusters (candidate modules)\n")
    md.append("| # | label (guess) | functions | LOC | constants | out-edges | in-edges |")
    md.append("|---|---|---|---|---|---|---|")
    for c in cl:
        o = sum(w for (a, b), w in inter.items() if a == c["id"])
        n = sum(w for (a, b), w in inter.items() if b == c["id"])
        md.append(f"| {c['id']} | {c['label']} | {len(c['functions'])} | {c['loc']} | "
                  f"{len(c['constants'])} | {o} | {n} |")
    md.append("\n## Cycles between clusters\n")
    if sccs:
        md.append("Clusters that depend on each other (must be broken or merged before a split):\n")
        for s in sccs:
            md.append(f"- clusters {s}")
    else:
        md.append("None. The cluster graph is acyclic.")
    md.append("\n## Heaviest cross-cluster edges (calls + name uses)\n")
    md.append("| from | to | weight |\n|---|---|---|")
    for (a, b), w in inter.most_common(15):
        md.append(f"| {a} {cl[a]['label']} | {b} {cl[b]['label']} | {w} |")
    md.append("\n## Shared mutable module state\n")
    md.append("| name | kinds | written by |\n|---|---|---|")
    for k, v in report["shared_mutable_state"].items():
        w = ", ".join(v["writers"][:6]) + (" …" if len(v["writers"]) > 6 else "")
        md.append(f"| `{k}` | {', '.join(v['kinds'])} | {w} |")
    md.append("\n## Constants used from several clusters\n")
    md.append("These belong in a shared `constants` module or a config object.\n")
    md.append("| constant | uses per cluster |\n|---|---|")
    for k, v in sorted(cross_const, key=lambda x: -sum(x[1].values()))[:25]:
        md.append(f"| `{k}` | {v} |")
    md.append("\n## Cluster contents\n")
    for c in cl:
        md.append(f"### {c['id']} — {c['label']} ({len(c['functions'])} functions, {c['loc']} LOC)\n")
        md.append(", ".join(f"`{f}`" for f in c["functions"]) + "\n")
        if c["constants"]:
            md.append("Constants: " + ", ".join(f"`{k}`" for k in c["constants"][:40]) + "\n")
    (out / "M0-REPORT.md").write_text("\n".join(md))
    print(f"clusters: {len(cl)}  cycles: {len(sccs)}  shared-state names: {len(state)}")
    print(f"wrote {out/'M0-REPORT.md'}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: m0_depmap.py ENGINE_FILE OUT_DIR")
    main(sys.argv[1], sys.argv[2])
