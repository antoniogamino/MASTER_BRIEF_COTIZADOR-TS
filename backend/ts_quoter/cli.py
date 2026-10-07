"""CLI: demo y cálculo sin UI (primer demo, sec. 188).

    tsq demo                                    # demo completo con datos SAMPLE
    tsq calc  <job.json> --master <xlsx> [--as-of 2026-10-06] [--out dir]
    tsq import-master <xlsx>
    tsq explain <costing.json> <line_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from .config import ROOT
from .exporters.excel_summary import export_excel
from .importers.excel import import_cost_master
from .pipeline import run
from .pipeline import run as run_pipeline
from .rules.loader import load_rules
from .schemas.manufacturing import ManufacturingJob


def _fmt(x: Decimal) -> str:
    return f"{x:,.2f}"


def print_report(res) -> None:
    c, r, q = res.cost, res.risk, res.quote
    print("=" * 100)
    if c.uses_sample_data:
        print("*** SAMPLE DATA — NO USAR PARA COTIZAR ***")
    print(f"Proyecto {res.job.project.project_id} | qty={c.quantity} | {c.currency} | {c.rule_set_ref} | {c.cost_master_version} | as_of {c.as_of_date}")
    print("-" * 100)
    print(f"{'line':6} {'categoría':20} {'estado':9} {'setup':>11} {'por unidad':>11}  descripción")
    for l in c.lines:
        print(f"{l.line_id:6} {l.category:20} {l.status.value:9} {_fmt(l.one_time):>11} {_fmt(l.per_unit):>11}  {l.description}"
              + (f"  ⚠ {l.missing_reason}" if l.missing_reason else ""))
    print("-" * 100)
    print(f"Cobertura de costo: {c.coverage.overall}%  {'(PARTIAL COST)' if c.is_partial else ''}")
    print("\nREQUIRES REVIEW")
    for rv in c.review_items:
        print(f"  [{rv.severity.value:8}] impacto {rv.cost_impact.value:6} {rv.description}")
    print(f"\nRIESGO global {r.overall_score} ({r.overall_risk}) | contingencia {r.contingency_mode} efectiva {r.contingency_pct_effective}% | CEI {r.cei} → {r.cei_classification}")
    for cat in (r.interpretation_risk, r.manufacturing_risk, r.cost_data_risk, r.commercial_risk, r.delivery_risk):
        for d in cat.drivers:
            print(f"   {d.category:15} {d.factor:24} +{d.points:>6}  {d.evidence}")
    print(f"\nPRECIO ({q.status})")
    for s in q.steps:
        print(f"  {s.label:30} {_fmt(s.amount):>14}   {s.formula}")
    print(f"  margen objetivo {q.target_margin_pct}%  | markup informativo {q.markup_pct_informative}%")
    print("\n  qty   precio unitario   redondeado")
    for b in q.quantity_breaks:
        print(f"  {b.quantity:>4} {_fmt(b.suggested_unit_price):>16} {_fmt(b.rounded_unit_price):>12}")
    for w in q.warnings + q.stop_reasons:
        print(f"  ⚠ {w}")
    for a in q.required_approvals:
        print(f"  ✋ aprobación requerida: {a}")
    if q.technical_questions:
        print("\nPREGUNTAS TÉCNICAS")
        for t in q.technical_questions:
            print(f"  • {t}")


def explain(costing_path: str, line_id: str) -> None:
    data = json.loads(Path(costing_path).read_text(encoding="utf-8"))
    line = next((l for l in data["lines"] if l["line_id"] == line_id), None)
    if line is None:
        sys.exit(f"línea {line_id} no encontrada")
    print(f"{line['line_id']}  {line['description']}  [{line['status']}]")
    print(f"Fórmula: {line['formula']}")
    print("Insumos:")
    for k, v in line["inputs"].items():
        print(f"  {k:22} = {v['value']} {v.get('unit') or ''}   ← {v['source']}")
    print(f"Resultado: setup {Decimal(line['one_time']):,.4f} + por unidad {Decimal(line['per_unit']):,.4f} ({data['currency']})  "
          f"| horas setup {Decimal(line['hours_one_time']):.4f} · horas/unidad {Decimal(line['hours_per_unit']):.4f}")
    for s in line["sources"]:
        parts = [f"{k}={s[k]}" for k in ("level", "supplier", "reference", "price_date", "age_days", "recency", "original_value",
                                          "original_currency", "adjustment_factor", "fx_rate", "fx_source", "is_sample") if s.get(k) not in (None, "")]
        print(f"Fuente: {s['kind']}:{s['key']}  " + "  ".join(parts))
    for r in line["rule_refs"]:
        print(f"Regla: {r}")


def run_text(a) -> None:
    from .interpreters.base import InterpreterInput
    from .interpreters.payload import human_project_value
    from .interpreters.text.interpreter import TextInterpreter
    from .logging_setup import setup_logging
    from .providers.anthropic import get_provider
    from .providers.base import ReplayProvider
    from .schemas.manufacturing import Project

    setup_logging()
    text = Path(a.file).read_text(encoding="utf-8") if a.file else (a.text or sys.stdin.read())
    pdata: dict = {"project_id": a.project_id, "created_by": "cli"}
    if a.customer:
        pdata["customer"] = human_project_value(a.customer)
    if a.qty:
        pdata["quantity"] = human_project_value(a.qty)
    if a.currency:
        pdata["currency"] = human_project_value(a.currency.upper())
    if a.export:
        pdata["export"] = human_project_value(a.export == "yes")
    provider = ReplayProvider(Path(a.replay).read_text(encoding="utf-8")) if a.replay else get_provider()
    interp = TextInterpreter(provider)
    print(f"Interpretando con {provider.name} ({interp.prompt_version})…")
    run = interp.interpret(InterpreterInput(project=Project(**pdata), text=text))
    out = Path(a.out or ROOT / "sample_projects" / "out" / a.project_id)
    out.mkdir(parents=True, exist_ok=True)
    if run.raw_output:
        (out / "ai_raw_output.json").write_text(run.raw_output, encoding="utf-8")
    print(f"Resultado: {run.outcome}  modelo={run.model}  in={run.input_hash} out={run.output_hash}")
    for e in run.errors:
        print(f"  ✗ {e}")
    if run.job is None:
        sys.exit("Interpretación fallida: el proyecto no se pierde; reintentar o capturar manualmente.")
    (out / "interpreted.json").write_text(run.job.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nComponentes: {len(run.job.components)}  conflictos: {len(run.job.conflicts)}  incertidumbres: {len(run.job.uncertainties)}")
    for c in run.job.components:
        mat = f"{c.material.grade.value} {getattr(c.material.form.value, 'value', c.material.form.value)}" if c.material else "-"
        procs = ", ".join(p.process_type for p in c.processes)
        print(f"  {c.component_id:5} {c.make_or_buy.value:7} {mat:28} {c.description}  [{procs}]")
    if interp.guard_log:
        print("\nGuardas aplicadas:")
        for g in interp.guard_log:
            print(f"  • {g}")
    print(f"\nArchivo: {out / 'interpreted.json'}")
    if a.master:
        master, rep = import_cost_master(a.master, load_rules())
        if master is None:
            print(rep.summary())
            sys.exit("Cost Master inválido")
        res = run_pipeline(run.job, master, load_rules(), date.fromisoformat(a.as_of) if a.as_of else date.today())
        print_report(res)
        res.write(out)
        export_excel(res, out / "internal_costing_report.xlsx")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tsq")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--out", default=str(ROOT / "sample_projects" / "out" / "DEMO-0001"))
    c = sub.add_parser("calc")
    c.add_argument("job")
    c.add_argument("--master", required=True)
    c.add_argument("--rules", default=None)
    c.add_argument("--as-of", default=None, help="fecha de cálculo (default: hoy). Fijarla garantiza reproducibilidad")
    c.add_argument("--out", default=None)
    im = sub.add_parser("import-master")
    im.add_argument("xlsx")
    ex = sub.add_parser("explain")
    ex.add_argument("costing")
    ex.add_argument("line_id")
    t = sub.add_parser("text", help="Interpretar texto del cliente con IA -> MCJ (+ costeo opcional)")
    t.add_argument("text", nargs="?", help="texto de la solicitud (o usar --file)")
    t.add_argument("--file", help="archivo .txt/.eml con la solicitud")
    t.add_argument("--project-id", default="TXT-0001")
    t.add_argument("--customer")
    t.add_argument("--qty", type=int)
    t.add_argument("--currency")
    t.add_argument("--export", choices=["yes", "no"])
    t.add_argument("--replay", help="usar salida IA guardada (JSON) en vez de llamar a la API")
    t.add_argument("--master", help="si se da, costea en seguida con este COST_MASTER.xlsx")
    t.add_argument("--as-of", default=None)
    t.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    if a.cmd == "text":
        run_text(a)
        return
    if a.cmd == "explain":
        explain(a.costing, a.line_id)
        return
    rules = load_rules(getattr(a, "rules", None))
    if a.cmd == "import-master":
        _, rep = import_cost_master(a.xlsx, rules)
        print(rep.summary())
        sys.exit(0 if rep.ok else 1)
    if a.cmd == "demo":
        job_path, master_path, as_of, out = ROOT / "sample_projects" / "charola_304_demo.json", ROOT / "data" / "sample" / "COST_MASTER_SAMPLE.xlsx", date(2026, 10, 6), a.out
    else:
        job_path, master_path, as_of, out = Path(a.job), Path(a.master), date.fromisoformat(a.as_of) if a.as_of else date.today(), a.out
    master, rep = import_cost_master(master_path, rules)
    if master is None:
        print(rep.summary())
        sys.exit("Cost Master inválido; ver reporte")
    job = ManufacturingJob.model_validate_json(Path(job_path).read_text(encoding="utf-8"))
    res = run(job, master, rules, as_of)
    print_report(res)
    if out:
        paths = res.write(out)
        paths.append(export_excel(res, Path(out) / "internal_costing_report.xlsx"))
        print("\nArchivos:", *[str(p) for p in paths], sep="\n  ")


if __name__ == "__main__":
    main()
