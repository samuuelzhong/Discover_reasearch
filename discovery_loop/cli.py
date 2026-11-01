"""CLI — one command per stage, so every step is inspectable and re-runnable."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from . import boss, evolve, hypothesis, scout
from .core import Run
from .data import hydro


def _load_frames(run: Run):
    d = run.dir / "artifacts" / "data"
    if not (d / "manifest.json").exists():
        raise SystemExit("no data yet — run: data --source usgs")
    return hydro.load(d)


def cmd_new(a):
    run = Run(a.id)
    run.decision("boss", "run-init", "created", "new closed-loop run")
    run.summary_append(f"# Run {run.id}\nBoss: discovery_loop.boss；阶段：①Scout ②假设 ③实验 ④分析 → 异常通道回流。")
    print(run.id)
    return 0


def cmd_papers(a):
    run = Run(a.run)
    res = boss.stage_papers(run, a.queries, a.n)
    print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_pdf(a):
    run = Run(a.run)
    ids = boss.stage_pdfs(run, a.paths)
    for cid in ids:
        row = run.get_paper(cid)
        print(f"{cid}\t{len(row['fulltext'])} chars\t{row['title'][:70]}")
    return 0


def cmd_mcp(a):
    run = Run(a.run)
    path = Path(a.paper).expanduser().resolve()
    cfg = {"mcpServers": {f"paper-{a.name}": {
        "command": sys.executable,
        "args": ["-m", "discovery_loop.paper_mcp", "serve", "--paper", str(path), "--name", a.name]}}}
    out = run.dir / "mcp" / f"{a.name}.json"
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    run.event("scout", "mcp_registered", {"name": a.name, "config": str(out)})
    print(out.read_text(encoding="utf-8"))
    return 0


def cmd_ask(a):
    """Drive the paper MCP server over stdio JSON-RPC — the 'discussable' path."""
    path = Path(a.paper).expanduser().resolve()
    proc = subprocess.Popen(
        [sys.executable, "-m", "discovery_loop.paper_mcp", "serve", "--paper", str(path), "--name", a.name],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")

    def rpc(mid, method, params=None):
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    rpc(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "boss", "version": "0.1"}})
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    tools = rpc(2, "tools/list")["result"]["tools"]
    if a.list_tools:
        print("\n".join(t["name"] for t in tools))
        proc.kill()
        return 0
    res = rpc(3, "tools/call", {"name": a.tool, "arguments": json.loads(a.args)})
    print(json.dumps(res["result"], ensure_ascii=False, indent=2)[:6000])
    proc.kill()
    return 0


def cmd_data(a):
    run = Run(a.run)
    states = tuple(a.states.split(","))
    frames, meta, dsha = boss.stage_data(run, a.source, a.path, states, a.per_state)
    print(json.dumps({"basins": len(frames), "data_sha": dsha, "period": meta.get("period")},
                     ensure_ascii=False))
    for k, v in list(meta.get("basins", {}).items())[:12]:
        print(f"  {k}\t{v}")
    return 0


def cmd_hyp(a):
    run = Run(a.run)
    drafts = json.loads(Path(a.file).read_text(encoding="utf-8"))
    res = boss.stage_hypotheses(run, drafts, a.budget)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_elo(a):
    run = Run(a.run)
    print(json.dumps(hypothesis.elo_update(run, a.winner, a.loser, a.judge, a.note), ensure_ascii=False))
    return 0


def cmd_evolve(a):
    run = Run(a.run)
    frames, meta = _load_frames(run)
    summ = boss.stage_evolve(run, frames, a.generations, a.islands, a.pop)
    print(json.dumps({k: summ[k] for k in ("evals", "best_val_median", "best_test_median",
                                           "best_kge_test_median", "best_n_features",
                                           "operator_policy_final", "best_spec")}, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(a):
    run = Run(a.run)
    frames, meta = _load_frames(run)
    verdicts = []
    if a.hypotheses:
        for hp in a.hypotheses:
            h = hypothesis.Hypothesis(**json.loads(Path(hp).read_text(encoding="utf-8")))
            if h.branch != "interpretation":
                continue
            table = None
            verdicts.append({"hid": h.hid, "pending": True})
        verdicts = []
    ana = boss.stage_analysis(run, frames, meta, verdicts)
    print(json.dumps({"n_basins": len(ana["table"]), "n_anomalies": len(ana["anomalies"]),
                      "calibration": ana["calibration"]}, ensure_ascii=False, indent=2))
    for an in ana["anomalies"][:6]:
        print(" -", an["basin"], an["metric"], an["value"], "z=", an["z"])
    return 0


def cmd_test(a):
    run = Run(a.run)
    frames, meta = _load_frames(run)
    table = __import__("discovery_loop.analysis", fromlist=["analysis"]).signature_table(frames)
    h = hypothesis.Hypothesis(**json.loads(Path(a.file).read_text(encoding="utf-8")))
    from . import analysis as ana
    res = ana.hypothesis_test(table, h.decision_criteria)
    run.db.execute("UPDATE hypotheses SET decision=? WHERE hid=?", (res["overall"], h.hid))
    run.db.commit()
    run.event("analysis", "hypothesis_tested", {"hid": h.hid, "result": res})
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_report(a):
    run = Run(a.run)
    frames, meta = _load_frames(run)
    dsha_p = run.dir / "artifacts" / "data" / "DATA_SHA.txt"
    dsha = dsha_p.read_text(encoding="utf-8").strip() if dsha_p.exists() else ""
    evo = json.loads((run.dir / "experiments" / "branch1" / "summary.json").read_text(encoding="utf-8"))
    ana_dir = run.dir / "analysis"
    table = pd.read_csv(ana_dir / "signatures.csv", index_col=0)
    anomalies = json.loads((ana_dir / "anomalies.json").read_text(encoding="utf-8"))
    calib_p = ana_dir / "detector_calibration.json"
    if not calib_p.exists():
        calib_p = ana_dir / "detector_calibration_synthetic.json"
    calib = json.loads(calib_p.read_text(encoding="utf-8")) if calib_p.exists() else None
    verdicts = []
    for p in sorted((run.dir / "verdicts").glob("*.json")) if (run.dir / "verdicts").exists() else []:
        verdicts.append(json.loads(p.read_text(encoding="utf-8")))
    hyp_results = []
    for row in run.db.execute("SELECT hid, branch, gate_status, gate_reasons FROM hypotheses ORDER BY hid"):
        hyp_results.append({"hid": row["hid"], "branch": row["branch"],
                            "ok": row["gate_status"] == "pass",
                            "reasons": json.loads(row["gate_reasons"] or "[]")})
    p = boss.stage_report(run, frames, meta, evo,
                          {"table": table, "anomalies": anomalies, "calibration": calib},
                          hyp_results, verdicts, dsha=dsha)
    print(p)
    return 0


def cmd_prune(a):
    run = Run(a.run)
    res = scout.prune_offtopic(run, a.keywords, a.dry_run)
    print(json.dumps({"kept": res["kept"], "n_dropped": len(res["dropped"])}, ensure_ascii=False))
    for d in res["dropped"]:
        print("  drop:", d["cite_id"], d["title"][:70])
    return 0


def cmd_cite(a):
    run = Run(a.run)
    out = scout.pick_sentence(run, a.cite, a.keywords)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out else 2



def cmd_ablate(a):
    run = Run(a.run)
    frames, meta = _load_frames(run)
    specs = json.loads(Path(a.specs).read_text(encoding="utf-8"))
    from . import analysis as ana
    df = ana.ablate(frames, specs)
    out = run.dir / "experiments" / "ablation"
    out.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(out / "per_basin_nse.csv", index_label="basin")
    table = ana.signature_table(frames)
    table["regime"].to_csv(out / "regimes.csv")
    print(df.round(3).to_string())
    print("\nmedian val NSE:", df.median().round(4).to_dict())
    return 0


def cmd_judge(a):
    run = Run(a.run)
    from . import analysis as ana
    out = run.dir / "experiments" / "ablation"
    df = pd.read_csv(out / "per_basin_nse.csv", index_col=0)
    sig = run.dir / "analysis" / "signatures.csv"
    if sig.exists():
        regimes = pd.read_csv(sig, index_col=0)["snow_class"]
    else:
        regimes = pd.read_csv(out / "regimes.csv", index_col=0)["regime"]
    res = ana.judge_group_delta(df, regimes, a.design_a, a.design_b, a.group_a, a.group_b, a.min_delta)
    (run.dir / "verdicts").mkdir(exist_ok=True)
    (run.dir / "verdicts" / f"{a.hid}.json").write_text(json.dumps({"hid": a.hid, **res}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0

def cmd_status(a):
    run = Run(a.run)
    print(f"run {run.id} @ {run.dir}")
    print("papers:", len(run.papers()), "| verified claims:", len(run.verified_claims()))
    for q in ("SELECT gate_status, COUNT(*) c FROM hypotheses GROUP BY gate_status",
              "SELECT COUNT(*) c FROM evaluations", "SELECT COUNT(*) c FROM anomalies"):
        try:
            print(q.split("FROM ")[1].split()[0], [dict(r) for r in run.db.execute(q).fetchall()])
        except Exception:
            pass
    print("costs:", json.dumps(run.cost_report(), ensure_ascii=False))
    return 0


def cmd_hypo_save(a):
    """Save the test verdict as a file the report reads (keeps stages decoupled)."""
    run = Run(a.run)
    src = Path(a.file)
    h = json.loads(src.read_text(encoding="utf-8"))
    (run.dir / "verdicts").mkdir(exist_ok=True)
    tbl = pd.read_csv(run.dir / "analysis" / "signatures.csv", index_col=0)
    from . import analysis as ana
    res = ana.hypothesis_test(tbl, h["decision_criteria"])
    out = {"hid": h["hid"], "claim": h["claim"], **res}
    (run.dir / "verdicts" / f"{h['hid']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    run.db.execute("UPDATE hypotheses SET decision=? WHERE hid=?", (res["overall"], h["hid"]))
    run.db.commit()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="dl")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new"); p.add_argument("--id"); p.set_defaults(fn=cmd_new)
    p = sub.add_parser("papers"); p.add_argument("--run", required=True)
    p.add_argument("--queries", nargs="+", required=True); p.add_argument("--n", type=int, default=8)
    p.set_defaults(fn=cmd_papers)
    p = sub.add_parser("pdf"); p.add_argument("--run", required=True)
    p.add_argument("--paths", nargs="+", required=True); p.set_defaults(fn=cmd_pdf)
    p = sub.add_parser("mcp"); p.add_argument("--run", required=True); p.add_argument("--paper", required=True)
    p.add_argument("--name", default="paper"); p.set_defaults(fn=cmd_mcp)
    p = sub.add_parser("ask"); p.add_argument("--run"); p.add_argument("--paper", required=True)
    p.add_argument("--name", default="paper"); p.add_argument("--tool", default="check_claim")
    p.add_argument("--args", default='{"statement":"x"}'); p.add_argument("--list-tools", action="store_true")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("data"); p.add_argument("--run", required=True)
    p.add_argument("--source", default="usgs", choices=["usgs", "synthetic", "local"])
    p.add_argument("--path"); p.add_argument("--states", default="ME,NC,CO,WA")
    p.add_argument("--per-state", type=int, default=8); p.set_defaults(fn=cmd_data)
    p = sub.add_parser("hyp"); p.add_argument("--run", required=True); p.add_argument("--file", required=True)
    p.add_argument("--budget", type=float, default=1e9); p.set_defaults(fn=cmd_hyp)
    p = sub.add_parser("elo"); p.add_argument("--run", required=True); p.add_argument("--winner", required=True)
    p.add_argument("--loser", required=True); p.add_argument("--judge", default="boss")
    p.add_argument("--note", default=""); p.set_defaults(fn=cmd_elo)
    p = sub.add_parser("evolve"); p.add_argument("--run", required=True)
    p.add_argument("--generations", type=int, default=3); p.add_argument("--islands", type=int, default=3)
    p.add_argument("--pop", type=int, default=4); p.set_defaults(fn=cmd_evolve)
    p = sub.add_parser("analyze"); p.add_argument("--run", required=True)
    p.add_argument("--hypotheses", nargs="*"); p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("test"); p.add_argument("--run", required=True); p.add_argument("--file", required=True)
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("verdict"); p.add_argument("--run", required=True); p.add_argument("--file", required=True)
    p.set_defaults(fn=cmd_hypo_save)
    p = sub.add_parser("report"); p.add_argument("--run", required=True); p.set_defaults(fn=cmd_report)
    p = sub.add_parser("status"); p.add_argument("--run", required=True); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("prune"); p.add_argument("--run", required=True)
    p.add_argument("--keywords", nargs="+", required=True); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_prune)
    p = sub.add_parser("cite"); p.add_argument("--run", required=True); p.add_argument("--cite", required=True)
    p.add_argument("--keywords", nargs="+", required=True); p.set_defaults(fn=cmd_cite)
    p = sub.add_parser("ablate"); p.add_argument("--run", required=True)
    p.add_argument("--specs", required=True); p.set_defaults(fn=cmd_ablate)
    p = sub.add_parser("judge"); p.add_argument("--run", required=True); p.add_argument("--hid", required=True)
    p.add_argument("--design-a", required=True); p.add_argument("--design-b", required=True)
    p.add_argument("--group-a", default="snow"); p.add_argument("--group-b", default="non_snow")
    p.add_argument("--min-delta", type=float, default=0.0); p.set_defaults(fn=cmd_judge)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
