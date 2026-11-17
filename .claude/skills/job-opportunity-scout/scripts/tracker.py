#!/usr/bin/env python3
"""Tracker files data/jobs.csv and data/jobs.xlsx (and the Google Sheet mirror).

Rules
  * Rows are only ever appended, never removed or reordered.
  * "Status" and "Notes" belong to the user. Before writing, edits are read back
    from BOTH files (and from the Google Sheet when a sheet export is given);
    an edited value (Status != "New", or non-empty Notes) always wins over the
    default. If two places hold different edits: sheet > xlsx > csv.

CLI
  python3 scripts/tracker.py merge-sheet sheet_values.json   # pull Status/Notes edits from the Google Sheet
  python3 scripts/tracker.py sheet-rows sheet_values.json    # print rows missing from the sheet (JSON), to append
  python3 scripts/tracker.py show                            # print tracker as a markdown table
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, normalize_url  # noqa: E402

COLUMNS = ["Date found", "Date posted", "Job Title", "Company", "Bucket", "Role type", "Location", "Link", "Fit score",
           "Est. OTE range", "Pay confidence", "Why it fits", "Main risk", "Status", "Notes"]
USER_COLS = ("Status", "Notes")
CSV_PATH = DATA_DIR / "jobs.csv"
XLSX_PATH = DATA_DIR / "jobs.xlsx"
SHEET_NAME = "Job Opportunities - Cédric"


def _key(row) -> str:
    return normalize_url(row.get("Link") or "")


def read_csv(path=CSV_PATH) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [dict(r) for r in csv.DictReader(f)]


def read_xlsx(path=XLSX_PATH) -> list[dict]:
    if not path.exists():
        return []
    from openpyxl import load_workbook

    ws = load_workbook(path, read_only=True, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h or "") for h in rows[0]]
    return [{h: ("" if v is None else str(v)) for h, v in zip(header, r)} for r in rows[1:] if any(r)]


def rows_from_sheet_values(values: list[list]) -> list[dict]:
    """Google Sheets get_values result (list of rows, first = header) -> list of dicts."""
    if not values:
        return []
    header = [str(h) for h in values[0]]
    return [{h: (str(r[i]) if i < len(r) else "") for i, h in enumerate(header)} for r in values[1:] if any(r)]


def _edited(col, val) -> bool:
    val = (val or "").strip()
    return bool(val) and not (col == "Status" and val == "New")


def merge_user_edits(base: list[dict], *sources: list[dict]) -> list[dict]:
    """Apply Status/Notes edits from `sources` (lowest priority first) onto base rows."""
    for src in sources:
        idx = {_key(r): r for r in src}
        for row in base:
            s = idx.get(_key(row))
            if not s:
                continue
            for col in USER_COLS:
                if _edited(col, s.get(col)):
                    row[col] = s[col]
    return base


def load(sheet_rows: list[dict] | None = None) -> list[dict]:
    """Current tracker rows with all user edits merged in. Row order follows the longest file."""
    c, x = read_csv(), read_xlsx()
    base_src = x if len(x) > len(c) else c
    base = [{col: r.get(col, "") for col in COLUMNS} for r in base_src]
    # rows present only in the other file (shouldn't happen, but never lose a row)
    have = {_key(r) for r in base}
    for r in (c if base_src is x else x):
        if _key(r) not in have:
            base.append({col: r.get(col, "") for col in COLUMNS})
            have.add(_key(r))
    return merge_user_edits(base, c, x, sheet_rows or [])


def write(rows: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    tmp.replace(CSV_PATH)

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Jobs"
    ws.append(COLUMNS)
    for r in rows:
        ws.append([_num(r.get(c, "")) if c == "Fit score" else r.get(c, "") for c in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    widths = {"Date found": 12, "Date posted": 12, "Job Title": 38, "Company": 20, "Bucket": 14, "Role type": 20, "Location": 24, "Link": 40,
              "Fit score": 9, "Est. OTE range": 16, "Pay confidence": 14, "Why it fits": 60, "Main risk": 45, "Status": 12, "Notes": 30}
    for i, c in enumerate(COLUMNS, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = widths.get(c, 15)
    link_col = COLUMNS.index("Link") + 1
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column in (COLUMNS.index("Why it fits") + 1, COLUMNS.index("Main risk") + 1))
        lc = row[link_col - 1]
        if lc.value:
            lc.hyperlink = lc.value
            lc.font = Font(color="0563C1", underline="single")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    tmpx = XLSX_PATH.with_suffix(".xlsx.tmp")
    wb.save(tmpx)
    tmpx.replace(XLSX_PATH)


def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v


def append(new_rows: list[dict], sheet_rows: list[dict] | None = None) -> int:
    rows = load(sheet_rows)
    have = {_key(r) for r in rows}
    added = 0
    for r in new_rows:
        if _key(r) in have:
            continue
        row = {c: r.get(c, "") for c in COLUMNS}
        row["Status"] = row["Status"] or "New"
        rows.append(row)
        have.add(_key(row))
        added += 1
    write(rows)
    return added


def _load_sheet_file(p) -> list[dict]:
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("values") or data.get("rows") or []
    if data and isinstance(data[0], dict):
        return data
    return rows_from_sheet_values(data)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "merge-sheet":
        rows = load(_load_sheet_file(argv[1]))
        write(rows)
        print(f"merged Status/Notes from sheet into {len(rows)} tracker rows")
    elif cmd == "sheet-rows":
        sheet = _load_sheet_file(argv[1]) if len(argv) > 1 and Path(argv[1]).exists() else []
        in_sheet = {_key(r) for r in sheet}
        missing = [[r.get(c, "") for c in COLUMNS] for r in load(sheet) if _key(r) not in in_sheet]
        print(json.dumps({"header": COLUMNS, "rows": missing, "sheet_has_header": bool(sheet)}, ensure_ascii=False))
    elif cmd == "show":
        rows = load()
        print("| " + " | ".join(COLUMNS[:9] + ["Status"]) + " |")
        print("|" + "---|" * 10)
        for r in rows:
            print("| " + " | ".join(str(r.get(c, "")).replace("|", "/") for c in COLUMNS[:9] + ["Status"]) + " |")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
