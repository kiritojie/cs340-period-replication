"""Exact, dependency-free charts from the existing frozen RQ1 report.

Only validated formal group statistics are plotted. Missing results and ND
remain labels, never substituted numeric observations. Python 3.6+.
"""
import csv
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

from rq1_integrity import digest, seal_tree, verify_tree

BENCHMARKS = tuple("reorder_%d_bad" % n for n in (3, 4, 5, 10))
MODES = ("parallel", "serial")
METRICS = (
    ("first_error_detected_only", "First error ordinal (detected rounds only)", "paper_first_error", "schedule ordinal"),
    ("total_schedules", "Total schedules", "paper_total_schedules", "schedules"),
    ("error_interleavings", "Error schedules", "paper_error_interleavings", "schedules"),
    ("detection_rate", "Bug detection rate (valid rounds)", None, "percent"),
    ("external_seconds", "External runtime", None, "seconds"),
)


def _number(value, label, optional=False):
    if value is None and optional:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid nonnegative chart value: " + label)
    return value


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError("invalid chart count: " + label)
    return value


def chart_rows(groups):
    """Retain every group and the exact mean/SD/count behind each chart."""
    index = {}
    for group in groups:
        key = (group.get("benchmark"), group.get("mode"))
        if key in index or key[0] not in BENCHMARKS or key[1] not in MODES:
            raise ValueError("duplicate or unsupported chart group: " + str(key))
        index[key] = group
    expected = {(benchmark, mode) for benchmark in BENCHMARKS for mode in MODES}
    if set(index) != expected:
        raise ValueError("charts require the eight explicit frozen report groups")
    rows = []
    for benchmark in BENCHMARKS:
        for mode in MODES:
            group = index[(benchmark, mode)]
            valid, attempted, detected, undetected = [_count(group.get(name), name) for name in (
                "valid", "attempted", "detected", "undetected")]
            if detected + undetected != valid or attempted < valid:
                raise ValueError("chart detection/accounting counts disagree")
            for metric, title, paper_field, unit in METRICS:
                status = "VALID" if valid else ("NOT_RUN" if not attempted else "NO_VALID_RUNS")
                if metric == "first_error_detected_only" and valid and not detected:
                    status = "ND"
                if metric == "detection_rate":
                    mean, sd, count = _number(group.get(metric), metric, optional=True), None, valid
                    if valid and (mean is None or abs(mean - detected / float(valid)) > 1e-12):
                        raise ValueError("chart detection rate differs from valid-round denominator")
                else:
                    mean = _number(group.get(metric + "_mean"), metric + " mean", optional=True)
                    sd = _number(group.get(metric + "_sample_sd"), metric + " SD", optional=True)
                    count = _count(group.get(metric + "_n"), metric + " n")
                    expected_n = detected if metric == "first_error_detected_only" else valid
                    if count != expected_n:
                        raise ValueError("chart metric count differs from eligible rounds")
                    if count > 1 and sd is None:
                        raise ValueError("sample SD is absent for repeated chart observations")
                if status == "VALID" and mean is None:
                    raise ValueError("validated chart observations lack a numeric mean")
                if status != "VALID" and (mean is not None or sd is not None):
                    raise ValueError("missing/ND chart observations must not contain numeric substitutes")
                paper = _number(group.get(paper_field), str(paper_field), optional=True) if paper_field else None
                rows.append({"benchmark": benchmark, "mode": mode, "metric": metric,
                             "ours_status": status, "ours_mean": mean, "ours_sample_sd": sd, "ours_n": count,
                             "paper_status": "VALUE" if paper is not None else "ND" if paper_field else "NOT_REPORTED",
                             "paper_value": paper, "paper_budget_censored": bool(group.get("paper_budget_censored")),
                             "planned_minimum": _count(group.get("planned_minimum"), "planned minimum"),
                             "attempted": attempted, "valid": valid, "detected": detected,
                             "undetected_censored": undetected,
                             "budget_exhausted": _count(group.get("budget_exhausted"), "budget count"), "unit": unit})
    return rows


def _format(value):
    return "%.6g" % value


