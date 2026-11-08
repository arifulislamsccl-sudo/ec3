"""Export the finished Excel suite into a JSON model for the mobile web app.
Engine data: every non-empty cell of every calculator sheet + Data (constants and formulas).
UI data: layout of each calculator page, grid pages, and the HOME index."""
import json, re, sys
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter, range_boundaries

SRC = sys.argv[1]
OUT = sys.argv[2]
wb = load_workbook(SRC)
GRID_SHEETS = {"Steel Weight", "FMEA", "Insulation BOM"}
SKIP = {"HOME"}

def fill_of(c):
    try:
        if c.fill is not None and c.fill.fill_type == "solid":
            rgb = c.fill.fgColor.rgb
            if isinstance(rgb, str):
                return rgb[-6:].upper()
    except Exception:
        pass
    return None

def merged_map(ws):
    m = {}
    for rng in ws.merged_cells.ranges:
        m[(rng.min_row, rng.min_col)] = (rng.max_row, rng.max_col)
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                if (r, c) != (rng.min_row, rng.min_col):
                    m.setdefault("hidden", set()).add((r, c))
    return m

def dv_map(ws):
    """cell address -> ('list', [options]) | ('formula', formula) | ('num', None)"""
    out = {}
    for dv in ws.data_validations.dataValidation:
        f1 = dv.formula1
        for rng in str(dv.sqref).split():
            mc, mr, xc, xr = range_boundaries(rng)
            origin = f"{get_column_letter(mc)}{mr}"
            for r in range(mr, xr + 1):
                for c in range(mc, xc + 1):
                    addr = f"{get_column_letter(c)}{r}"
                    if dv.type == "list":
                        if f1.startswith('"'):
                            out[addr] = ("list", f1.strip('"').split(","))
                        else:
                            f = Translator("=" + f1.lstrip("="), origin=origin).translate_formula(addr)
                            out[addr] = ("formula", f[1:])
                    elif dv.type in ("decimal", "whole"):
                        out.setdefault(addr, ("num", None))
    return out

def cell_payload(v):
    if isinstance(v, str) and v.startswith("="):
        return {"f": v[1:]}
    if v is None:
        return None
    if isinstance(v, bool):
        return {"v": v}
    if isinstance(v, (int, float)):
        return {"v": v}
    return {"v": str(v)}

model = {"sheets": {}, "pages": {}, "order": [], "index": []}

for ws in wb.worksheets:
    if ws.title in SKIP:
        continue
    cells = {}
    for row in ws.iter_rows():
        for c in row:
            p = cell_payload(c.value)
            if p is not None:
                cells[c.coordinate] = p
    model["sheets"][ws.title] = cells

def text(ws, addr):
    v = ws[addr].value
    return "" if v is None else str(v)

