"""Write the Power BI project (PBIP: TMDL semantic model + PBIR report) under dashboard/.

Column types are read from the bi.* views in Postgres so the model always matches the warehouse.
Lineage tags and ids are uuid5, so a rerun produces identical files. Open dashboard/ShipOrStop.pbip
in Power BI Desktop, enter the Postgres login once and Refresh: every table is an import from bi.*.
"""
import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shiporstop import db  # noqa: E402
from shiporstop.config import DB, ROOT  # noqa: E402

DASH = ROOT / "dashboard"
NAME = "ShipOrStop"
NS = uuid.UUID("7b1d2c64-5a0e-4c1f-9d8e-1f2a3b4c5d6e")


def tag(*parts):
    return str(uuid.uuid5(NS, "/".join(parts)))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def wjson(path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ model
TABLES = {
    "program_kpis": "One row of program-level KPIs computed in SQL",
    "experiments": "One row per experiment",
    "arms": "One row per treatment arm with its verdict",
    "final_results": "Full-horizon read per arm x metric (Holm within experiment, BH across program)",
    "checkpoints": "Every testable checkpoint with z, OBF boundary and always-valid p",
    "srm": "Sample ratio per arm at the final checkpoint",
    "srm_trajectory": "Treatment share and SRM p-value over the life of each arm",
    "null_fpr": "A/A replay on the real checkpoint schedules, false positive rate per stopping rule",
    "peeking_curve": "False positive rate vs number of equally spaced looks",
    "sequential_stops": "First stop per rule per arm x metric, agreement with full horizon",
    "sequential_summary": "Stopping rules compared on the primary metric",
    "verdict_counts": "Verdicts across the portfolio",
    "decision_sensitivity": "Verdict counts over alpha x guardrail margin",
    "heterogeneity": "Between-experiment spread of true effects (DerSimonian-Laird)",
    "eb_shrinkage": "Observed vs empirical-Bayes shrunk lift",
    "metric_tree": "Program health KPI tree",
    "verdict_segments": "Outcome rates by experiment size, length and design",
    "metric_comovement": "Correlation of treatment-effect z between metric pairs",
    "metric_sensitivity": "How often each metric detects an effect",
    "early_read": "How well an early read predicts the final result",
    "dq_checks": "Data quality checks (raw file and staging)",
    "dq_incidents": "Row-level data incidents on the primary metric",
    "layer_rows": "Row counts per warehouse layer",
    "load_audit": "Load audit: source file hash and rows",
}

RELS = [
    ("arms", "experiment_id", "experiments", "experiment_id"),
    ("final_results", "arm_id", "arms", "arm_id"),
    ("checkpoints", "arm_id", "arms", "arm_id"),
    ("sequential_stops", "arm_id", "arms", "arm_id"),
    ("srm_trajectory", "arm_id", "arms", "arm_id"),
]

SORT_BY = {("verdict_counts", "verdict"): "verdict_order", ("null_fpr", "rule"): "rule_order",
           ("sequential_summary", "rule"): "rule_order", ("arms", "outcome"): "outcome_order"}

PG = {"integer": ("int64", "#,0", "Int64.Type"), "bigint": ("int64", "#,0", "Int64.Type"),
      "smallint": ("int64", "0", "Int64.Type"), "numeric": ("double", "#,0.00", "type number"),
      "double precision": ("double", "#,0.0000", "type number"), "text": ("string", None, "type text"),
      "date": ("dateTime", "yyyy-mm-dd", "type date"),
      "timestamp with time zone": ("dateTime", "yyyy-mm-dd hh:nn", "type datetimezone"),
      "timestamp without time zone": ("dateTime", "yyyy-mm-dd hh:nn", "type datetime"),
      "boolean": ("boolean", None, "type logical")}

PCT_COLS = {"primary_lift", "primary_low", "primary_high", "eb_lift", "mde_rel_80", "worst_guardrail_low",
            "treatment_share", "rel_lift", "rel_ci_low", "rel_ci_high", "observed_lift", "rel_se", "eb_sd",
            "shrinkage", "abs_shrinkage", "pooled_lift", "tau", "i2", "win_rate", "loss_rate", "flat_rate",
            "untrusted_rate", "avg_abs_lift", "median_mde", "sign_agreement", "significance_agreement",
            "share_significant", "share_significant_holm", "median_mde_rel", "sign_agreement_when_final_sig",
            "share_sig_early", "share_early_sig_not_final", "false_positive_rate", "naive_peeking",
            "obrien_fleming", "msprt", "ship_rate", "harm_rate", "srm_rate", "fpr_fixed", "fpr_naive",
            "fpr_obf", "fpr_msprt", "avg_shrunk_win_lift", "avg_observed_win_lift", "median_mde_rel",
            "tau_primary", "info_frac", "shrink_factor"}
HIDDEN = set()

P1 = "0.0%"
P2 = "0.00%"
MEASURES = [
    # folder, name, dax, format, description
    ("Program", "Experiments", "MAX ( program_kpis[experiments] )", "#,0", None),
    ("Program", "Treatment Arms", "MAX ( program_kpis[arms] )", "#,0", None),
    ("Program", "Testable Checkpoints", "MAX ( program_kpis[testable_checkpoints] )", "#,0", None),
    ("Program", "Ship Rate", "MAX ( program_kpis[ship_rate] )", P1, "Arms with verdict SHIP / all arms"),
    ("Program", "Harm Rate", "MAX ( program_kpis[harm_rate] )", P1, "Arms with a STOP verdict / all arms"),
    ("Program", "SRM Rate", "MAX ( program_kpis[srm_rate] )", P1, "Arms failing the sample ratio check"),
    ("Program", "Ship Arms", "MAX ( program_kpis[ship] )", "#,0", None),
    ("Program", "Stop Arms", "MAX ( program_kpis[stop] )", "#,0", None),
    ("Program", "Inconclusive Arms", "MAX ( program_kpis[inconclusive] )", "#,0", None),
    ("Program", "Untrusted Arms", "MAX ( program_kpis[untrusted] )", "#,0", None),
    ("Program", "Median Horizon Days", "MAX ( program_kpis[median_horizon_days] )", "#,0.0", None),
    ("Program", "Median MDE", "MAX ( program_kpis[median_mde_rel] )", P2, "Median smallest relative lift detectable at 80% power"),
    ("Peeking", "FPR Fixed", "MAX ( program_kpis[fpr_fixed] )", P1, None),
    ("Peeking", "FPR Naive Peeking", "MAX ( program_kpis[fpr_naive] )", P1, "Stop at the first |z| >= 1.96"),
    ("Peeking", "FPR OBF", "MAX ( program_kpis[fpr_obf] )", P1, None),
    ("Peeking", "FPR mSPRT", "MAX ( program_kpis[fpr_msprt] )", P1, None),
    ("Peeking", "Naive Wrong Calls", "MAX ( program_kpis[naive_wrong_calls] )", "#,0", "Primary arms where the first naive crossing disagrees with the full horizon"),
    ("Peeking", "False Positive Rate", "AVERAGE ( null_fpr[false_positive_rate] )", P1, None),
    ("Peeking", "Curve Naive", "AVERAGE ( peeking_curve[naive_peeking] )", P1, None),
    ("Peeking", "Curve OBF", "AVERAGE ( peeking_curve[obrien_fleming] )", P1, None),
    ("Peeking", "Curve mSPRT", "AVERAGE ( peeking_curve[msprt] )", P1, None),
    ("Sequential", "OBF Median Days Saved", "MAX ( program_kpis[obf_median_days_saved] )", "#,0.0", None),
    ("Sequential", "mSPRT Median Days Saved", "MAX ( program_kpis[msprt_median_days_saved] )", "#,0.0", None),
    ("Sequential", "Arm-days Freed by OBF", "MAX ( program_kpis[arm_days_saved_obf] )", "#,0", None),
    ("Sequential", "Arm-days Run", "MAX ( program_kpis[arm_days_run] )", "#,0", None),
    ("Sequential", "OBF Agreement", "DIVIDE ( MAX ( program_kpis[obf_agrees] ), MAX ( program_kpis[primary_fixed_sig] ) )", P1, "Significant full-horizon arms that OBF calls the same way"),
    ("Sequential", "mSPRT Agreement", "DIVIDE ( MAX ( program_kpis[msprt_agrees] ), MAX ( program_kpis[primary_fixed_sig] ) )", P1, None),
    ("Sequential", "Avg OBF Stop Day", "AVERAGE ( sequential_stops[obf_day] )", "#,0.0", None),
    ("Sequential", "Avg Horizon Day", "AVERAGE ( sequential_stops[horizon_days] )", "#,0.0", None),
    ("Sequential", "Days Saved OBF", "SUM ( sequential_stops[obf_days_saved] )", "#,0.0", None),
    ("Checkpoints", "Z", "AVERAGE ( checkpoints[z] )", "0.00", None),
    ("Checkpoints", "OBF Upper", "AVERAGE ( checkpoints[obf_upper] )", "0.00", None),
    ("Checkpoints", "OBF Lower", "AVERAGE ( checkpoints[obf_lower] )", "0.00", None),
    ("Checkpoints", "Naive Upper", "AVERAGE ( checkpoints[naive_upper] )", "0.00", None),
    ("Checkpoints", "Naive Lower", "AVERAGE ( checkpoints[naive_lower] )", "0.00", None),
    ("Checkpoints", "Always-valid p", "AVERAGE ( checkpoints[always_valid_p] )", "0.000", None),
    ("Checkpoints", "Naive p", "AVERAGE ( checkpoints[p_naive] )", "0.000", None),
    ("Checkpoints", "Cumulative Lift", "AVERAGE ( checkpoints[rel_lift] )", P2, None),
    ("Checkpoints", "Lift CI Low", "AVERAGE ( checkpoints[rel_ci_low] )", P2, None),
    ("Checkpoints", "Lift CI High", "AVERAGE ( checkpoints[rel_ci_high] )", P2, None),
    ("Checkpoints", "Arm Sample", "MAX ( checkpoints[n] )", "#,0", None),
    ("SRM", "SRM Arms", "CALCULATE ( COUNTROWS ( srm ), srm[ratio_status] = \"SRM\" ) + 0", "#,0", None),
    ("SRM", "Allocation Unknown Arms", "CALCULATE ( COUNTROWS ( srm ), srm[ratio_status] = \"allocation unknown\" ) + 0", "#,0", None),
    ("SRM", "Healthy Ratio Share", "DIVIDE ( CALCULATE ( COUNTROWS ( srm ), srm[ratio_status] = \"healthy\" ), COUNTROWS ( srm ) )", P1, None),
    ("SRM", "Arm Users", "SUM ( srm[n_c] ) + SUM ( srm[n_t] )", "#,0", None),
    ("SRM", "Arm Treatment Share", "AVERAGE ( srm[treatment_share] )", "0.00%", None),
    ("Tree", "KPI Count", "COUNTROWS ( metric_tree )", "#,0", None),
    ("SRM", "Arms by Status", "COUNTROWS ( srm )", "#,0", None),
    ("SRM", "Treatment Share", "AVERAGE ( srm_trajectory[treatment_share] )", "0.000%", None),
    ("SRM", "Worst Share Gap", "MAXX ( FILTER ( srm, srm[ratio_status] = \"SRM\" ), ABS ( srm[treatment_share] - 0.5 ) )", "0.00%", "Largest |share - 50%| among SRM arms"),
    ("Verdicts", "Arms", "SUM ( verdict_counts[arms] )", "#,0", None),
    ("Verdicts", "Arm Count", "COUNTROWS ( arms )", "#,0", None),
    ("Verdicts", "Primary Lift", "AVERAGE ( arms[primary_lift] )", P2, None),
    ("Verdicts", "Primary CI Low", "AVERAGE ( arms[primary_low] )", P2, None),
    ("Verdicts", "Primary CI High", "AVERAGE ( arms[primary_high] )", P2, None),
    ("Verdicts", "Guardrail Breaches", "SUM ( arms[guardrails_breached] )", "#,0", None),
    ("Verdicts", "Guardrails Unproven", "SUM ( arms[guardrails_unproven] )", "#,0", None),
    ("Verdicts", "Arms with Guardrail Breach", "CALCULATE ( COUNTROWS ( arms ), arms[guardrails_breached] > 0 ) + 0", "#,0", None),
    ("Verdicts", "Worst Guardrail Low", "MIN ( arms[worst_guardrail_low] )", P2, None),
    ("Verdicts", "Avg Observed Win Lift", "MAX ( program_kpis[avg_observed_win_lift] )", P2, None),
    ("Verdicts", "Avg Shrunk Win Lift", "MAX ( program_kpis[avg_shrunk_win_lift] )", P2, None),
    ("Verdicts", "Sensitivity Arms", "SUM ( decision_sensitivity[arms] )", "#,0", None),
    ("Shrinkage", "Observed Lift", "AVERAGE ( eb_shrinkage[observed_lift] )", P2, None),
    ("Shrinkage", "Shrunk Lift", "AVERAGE ( eb_shrinkage[eb_lift] )", P2, None),
    ("Shrinkage", "Shrink Factor", "CALCULATE ( AVERAGE ( eb_shrinkage[shrink_factor] ), eb_shrinkage[metric_id] = 1 )", "0.00", "Average weight on the program mean for the primary metric (1 = fully shrunk)"),
    ("Shrinkage", "Tau Primary", "MAX ( program_kpis[tau_primary] )", P2, "Between-experiment sd of true primary lifts"),
    ("Shrinkage", "Tau", "AVERAGE ( heterogeneity[tau] )", P2, None),
    ("Shrinkage", "I2", "AVERAGE ( heterogeneity[i2] )", P1, None),
    ("Segments", "Win Rate", "AVERAGE ( verdict_segments[win_rate] )", P1, None),
    ("Segments", "Loss Rate", "AVERAGE ( verdict_segments[loss_rate] )", P1, None),
    ("Segments", "Flat Rate", "AVERAGE ( verdict_segments[flat_rate] )", P1, None),
    ("Segments", "Segment Arms", "SUM ( verdict_segments[arms] )", "#,0", None),
    ("Segments", "Segment MDE", "AVERAGE ( verdict_segments[median_mde] )", P2, None),
    ("Metrics", "Z Correlation", "AVERAGE ( metric_comovement[z_corr] )", "0.00", None),
    ("Metrics", "Sign Agreement", "AVERAGE ( metric_comovement[sign_agreement] )", P1, None),
    ("Metrics", "Early Z Corr", "AVERAGE ( early_read[z_corr] )", "0.00", None),
    ("Metrics", "Early Sign Agreement", "AVERAGE ( early_read[sign_agreement_when_final_sig] )", P1, None),
    ("Metrics", "Early False Alarm", "AVERAGE ( early_read[share_early_sig_not_final] )", P1, "Significant at the read day but not at the end"),
    ("Metrics", "Min Metric Corr", "CALCULATE ( MIN ( metric_comovement[z_corr] ), metric_comovement[metric_a] <> metric_comovement[metric_b] )", "0.00", None),
    ("Metrics", "Day 7 Sign Agreement", "CALCULATE ( AVERAGE ( early_read[sign_agreement_when_final_sig] ), early_read[read_day] = 7, early_read[early_metric] = 1, early_read[final_metric] = 1 )", P1, None),
    ("Metrics", "Day 7 Z Corr", "CALCULATE ( AVERAGE ( early_read[z_corr] ), early_read[read_day] = 7, early_read[early_metric] = 1, early_read[final_metric] = 1 )", "0.00", None),
    ("Quality", "Raw Rows", "CALCULATE ( SUM ( layer_rows[row_count] ), layer_rows[object] = \"raw.asos_checkpoints\" )", "#,0", None),
    ("Quality", "Rejected Rows", "CALCULATE ( SUM ( layer_rows[row_count] ), layer_rows[object] = \"stg.rejected_checkpoints\" )", "#,0", None),
    ("Quality", "DQ Checks", "COUNTROWS ( dq_checks )", "#,0", None),
    ("Quality", "DQ Errors", "CALCULATE ( COUNTROWS ( dq_checks ), dq_checks[severity] = \"error\", dq_checks[passed] = FALSE () ) + 0", "#,0", None),
    ("Quality", "DQ Warnings", "CALCULATE ( COUNTROWS ( dq_checks ), dq_checks[severity] = \"warn\", dq_checks[passed] = FALSE () ) + 0", "#,0", None),
    ("Quality", "Incidents", "COUNTROWS ( dq_incidents )", "#,0", None),
    ("Quality", "Layer Rows", "SUM ( layer_rows[row_count] )", "#,0", None),
    ("Tree", "KPI Value", "MAX ( metric_tree[value_display] )", None, None),
    ("Tree", "KPI Target", "MAX ( metric_tree[target_display] )", None, None),
]


def columns(conn, view):
    return conn.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = 'bi' and table_name = %s order by ordinal_position", (view,)).fetchall()


def tmdl_table(conn, name):
    lines = [f"/// {TABLES[name]}", f"table {name}", f"\tlineageTag: {tag('t', name)}"]
    lines.append("")
    typed = []
    for c, t in columns(conn, name):
        dt, fmt, mtype = PG[t]
        if c in PCT_COLS:
            fmt = "0.00%"
        elif c.startswith("p_") or c.endswith("_p") or c == "p_value":
            fmt = "0.00E+00"
        if c.endswith("_id") or c.endswith("_order") or c in ("look", "looks", "variant_id", "metric_a", "metric_b",
                                                               "early_metric", "final_metric", "node_id", "load_id"):
            fmt = "0"
        lines.append(f"\tcolumn {c}")
        lines.append(f"\t\tdataType: {dt}")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        if (name, c) in HIDDEN:
            lines.append("\t\tisHidden")
        lines.append(f"\t\tlineageTag: {tag('c', name, c)}")
        lines.append("\t\tsummarizeBy: none")
        lines.append(f"\t\tsourceColumn: {c}")
        if (name, c) in SORT_BY:
            lines.append(f"\t\tsortByColumn: {SORT_BY[(name, c)]}")
        lines += ["", "\t\tannotation SummarizationSetBy = Automatic", ""]
        typed.append(f'{{"{c}", {mtype}}}')
    lines += [
        f"\tpartition {name} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        "\t\t\t\t    Source = PostgreSQL.Database ( PgServer, PgDatabase ),",
        f'\t\t\t\t    View = Source{{[Schema = "bi", Item = "{name}"]}}[Data],',
        f"\t\t\t\t    Typed = Table.TransformColumnTypes ( View, {{{', '.join(typed)}}} )",
        "\t\t\t\tin",
        "\t\t\t\t    Typed",
        "",
    ]
    return "\n".join(lines)


def tmdl_measures():
    lines = ["table _Measures", f"\tlineageTag: {tag('t', '_Measures')}", ""]
    for folder, name, expr, fmt, desc in MEASURES:
        if desc:
            lines.append(f"\t/// {desc}")
        lines.append(f"\tmeasure '{name}' = {expr}")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        lines.append(f"\t\tdisplayFolder: {folder}")
        lines.append(f"\t\tlineageTag: {tag('m', name)}")
        lines.append("")
    lines += ["\tcolumn Value", "\t\tdataType: string", "\t\tisHidden", f"\t\tlineageTag: {tag('c', '_Measures', 'Value')}",
              "\t\tsummarizeBy: none", "\t\tisNameInferred", "\t\tsourceColumn: [Value]", "",
              "\t\tannotation SummarizationSetBy = Automatic", "",
              "\tpartition _Measures = calculated", "\t\tmode: import", '\t\tsource = ROW ( "Value", BLANK () )', ""]
    return "\n".join(lines)


def build_model(conn):
    sm = DASH / f"{NAME}.SemanticModel"
    d = sm / "definition"
    if d.exists():
        shutil.rmtree(d)
    wjson(sm / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": tag("sm")}})
    wjson(sm / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}})
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1606\n")
    write(d / "expressions.tmdl",
          f'expression PgServer = "{DB["host"]}:{DB["port"]}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
          f"\tlineageTag: {tag('e', 'PgServer')}\n\n\tannotation PBI_ResultType = Text\n\n"
          f'expression PgDatabase = "{DB["dbname"]}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
          f"\tlineageTag: {tag('e', 'PgDatabase')}\n\n\tannotation PBI_ResultType = Text\n")
    order = list(TABLES) + ["_Measures"]
    write(d / "model.tmdl",
          "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tdiscourageImplicitMeasures\n\tsourceQueryCulture: en-US\n\n"
          f"annotation PBI_QueryOrder = {json.dumps(['PgServer', 'PgDatabase'] + order)}\n\n"
          "annotation __PBI_TimeIntelligenceEnabled = 0\n\n"
          + "".join(f"ref table {t}\n" for t in order))
    rel = [f"relationship {tag('r', ft, fc, tt)}\n\tfromColumn: {ft}.{fc}\n\ttoColumn: {tt}.{tc}\n" for ft, fc, tt, tc in RELS]
    write(d / "relationships.tmdl", "\n".join(rel))
    for t in TABLES:
        write(d / "tables" / f"{t}.tmdl", tmdl_table(conn, t))
    write(d / "tables" / "_Measures.tmdl", tmdl_measures())