def _svg(rows, title, unit):
    width, height, left, right, top, gap = 1240, 800, 265, 945, 126, 70
    scale_factor = 100 if unit == "percent" else 1
    values = []
    for row in rows:
        if row["ours_mean"] is not None:
            values.append((row["ours_mean"] + (row["ours_sample_sd"] or 0)) * scale_factor)
        if row["paper_value"] is not None:
            values.append(row["paper_value"] * scale_factor)
    maximum = (max(values) if values else 1) or 1
    maximum = 100 if unit == "percent" else maximum * 1.08
    span = right - left
    chunks = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (width, height, width, height),
              '<rect width="100%" height="100%" fill="#fff"/>',
              '<style>text{font-family:Arial,sans-serif;fill:#182335} .note{font-size:12px;fill:#536276} .axis{font-size:11px;fill:#536276}</style>',
              '<text x="28" y="38" font-size="24" font-weight="bold">%s</text>' % escape(title),
              '<text x="28" y="65" class="note">Ours: mean with sample SD where defined; explicit formal rounds only</text>',
              '<rect x="28" y="82" width="18" height="12" rx="2" fill="#1b7097"/><text x="54" y="93" class="note">Ours</text>',
              '<rect x="115" y="82" width="18" height="12" rx="2" fill="#aeb8c4"/><text x="141" y="93" class="note">Paper reference (no paper SD supplied)</text>']
    for tick in range(6):
        value = maximum * tick / 5.0
        x = left + span * tick / 5.0
        chunks.append('<line x1="%.2f" y1="112" x2="%.2f" y2="695" stroke="#e4e9ef"/>' % (x, x))
        chunks.append('<text x="%.2f" y="715" text-anchor="middle" class="axis">%s</text>' % (x, _format(value)))
    for index, row in enumerate(rows):
        y = top + index * gap
        label = row["benchmark"].replace("_bad", "") + " / " + row["mode"].title()
        chunks.append('<text x="28" y="%d" font-size="14" font-weight="bold">%s</text>' % (y + 15, escape(label)))
        chunks.append('<text x="28" y="%d" class="note">valid %d/%d; detected %d; censored %d</text>' % (
            y + 34, row["valid"], row["planned_minimum"], row["detected"], row["undetected_censored"]))
        for ours, offset in ((True, 0), (False, 25)):
            value = row["ours_mean"] if ours else row["paper_value"]
            status = row["ours_status"] if ours else row["paper_status"]
            yy = y + offset
            if value is None:
                label = "ND (censored)" if status == "ND" else status.replace("_", " ")
                chunks.append('<text x="%d" y="%d" class="note" data-status="%s">%s</text>' % (
                    left + 5, yy + 15, status, escape(label)))
                continue
            amount = value * scale_factor
            bar_width = span * amount / maximum
            color = "#1b7097" if ours else "#aeb8c4"
            chunks.append('<rect class="%s-bar" data-status="%s" data-value="%s" x="%d" y="%d" width="%.4f" height="17" rx="2" fill="%s"/>' % (
                "ours" if ours else "paper", status, str(value), left, yy, bar_width, color))
            numeric = _format(amount)
            if ours and row["ours_sample_sd"] is not None:
                sd = row["ours_sample_sd"] * scale_factor
                a = left + span * max(0, amount - sd) / maximum
                b = left + span * (amount + sd) / maximum
                chunks.append('<path d="M %.3f %d H %.3f M %.3f %d V %d M %.3f %d V %d" fill="none" stroke="#17324d" stroke-width="1.5"/>' % (
                    a, yy + 8, b, a, yy + 3, yy + 13, b, yy + 3, yy + 13))
                numeric += " +/- " + _format(sd)
            if ours:
                numeric += " (n=%d)" % row["ours_n"]
            elif row["paper_budget_censored"] and row["metric"] == "total_schedules":
                numeric += " (budget)"
            chunks.append('<text x="%.2f" y="%d" class="note">%s</text>' % (
                max(left + 5, min(right + 15, left + bar_width + 8)), yy + 14, escape(numeric)))
    chunks += ['<text x="%d" y="744" text-anchor="middle" class="note">%s; linear scale</text>' % ((left + right) // 2, escape(unit)),
               '<text x="28" y="773" class="note">ND is not 10000 or zero. First-error means are conditional on detection; valid zero error counts remain zero.</text>',
               '</svg>']
    return "\n".join(chunks) + "\n"


def write_charts(statistics_dir, output_newdir):
    statistics_dir, output = Path(statistics_dir).resolve(), Path(output_newdir).resolve()
    source_verification = verify_tree(statistics_dir)
    summary_path = statistics_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("schema") != "cs340-period-rq1-report-v1":
        raise ValueError("unsupported chart statistics schema")
    rows = chart_rows(summary.get("groups", []))
    output.mkdir(parents=True, exist_ok=False)
    with (output / "chart-data.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for metric, title, unused, unit in METRICS:
        with (output / (metric + ".svg")).open("x", encoding="utf-8") as stream:
            stream.write(_svg([row for row in rows if row["metric"] == metric], title, unit))
    record = {"schema": "cs340-period-rq1-charts-v1", "statistics_summary_sha256": digest(summary_path),
              "protocol_sha256": summary.get("protocol_sha256"), "formal_valid_rounds": summary.get("valid_formal_rounds"),
              "source_verification": source_verification, "chart_count": len(METRICS),
              "statistics_rule": "mean with sample SD; first-error among detected valid rounds only; ND remains categorical"}
    with (output / "chart-summary.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    text = ["# RQ1 comparison charts", "", "The CSV contains the exact source values; SVG labels are rounded for readability.", "",
            "Missing runs, invalid-only groups and ND are separate labels. They are never inserted as numeric zero or 10000.",
            "Paper references come from the existing frozen report; paper SD, detection rate and runtime are not invented.",
            "External runtime includes local profiling and supervision overhead; it is not a direct paper timing comparison.", ""]
    for metric, title, unused, unit in METRICS:
        text += ["## " + title, "", "![%s](%s.svg)" % (title, metric), ""]
    with (output / "README.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(text))
    seal_tree(output)
    verify_tree(output)
    return record