for ws in wb.worksheets:
    name = ws.title
    if name in ("HOME",):
        continue
    if name != "Data":
        model["order"].append(name)
    dvs = dv_map(ws)
    mm = merged_map(ws)
    hidden = mm.get("hidden", set())
    page = {"title": text(ws, "A1") or text(ws, "B1"), "desc": text(ws, "A2") or text(ws, "B2")}
    if name == "Data":
        page["type"] = "data"
        rows = []
        for r in range(1, ws.max_row + 1):
            vals = [ws.cell(r, c).coordinate if ws.cell(r, c).value is not None else None for c in range(1, 14)]
            if any(vals):
                kind = "h" if fill_of(ws.cell(r, 1)) in ("3D85C6",) else ("s" if fill_of(ws.cell(r, 1)) == "CFE2F3" else "d")
                while vals and vals[-1] is None:
                    vals.pop()
                rows.append({"k": kind, "c": vals})
        page["rows"] = rows
        model["pages"][name] = page
        continue
    if name in GRID_SHEETS:
        page["type"] = "grid"
        maxc = ws.max_column
        rows = []
        for r in range(2, ws.max_row + 1):
            row = []
            any_content = False
            for c in range(1, maxc + 1):
                cell = ws.cell(r, c)
                if (r, c) in hidden or cell.hyperlink:
                    row.append(None); continue
                addr = cell.coordinate
                unlocked = cell.protection is not None and cell.protection.locked is False
                fl = fill_of(cell)
                ent = None
                if unlocked:
                    d = dvs.get(addr)
                    ent = {"a": addr, "k": "in"}
                    if d:
                        ent["dv"] = d
                elif cell.value is not None:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        ent = {"a": addr, "k": "f", "nf": cell.number_format}
                    else:
                        ent = {"a": addr, "k": "t"}
                if ent:
                    any_content = True
                    if fl == "3D85C6": ent["h"] = 1
                    elif fl == "D9EAD3": ent["r"] = 1
                    elif fl == "0B5394": ent["T"] = 1
                    if cell.font is not None and cell.font.b: ent["b"] = 1
                    if (r, c) in mm:
                        ent["span"] = mm[(r, c)][1] - c + 1
                row.append(ent)
            if any_content:
                while row and row[-1] is None:
                    row.pop()
                rows.append({"r": r, "c": row})
        page["rows"] = rows
        page["widths"] = [round((ws.column_dimensions[get_column_letter(c)].width or 9)) for c in range(1, maxc + 1)]
        model["pages"][name] = page
        continue
    # calculator page (A label, B value, C unit, D note) + optional side table (H..)
    page["type"] = "calc"
    blocks = []
    for r in range(4, ws.max_row + 1):
        a = ws.cell(r, 1); b = ws.cell(r, 2)
        if a.hyperlink or b.hyperlink:
            continue
        span = mm.get((r, 1))
        if span and span[1] >= 4:
            if a.value is None:
                continue
            if fill_of(a) == "3D85C6":
                blocks.append({"t": "sec", "x": str(a.value)})
            else:
                blocks.append({"t": "note", "x": str(a.value)})
            continue
        if a.value is None and b.value is None:
            continue
        label = "" if a.value is None else str(a.value)
        unit = text(ws, f"C{r}"); note = text(ws, f"D{r}")
        if isinstance(ws[f"D{r}"].value, str) and ws[f"D{r}"].value.startswith("="):
            note = ""
        unlocked = b.protection is not None and b.protection.locked is False
        if unlocked:
            blk = {"t": "in", "l": label, "a": f"B{r}", "u": unit, "n": note}
            d = dvs.get(f"B{r}")
            if d:
                blk["dv"] = d
            blocks.append(blk)
        else:
            blk = {"t": "out", "l": label, "a": f"B{r}", "u": unit, "n": note, "nf": b.number_format}
            if fill_of(b) == "D9EAD3":
                blk["res"] = 1
            if b.font is not None and b.font.sz and b.font.sz >= 16:
                blk["main"] = 1
            if (r, 2) in mm and mm[(r, 2)][1] >= 4:
                blk["wide"] = 1
            blocks.append(blk)
    page["blocks"] = blocks
    # side tables in columns H+
    side_cells = [(c.row, c.column) for row in ws.iter_rows(min_col=8) for c in row if c.value is not None]
    if side_cells:
        minr = min(r for r, _ in side_cells); maxr = max(r for r, _ in side_cells)
        maxc = max(c for _, c in side_cells)
        hdr_row = None
        for r in range(minr, maxr + 1):
            if fill_of(ws.cell(r, 8)) == "3D85C6":
                hdr_row = r; break
        tbl = {"title": text(ws, f"H{hdr_row - 1}") if hdr_row else "", "head": [], "rows": [], "notes": []}
        if hdr_row:
            tbl["head"] = [text(ws, f"{get_column_letter(c)}{hdr_row}") for c in range(8, maxc + 1)]
            ended = False
            for r in range(hdr_row + 1, maxr + 1):
                vals = [ws.cell(r, c) for c in range(8, maxc + 1)]
                if all(v.value is None for v in vals):
                    ended = True; continue
                if ended or (vals[0].value is not None and all(v.value is None for v in vals[1:]) and not str(vals[0].value).startswith("=")):
                    tbl["notes"].append(str(vals[0].value)); continue
                tbl["rows"].append([{"a": v.coordinate, "nf": v.number_format} for v in vals])
        page["table"] = tbl
    model["pages"][name] = page

# HOME index
hm = wb["HOME"]
group = None
for r in range(5, hm.max_row + 1):
    a = hm.cell(r, 1); b = hm.cell(r, 2)
    if a.value and not b.value and (r, 1) in merged_map(hm):
        group = str(a.value).title(); continue
    if b.hyperlink and a.value and group:
        from urllib.parse import unquote; target = unquote(b.hyperlink.location).split("!")[0].strip("'") if b.hyperlink.location else None
        d = hm.cell(r, 4).value
        model["index"].append({"g": group, "code": str(a.value), "title": str(b.value), "desc": str(hm.cell(r, 3).value or ""),
                               "s": target, "d": d[1:] if isinstance(d, str) and d.startswith("=") else None})
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("window.APPDATA=" + json.dumps(model, ensure_ascii=False, separators=(",", ":")) + ";")
print("sheets", len(model["sheets"]), "pages", len(model["pages"]), "index", len(model["index"]))