# ------------------------------------------------------------------ report
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def field(ref):
    """'table.column' or '[Measure]'"""
    if ref.startswith("["):
        m = ref[1:-1]
        return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": m}},
                "queryRef": f"_Measures.{m}", "nativeQueryRef": m}
    t, c = ref.split(".", 1)
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}},
            "queryRef": ref, "nativeQueryRef": c}


def container(title):
    return {
        "title": [{"properties": {"show": lit("true"), "text": lit(f"'{title}'"),
                                  "fontSize": lit("13D"), "fontColor": {"solid": {"color": lit("'#323130'")}}}}],
        "background": [{"properties": {"show": lit("true"), "color": {"solid": {"color": lit("'#FFFFFF'")}}}}],
        "border": [{"properties": {"show": lit("true"), "color": {"solid": {"color": lit("'#E6E6E6'")}}, "radius": lit("2D")}}],
        "dropShadow": [{"properties": {"show": lit("false")}}],
    }


class Page:
    def __init__(self, name, display, subtitle):
        self.name, self.display, self.subtitle = name, display, subtitle
        self.visuals, self.texts = [], []

    def add(self, vtype, title, x, y, w, h, roles, sort=None, objects=None, filters=None):
        v = {"visualType": vtype,
             "query": {"queryState": {role: {"projections": [field(f) for f in fs]} for role, fs in roles.items()}},
             "drillFilterOtherVisuals": True,
             "visualContainerObjects": container(title)}
        if sort:
            ref, direction = sort
            v["query"]["sortDefinition"] = {"sort": [{"field": field(ref)["field"], "direction": direction}],
                                            "isDefaultSort": True}
        if vtype in ("clusteredBarChart", "clusteredColumnChart", "donutChart"):
            objects = {"labels": [{"properties": {"show": lit("true"), "fontSize": lit("10D")}}], **(objects or {})}
        if vtype in ("tableEx", "pivotTable"):
            size = "12D"
            base = {k: [{"properties": {"fontSize": lit(size)}}] for k in ("values", "columnHeaders", "rowHeaders", "total")}
            base.update(objects or {})
            objects = base
        if objects:
            v["objects"] = objects
        self.visuals.append((f"{self.name}_v{len(self.visuals) + 1:02d}", x, y, w, h, v, filters))
        return self

    def slicer(self, title, x, y, w, h, col):
        obj = {"data": [{"properties": {"mode": lit("'Dropdown'")}}]}
        return self.add("slicer", title, x, y, w, h, {"Values": [col]}, objects=obj)

    def cards(self, measures, y=90, x0=20, h=110, gap=16, total=1880):
        w = (total - gap * (len(measures) - 1)) // len(measures)
        for i, m in enumerate(measures):
            self.add("card", m, x0 + i * (w + gap), y, w, h, {"Values": [f"[{m}]"]},
                     objects={"labels": [{"properties": {"fontSize": lit("30D"), "color": {"solid": {"color": lit("'#1F4E79'")}}}}],
                              "categoryLabels": [{"properties": {"show": lit("false")}}]})
        return self

    def text(self, x, y, w, h, paragraphs):
        self.texts.append((x, y, w, h, paragraphs))
        return self


def cat_filter(entity, prop, values, fname):
    return {"filters": [{"name": fname, "field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
                         "type": "Categorical",
                         "filter": {"Version": 2, "From": [{"Name": "t", "Entity": entity, "Type": 0}],
                                    "Where": [{"Condition": {"In": {
                                        "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": prop}}],
                                        "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}]}}]}


def num_filter(entity, prop, value, fname):
    f = cat_filter(entity, prop, ["x"], fname)
    f["filters"][0]["filter"]["Where"][0]["Condition"]["In"]["Values"] = [[{"Literal": {"Value": f"{value}L"}}]]
    return f


def pages():
    out = []

    p = Page("p01_overview", "Program Overview",
             "78 real ASOS.com experiments, 99 treatment arms, 4 decision metrics, daily checkpoints. Verdict = primary metric up, guardrails non-inferior (-1%), healthy sample ratio")
    p.cards(["Experiments", "Treatment Arms", "Ship Rate", "Harm Rate", "SRM Rate", "FPR Naive Peeking"], y=90)
    p.add("clusteredBarChart", "Portfolio verdicts", 20, 220, 760, 400, {"Category": ["verdict_counts.verdict"], "Y": ["[Arms]"]}, sort=("verdict_counts.verdict", "Ascending"))
    p.add("clusteredColumnChart", "A/A replay: false positive rate by stopping rule (target 5%)", 796, 220, 1104, 400, {"Category": ["null_fpr.rule"], "Y": ["[False Positive Rate]"]}, sort=("null_fpr.rule", "Ascending"))
    p.add("tableEx", "Program health metric tree", 20, 636, 1180, 420, {"Values": ["metric_tree.branch", "metric_tree.kpi", "metric_tree.value_display", "metric_tree.target_display", "metric_tree.status"]}, sort=("metric_tree.node_id", "Ascending"))
    p.text(1216, 636, 684, 420, [
        ("What the program should change", "18pt", True),
        ("1. Daily peeking at 1.96 gives ~19% false positives. Move to an O'Brien-Fleming plan: 5% error and a median 25 days earlier.", "14pt", False),
        ("2. 9 of 99 arms fail SRM. Gate readouts on a chi-square check.", "14pt", False),
        ("3. 1 in 7 arms wins, 1 in 10 hurts. Inconclusive is the norm, not a failure.", "14pt", False),
        ("4. Report shrunk lifts in roadmaps: noisy wins shrink hard.", "14pt", False),
        ("5. The 4 metrics move together (z corr 0.89-0.97): one guardrail would do.", "14pt", False),
    ])
    out.append(p)

    p = Page("p02_metric_tree", "Program Metric Tree",
             "Program health = Trust x Speed x Impact x Risk. Targets are the program's own policy targets (illustrative), status is computed in SQL")
    p.cards(["Healthy Ratio Share", "DQ Errors", "Median Horizon Days", "OBF Median Days Saved", "Ship Rate", "Naive Wrong Calls"], y=90)
    p.add("tableEx", "Metric tree: Program health > branch > KPI", 20, 220, 1180, 836, {"Values": ["metric_tree.branch", "metric_tree.kpi", "metric_tree.value_display", "metric_tree.target_display", "metric_tree.status"]}, sort=("metric_tree.node_id", "Ascending"),
          objects={k: [{"properties": {"fontSize": lit("14D")}}] for k in ("values", "columnHeaders")})
    p.add("clusteredColumnChart", "KPIs on / off target by branch", 1216, 220, 684, 420, {"Category": ["metric_tree.branch"], "Series": ["metric_tree.status"], "Y": ["[KPI Count]"]})
    p.text(1216, 656, 684, 400, [
        ("How to read the tree", "16pt", True),
        ("Trust: can we believe the readout? (sample ratio, data quality, error rate of the stopping rule)", "13pt", False),
        ("Speed: how long until a decision, and how much traffic a sequential plan would free", "13pt", False),
        ("Impact: how often we ship, and how big wins really are after shrinkage", "13pt", False),
        ("Risk: how often a change hurts, and how many calls a naive peek gets wrong", "13pt", False),
    ])
    out.append(p)

    p = Page("p03_data_quality", "Data Quality & Lineage",
             "raw -> staging -> marts -> bi. Error checks stop the pipeline; warnings are logged and the offending rows kept in an incident log")
    p.cards(["Raw Rows", "Testable Checkpoints", "Rejected Rows", "DQ Checks", "DQ Errors", "DQ Warnings"], y=90)
    p.add("clusteredBarChart", "Rows per warehouse object", 20, 220, 760, 400, {"Category": ["layer_rows.object"], "Y": ["[Layer Rows]"]}, sort=("[Layer Rows]", "Descending"))
    p.add("tableEx", "Incident log (primary metric rows)", 796, 220, 1104, 400, {"Values": ["dq_incidents.incident", "dq_incidents.arm_id", "dq_incidents.day", "dq_incidents.detail"]})
    p.add("tableEx", "Checks", 20, 636, 1880, 420, {"Values": ["dq_checks.layer", "dq_checks.check_name", "dq_checks.severity", "dq_checks.failed_rows", "dq_checks.total_rows", "dq_checks.passed"]}, sort=("dq_checks.check_id", "Ascending"))
    out.append(p)

    p = Page("p04_catalog", "Experiment Catalog", "Every experiment and arm with its size, length and verdict. Use the slicers to filter")
    p.slicer("Verdict", 20, 90, 300, 66, "arms.verdict")
    p.slicer("Ratio status", 336, 90, 300, 66, "arms.ratio_status")
    p.cards(["Arm Count", "Median Horizon Days", "Median MDE"], y=90, x0=652, h=66, total=1248)
    p.add("tableEx", "Experiments", 20, 172, 760, 884, {"Values": ["experiments.experiment_id", "experiments.arms", "experiments.horizon_days", "experiments.max_arm_n", "experiments.ship_arms", "experiments.stop_arms"]}, sort=("experiments.max_arm_n", "Descending"))
    p.add("tableEx", "Arms", 796, 172, 1104, 884, {"Values": ["arms.arm_id", "arms.verdict", "arms.primary_lift", "arms.primary_low", "arms.primary_high", "arms.mde_rel_80", "arms.horizon_days", "arms.final_n"]}, sort=("arms.primary_lift", "Descending"))
    out.append(p)

    p = Page("p05_srm", "Sample Ratio Health",
             "Chi-square vs 50/50 at the final checkpoint. Arms more than 10 pp off 50/50 are held until the planned split is confirmed")
    p.cards(["SRM Arms", "Allocation Unknown Arms", "Healthy Ratio Share", "Worst Share Gap"], y=90)
    p.add("donutChart", "Arms by ratio status", 20, 220, 600, 400, {"Category": ["srm.ratio_status"], "Y": ["[Arms by Status]"]})
    p.add("scatterChart", "Treatment share vs arm size", 636, 220, 1264, 400, {"Category": ["srm.arm_id"], "X": ["[Arm Users]"], "Y": ["[Arm Treatment Share]"], "Legend": ["srm.ratio_status"]})
    p.add("tableEx", "Flagged arms", 20, 636, 940, 420, {"Values": ["srm.arm_id", "srm.n_c", "srm.n_t", "srm.treatment_share", "srm.srm_p", "srm.ratio_status"]},
          sort=("srm.srm_p", "Ascending"), filters=cat_filter("srm", "ratio_status", ["SRM", "allocation unknown"], "f_srm"))
    p.add("lineChart", "Arm 329386/v1: treatment share drifts below 50% from day one", 976, 636, 924, 420, {"Category": ["srm_trajectory.day"], "Y": ["[Treatment Share]"]},
          filters=cat_filter("srm_trajectory", "arm_id", ["329386/v1"], "f_traj"))
    out.append(p)

    p = Page("p06_peeking", "The Peeking Problem",
             "Null (A/A) paths replayed on each arm's real checkpoint schedule, 3,000 simulations per arm. Any rule above 5% is overstating confidence")
    p.cards(["FPR Fixed", "FPR Naive Peeking", "FPR OBF", "FPR mSPRT", "Naive Wrong Calls"], y=90)
    p.add("clusteredColumnChart", "False positive rate by stopping rule", 20, 220, 760, 836, {"Category": ["null_fpr.rule"], "Y": ["[False Positive Rate]"]}, sort=("null_fpr.rule", "Ascending"))
    p.add("lineChart", "False positive rate vs number of looks (equally spaced)", 796, 220, 1104, 520, {"Category": ["peeking_curve.looks"], "Y": ["[Curve Naive]", "[Curve OBF]", "[Curve mSPRT]"]})
    p.text(796, 756, 1104, 300, [
        ("Reading it", "16pt", True),
        ("Checking a dashboard daily and stopping the first time p < 0.05 turns a 5% error rate into ~19% on these schedules, and it keeps climbing with more looks.", "14pt", False),
        ("O'Brien-Fleming spends almost no alpha early and holds 5%. mSPRT is valid at any look but conservative (~1%), so it is slower to call real effects.", "14pt", False),
    ])
    out.append(p)

    p = Page("p07_checkpoints", "Checkpoint Explorer",
             "Cumulative z-score of the primary metric at every checkpoint against the naive 1.96 line and the O'Brien-Fleming boundary")
    p.add("lineChart", "Arm 036afc/v2: crosses -1.96 on day 5, ends flat (a naive peek kills a null)", 20, 90, 940, 480,
          {"Category": ["checkpoints.day"], "Y": ["[Z]", "[OBF Upper]", "[OBF Lower]", "[Naive Upper]", "[Naive Lower]"]},
          filters={"filters": cat_filter("checkpoints", "arm_id", ["036afc/v2"], "f_a")["filters"] + cat_filter("checkpoints", "metric_name", ["M1 binary"], "f_m")["filters"]})
    p.add("lineChart", "Arm a4386f/v1: real winner, OBF stops on day 11.5 of 89 (the two spikes are one-checkpoint glitches, see DQ)", 976, 90, 924, 480,
          {"Category": ["checkpoints.day"], "Y": ["[Z]", "[OBF Upper]", "[OBF Lower]", "[Naive Upper]", "[Naive Lower]"]},
          filters={"filters": cat_filter("checkpoints", "arm_id", ["a4386f/v1"], "f_b")["filters"] + cat_filter("checkpoints", "metric_name", ["M1 binary"], "f_m2")["filters"]})
    p.add("lineChart", "036afc/v2: cumulative lift with 95% CI", 20, 586, 940, 470,
          {"Category": ["checkpoints.day"], "Y": ["[Lift CI Low]", "[Cumulative Lift]", "[Lift CI High]"]},
          filters={"filters": cat_filter("checkpoints", "arm_id", ["036afc/v2"], "f_c")["filters"] + cat_filter("checkpoints", "metric_name", ["M1 binary"], "f_m3")["filters"]})
    p.add("lineChart", "a4386f/v1: naive p vs always-valid (mSPRT) p", 976, 586, 924, 470,
          {"Category": ["checkpoints.day"], "Y": ["[Naive p]", "[Always-valid p]"]},
          filters={"filters": cat_filter("checkpoints", "arm_id", ["a4386f/v1"], "f_d")["filters"] + cat_filter("checkpoints", "metric_name", ["M1 binary"], "f_m4")["filters"]})
    out.append(p)

    p = Page("p08_sequential", "Sequential Rules Compared",
             "Replaying the real primary-metric paths: when would each rule stop, and does it reach the same answer as running to the end?")
    p.cards(["OBF Median Days Saved", "mSPRT Median Days Saved", "Arm-days Freed by OBF", "Arm-days Run", "OBF Agreement", "mSPRT Agreement"], y=90)
    p.add("tableEx", "Rules on the primary metric (99 arms)", 20, 220, 940, 300, {"Values": ["sequential_summary.rule", "sequential_summary.arms_stopped", "sequential_summary.wrong_calls", "sequential_summary.agrees_with_fixed", "sequential_summary.median_days_saved"]}, sort=("sequential_summary.rule", "Ascending"))
    p.add("scatterChart", "OBF stop day vs full horizon (arms OBF stopped)", 976, 220, 924, 836, {"Category": ["sequential_stops.arm_id"], "X": ["[Avg Horizon Day]"], "Y": ["[Avg OBF Stop Day]"]},
          filters=cat_filter("sequential_stops", "metric_role", ["primary"], "f_p"))
    p.add("clusteredBarChart", "Days saved by OBF per agreeing arm", 20, 536, 940, 520, {"Category": ["sequential_stops.arm_id"], "Y": ["[Days Saved OBF]"]}, sort=("[Days Saved OBF]", "Descending"),
          filters=cat_filter("sequential_stops", "metric_role", ["primary"], "f_p2"))
    out.append(p)

    p = Page("p09_guardrails", "Guardrails & Verdicts",
             "Guardrail rule: lower 95% bound of M2, M3 and M4 must sit above -1%. A breach means the upper bound is below -1%")
    p.slicer("Verdict", 20, 90, 300, 66, "arms.verdict")
    p.cards(["Ship Arms", "Stop Arms", "Inconclusive Arms", "Untrusted Arms", "Arms with Guardrail Breach"], y=90, x0=336, h=110, total=1564)
    p.add("donutChart", "Verdict mix", 20, 220, 600, 400, {"Category": ["verdict_counts.verdict"], "Y": ["[Arms]"]})
    p.add("clusteredBarChart", "Worst guardrail lower bound per arm (below -1% = not proven safe)", 636, 220, 1264, 400, {"Category": ["arms.arm_id"], "Y": ["[Worst Guardrail Low]"]}, sort=("[Worst Guardrail Low]", "Ascending"))
    p.add("tableEx", "Arm verdicts with guardrail detail", 20, 636, 1880, 420, {"Values": ["arms.arm_id", "arms.verdict", "arms.primary_lift", "arms.primary_low", "arms.guardrails_breached", "arms.guardrails_unproven", "arms.worst_guardrail_low", "arms.p_holm"]}, sort=("arms.outcome", "Ascending"))
    out.append(p)

    p = Page("p10_winners", "Winners & Losers",
             "Primary-metric relative lift with 95% CI for every arm that got a SHIP or STOP verdict")
    p.cards(["Ship Arms", "Stop Arms", "Avg Observed Win Lift", "Avg Shrunk Win Lift"], y=90)
    p.add("clusteredBarChart", "Lift with CI: shipped arms", 20, 220, 940, 836, {"Category": ["arms.arm_id"], "Y": ["[Primary CI Low]", "[Primary Lift]", "[Primary CI High]"]}, sort=("[Primary Lift]", "Descending"),
          filters=cat_filter("arms", "verdict", ["SHIP"], "f_w"))
    p.add("clusteredBarChart", "Lift with CI: stopped arms", 976, 220, 924, 836, {"Category": ["arms.arm_id"], "Y": ["[Primary CI Low]", "[Primary Lift]", "[Primary CI High]"]}, sort=("[Primary Lift]", "Ascending"),
          filters=cat_filter("arms", "outcome", ["loss"], "f_l"))
    out.append(p)

    p = Page("p11_winners_curse", "Winner's Curse & Shrinkage",
             "Random-effects (DerSimonian-Laird) estimate of how much true effects vary between experiments, and empirical-Bayes shrunk lifts")
    p.cards(["Tau Primary", "Avg Observed Win Lift", "Avg Shrunk Win Lift", "Shrink Factor"], y=90)
    p.add("scatterChart", "Observed vs shrunk primary lift (noisy arms fall towards the mean)", 20, 220, 1180, 836, {"Category": ["eb_shrinkage.arm_id"], "X": ["[Observed Lift]"], "Y": ["[Shrunk Lift]"]},
          filters=num_filter("eb_shrinkage", "metric_id", 1, "f_e"))
    p.add("tableEx", "Between-experiment heterogeneity", 1216, 220, 684, 300, {"Values": ["heterogeneity.metric_name", "heterogeneity.arms", "heterogeneity.pooled_lift", "heterogeneity.tau", "heterogeneity.i2"]})
    p.add("tableEx", "Biggest shrinkage", 1216, 536, 684, 520, {"Values": ["eb_shrinkage.arm_id", "eb_shrinkage.observed_lift", "eb_shrinkage.eb_lift", "eb_shrinkage.shrink_factor"]}, sort=("eb_shrinkage.abs_shrinkage", "Descending"))
    out.append(p)

    p = Page("p12_segments", "Heterogeneity by Experiment Type",
             "Do outcomes depend on how big, how long or how complex the test was? Rates are shares of arms in each segment")
    p.slicer("Dimension", 20, 90, 300, 66, "verdict_segments.dimension")
    p.add("clusteredColumnChart", "Win and loss rate by segment", 20, 172, 1180, 470, {"Category": ["verdict_segments.segment"], "Y": ["[Win Rate]", "[Loss Rate]"]}, sort=("verdict_segments.segment", "Ascending"))
    p.add("clusteredColumnChart", "Median detectable effect by segment", 1216, 172, 684, 470, {"Category": ["verdict_segments.segment"], "Y": ["[Segment MDE]"]}, sort=("verdict_segments.segment", "Ascending"))
    p.add("tableEx", "Segment table", 20, 658, 1880, 398, {"Values": ["verdict_segments.dimension", "verdict_segments.segment", "verdict_segments.arms", "verdict_segments.win_rate", "verdict_segments.loss_rate", "verdict_segments.flat_rate", "verdict_segments.untrusted_rate", "verdict_segments.median_mde"]}, sort=("verdict_segments.segment", "Ascending"))
    out.append(p)

    p = Page("p13_metrics", "Metric Co-movement & Early Reads",
             "Do the four metrics tell the same story, and how much does a day-3/7/14 read tell you about the final answer?")
    p.cards(["Min Metric Corr", "Day 7 Z Corr", "Day 7 Sign Agreement"], y=90)
    p.add("pivotTable", "Correlation of final z across arms", 20, 220, 760, 360, {"Rows": ["metric_comovement.metric_a_name"], "Columns": ["metric_comovement.metric_b_name"], "Values": ["[Z Correlation]"]},
          objects={"subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}]})
    p.add("tableEx", "Metric sensitivity", 796, 220, 1104, 360, {"Values": ["metric_sensitivity.metric_name", "metric_sensitivity.arms", "metric_sensitivity.share_significant", "metric_sensitivity.share_significant_holm", "metric_sensitivity.median_abs_z", "metric_sensitivity.median_mde_rel"]})
    p.add("lineChart", "Early M1 read vs final M1: correlation and sign agreement", 20, 596, 940, 460, {"Category": ["early_read.read_day"], "Y": ["[Early Z Corr]", "[Early Sign Agreement]", "[Early False Alarm]"]},
          filters={"filters": cat_filter("early_read", "early_metric_name", ["M1"], "f_e1")["filters"] + cat_filter("early_read", "final_metric_name", ["M1"], "f_e2")["filters"]})
    p.add("pivotTable", "Early read z corr (rows: read day, columns: early metric -> final M1)", 976, 596, 924, 460, {"Rows": ["early_read.read_label"], "Columns": ["early_read.early_metric_name"], "Values": ["[Early Z Corr]"]},
          objects={"subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}]},
          filters=cat_filter("early_read", "final_metric_name", ["M1"], "f_e3"))
    out.append(p)

    p = Page("p14_sensitivity", "Decision Sensitivity",
             "Same 99 arms, re-decided under 3 alphas x 5 guardrail margins. Shows which conclusions survive a change of policy")
    p.slicer("Verdict", 20, 90, 400, 66, "decision_sensitivity.verdict")
    p.add("pivotTable", "Arms per verdict (rows: alpha, columns: guardrail margin)", 20, 172, 1880, 330, {"Rows": ["decision_sensitivity.alpha_label"], "Columns": ["decision_sensitivity.margin_label"], "Values": ["[Sensitivity Arms]"]},
          objects={"subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}],
                   "values": [{"properties": {"fontSize": lit("16D")}}], "columnHeaders": [{"properties": {"fontSize": lit("14D")}}],
                   "rowHeaders": [{"properties": {"fontSize": lit("14D")}}]},
          filters=cat_filter("decision_sensitivity", "verdict", ["SHIP"], "f_s"))
    p.add("clusteredColumnChart", "Verdict mix by guardrail margin at alpha 0.05", 20, 518, 1880, 538, {"Category": ["decision_sensitivity.margin_label"], "Series": ["decision_sensitivity.verdict"], "Y": ["[Sensitivity Arms]"]},
          filters=cat_filter("decision_sensitivity", "alpha_label", ["alpha 0.05"], "f_s2"))
    out.append(p)

    p = Page("p15_memo", "Decision Memo", "What the head of experimentation should do next quarter")
    p.text(20, 100, 1880, 956, [
        ("Recommendation: replace daily 1.96 peeking with a pre-registered O'Brien-Fleming plan, gate every readout on SRM, and report shrunk lifts.", "22pt", True),
        ("- Peeking: on the real checkpoint schedules, stopping at the first |z| >= 1.96 has a ~19% false positive rate, not 5%. 20 of 99 primary arms cross 1.96 at some point and the full-horizon answer disagrees.", "18pt", False),
        ("- OBF holds the error at ~5%, calls 24 of the 26 significant arms the same way, and stops a median 25 days early (median test length 44 days). That frees ~750 arm-days of traffic.", "18pt", False),
        ("- mSPRT is always valid (~1% FPR) but only recovers 18 of 26. Use it for continuous monitoring and kill switches, not for the ship call.", "18pt", False),
        ("- Trust: 9 arms (9%) fail SRM with shares like 49.2% on millions of users. That is a bug (assignment, logging, bot filtering), not noise. 3 more arms are far from 50/50 and need their planned split confirmed. Two arms also lost treatment users between checkpoints, and one experiment had an empty checkpoint.", "18pt", False),
        ("- Portfolio: 14 SHIP, 10 STOP (primary harm), 63 inconclusive, 12 untrusted. 1 in 7 wins and 1 in 10 hurts. Short tests (<= 3 weeks) never shipped, and 15% of them were harmful.", "18pt", False),
        ("- Winner's curse: true effects vary by ~0.7% between experiments. Precise wins barely move, noisy ones collapse (e.g. +1.9% -> +0.4%). Forecast with shrunk numbers.", "18pt", False),
        ("- Metrics: final z-scores of the 4 metrics correlate 0.89-0.97. Keep M1 plus one guardrail and review the rare disagreements before dropping the others.", "18pt", False),
        ("- Robustness: across alpha 0.01-0.10 and guardrail margins 0-3%, SHIP ranges from 6 to 17. Above a 1% margin the guardrails stop binding. The peeking and SRM findings do not depend on these settings.", "18pt", False),
        ("Caveat: metrics are anonymised. Calling M1 primary and M2-M4 guardrails is this program's assumed policy, not ASOS's actual practice. Source: ASOS Digital Experiments Dataset (Liu et al. 2021), CC BY 4.0.", "15pt", False),
    ])
    out.append(p)
    return out

VC = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"


def textbox(name, x, y, w, h, paragraphs, z=0):
    paras = []
    for text, size, bold in paragraphs:
        style = {"fontSize": size, "color": "#323130"}
        if bold:
            style["fontWeight"] = "bold"
        paras.append({"textRuns": [{"value": text, "textStyle": style}]})
    return {"$schema": VC, "name": name, "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
            "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paras}}]}}}


def build_report():
    rp = DASH / f"{NAME}.Report"
    d = rp / "definition"
    wjson(rp / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": tag("report")}})
    wjson(rp / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    theme = "plain-light.json"
    wjson(rp / "StaticResources" / "RegisteredResources" / theme, {
        "name": "Plain Light",
        "dataColors": ["#1F4E79", "#9DB9D5", "#E07B39", "#5B8C5A", "#B0B0B0", "#C9A227", "#7A5C99", "#D46A6A"],
        "background": "#FFFFFF", "foreground": "#323130", "tableAccent": "#1F4E79",
        "good": "#5B8C5A", "neutral": "#C9A227", "bad": "#D46A6A",
        "textClasses": {"title": {"fontFace": "Segoe UI", "fontSize": 13, "color": "#323130"},
                        "label": {"fontFace": "Segoe UI", "fontSize": 12, "color": "#605E5C"},
                        "callout": {"fontFace": "Segoe UI", "fontSize": 24, "color": "#1F4E79"}},
        "visualStyles": {"page": {"*": {"background": [{"color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
                                        "outspace": [{"color": {"solid": {"color": "#FFFFFF"}}}]}}}})
    wjson(d / "version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"})
    wjson(d / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.2.0/schema.json",
        "layoutOptimization": "None",
        "themeCollection": {"customTheme": {"name": theme, "reportVersionAtImport": "5.55", "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": theme, "path": theme, "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True}})
    if (d / "pages").exists():
        shutil.rmtree(d / "pages")
    ps = pages()
    wjson(d / "pages" / "pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in ps], "activePageName": ps[0].name})
    for p in ps:
        wjson(d / "pages" / p.name / "page.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.3.0/schema.json",
            "name": p.name, "displayName": p.display, "displayOption": "FitToPage", "height": 1080, "width": 1920,
            "objects": {"background": [{"properties": {"color": {"solid": {"color": lit("'#FFFFFF'")}}, "transparency": lit("0D")}}],
                        "outspace": [{"properties": {"color": {"solid": {"color": lit("'#FFFFFF'")}}}}]}})
        wjson(d / "pages" / p.name / "visuals" / f"{p.name}_title" / "visual.json",
              textbox(f"{p.name}_title", 20, 2, 1880, 86, [(p.display, "20pt", True), (p.subtitle, "12pt", False)]))
        for i, (x, y, w, h, paras) in enumerate(p.texts, 1):
            wjson(d / "pages" / p.name / "visuals" / f"{p.name}_text{i}" / "visual.json",
                  textbox(f"{p.name}_text{i}", x, y, w, h, paras, z=500 + i))
        for i, (vname, x, y, w, h, v, flt) in enumerate(p.visuals, 1):
            body = {"$schema": VC, "name": vname,
                    "position": {"x": x, "y": y, "z": i * 1000, "width": w, "height": h, "tabOrder": i * 1000},
                    "visual": v}
            if flt:
                body["filterConfig"] = flt
            wjson(d / "pages" / p.name / "visuals" / vname / "visual.json", body)


def main():
    with db.connect() as conn:
        build_model(conn)
    build_report()
    wjson(DASH / f"{NAME}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    write(DASH / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    print("wrote", DASH.relative_to(ROOT), "with", len(pages()), "pages and", len(MEASURES), "measures")


if __name__ == "__main__":
    main()
