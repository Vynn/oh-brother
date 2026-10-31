"""Read a data file into rows of strings, using only the standard library.

Supported: delimited text (CSV, TSV, semicolon or pipe), OpenDocument
spreadsheets (.ods, flat .fods), Excel workbooks (.xlsx) and JSON. Spreadsheets
give the first sheet. Anything else raises TableError with a message for the user.
"""

import csv
import datetime
import io
import json
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

MAX_XML = 64 * 1024 * 1024   # largest unpacked sheet we'll parse

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def q(tag):
    """'table:table-row' -> '{urn:…}table-row' for ElementTree."""
    p, name = tag.split(":")
    return "{%s}%s" % (NS[p], name)


class TableError(ValueError):
    """A file that can't be read, with a message for the user."""


# What a file that isn't what it claims to be raises in the zip, XML and
# number handling below: a missing part, a bad index, a value that isn't a number
DAMAGED = (zipfile.BadZipFile, zlib.error, EOFError, ET.ParseError,
           KeyError, IndexError, StopIteration, ValueError)


def read_table(name, raw):
    """Rows (lists of strings) from an uploaded file's name and bytes."""
    try:
        return _read(name, raw)
    except TableError:
        raise
    except DAMAGED:
        raise TableError("The file looks damaged") from None


def _read(name, raw):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if raw[:4] == b"PK\x03\x04":
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = set(z.namelist())
        if "content.xml" in names:
            return _ods_rows(ET.fromstring(_member(z, "content.xml")))
        if "xl/workbook.xml" in names:
            return _xlsx_rows(z)
        raise TableError(_unsupported(ext))
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise TableError("Old Excel files (.xls) aren't supported. Save it as .xlsx, .ods or CSV.")
    text = _decode(raw)
    head = text[:8192]
    if sum(c < " " and c not in "\t\n\r\f" for c in head) > len(head) // 100:
        raise TableError(_unsupported(ext))
    stripped = text.lstrip()
    if ext == "fods" or (stripped.startswith("<?xml") and "opendocument" in stripped[:2000]):
        return _ods_rows(ET.fromstring(raw))
    if ext == "json" or (stripped[:1] in ("[", "{") and ext not in ("csv", "tsv", "txt")):
        return _json_rows(text)
    return _delimited_rows(text)


def _unsupported(ext):
    kind = f"This .{ext} file" if ext else "This file"
    return f"{kind} isn't text or a supported spreadsheet. Use CSV, TSV, .ods, .xlsx or JSON."


def _member(z, path):
    if z.getinfo(path).file_size > MAX_XML:
        raise TableError("The sheet is too large")
    return z.read(path)


def _decode(raw):
    # UTF-16 only with a byte-order mark, as Excel's "Unicode Text" writes it.
    # Without one it can't be told from other bytes reliably.
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")   # reads and drops the mark
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")   # never fails


# ---- delimited text --------------------------------------------------------

def _delimited_rows(text):
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


# ---- JSON: a list of objects, or a list of lists with headers first ---------

def _json_rows(text):
    try:
        data = json.loads(text)
    except ValueError as e:
        raise TableError(f"The JSON can't be read: {e}")
    if isinstance(data, dict):   # {"rows": [...]}: take the first list inside
        data = next((v for v in data.values() if isinstance(v, list)), None)
    if not isinstance(data, list):
        raise TableError("The JSON needs a list of rows")

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    if all(isinstance(r, list) for r in data):
        return [[cell(v) for v in r] for r in data]
    if all(isinstance(r, dict) for r in data):
        headers = []
        for r in data:
            headers += [k for k in r if k not in headers]
        return [headers] + [[cell(r.get(h)) for h in headers] for r in data]
    raise TableError("The JSON rows must all be objects, or all be lists")


# ---- OpenDocument (.ods, .fods) ----------------------------------------------
# Cells give their displayed text, so numbers, dates and currency appear as
# formatted in the sheet.

def _odf_text(el):
    out = [el.text or ""]
    for ch in el:
        if ch.tag == q("text:s"):
            out.append(" " * int(ch.get(q("text:c"), 1)))
        elif ch.tag == q("text:tab"):
            out.append("\t")
        elif ch.tag == q("text:line-break"):
            out.append("\n")
        elif ch.tag != q("office:annotation"):
            out.append(_odf_text(ch))
        out.append(ch.tail or "")
    return "".join(out)


def _ods_rows(root):
    sheet = root.find(".//" + q("table:table"))
    if sheet is None:
        raise TableError("The spreadsheet has no sheets")
    rows = []
    # Rows may sit inside header-row or row-group wrappers
    for row in sheet.iter(q("table:table-row")):
        cells, gap = [], 0
        for c in row:
            if c.tag not in (q("table:table-cell"), q("table:covered-table-cell")):
                continue
            n = int(c.get(q("table:number-columns-repeated"), 1))
            v = "\n".join(_odf_text(p) for p in c.findall(q("text:p")))
            if not v:
                gap += n   # empty cells only count once something follows them
                continue
            cells += [""] * gap + [v] * min(n, 1000)
            gap = 0
        if cells:
            rows.append(cells)   # empty rows (often repeated a million times) are dropped
    return rows


# ---- Excel (.xlsx) -----------------------------------------------------------
# Cells hold raw values. Numbers are shown in general form, dates as
# YYYY-MM-DD (with HH:MM when there's a time), and zero-padded number formats
# such as 00000 keep their zeros. Other formatting (currency, %) isn't applied.

BUILTIN_DATE_FMTS = set(range(14, 23)) | {45, 46, 47}


def _xlsx_rows(z):
    wb = ET.fromstring(_member(z, "xl/workbook.xml"))
    first = wb.find(f"{q('x:sheets')}/{q('x:sheet')}")
    if first is None:
        raise TableError("The workbook has no sheets")
    rels = ET.fromstring(_member(z, "xl/_rels/workbook.xml.rels"))
    rid = first.get(q("r:id"))
    target = next(r.get("Target") for r in rels.iter(q("rel:Relationship")) if r.get("Id") == rid)
    path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
    pr = wb.find(q("x:workbookPr"))
    epoch = datetime.datetime(1904, 1, 1) if pr is not None and pr.get("date1904") in ("1", "true") \
        else datetime.datetime(1899, 12, 30)

    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(_member(z, "xl/sharedStrings.xml")).iter(q("x:si")):
            # Plain text (<t>) or rich-text runs (<r><t>); phonetic hints (<rPh>) are skipped
            runs = si.findall(q("x:t")) + si.findall(f"{q('x:r')}/{q('x:t')}")
            shared.append("".join(t.text or "" for t in runs))

    styles = _xlsx_styles(z)

    rows = []
    for row in ET.fromstring(_member(z, path)).iter(q("x:row")):
        cells = {}
        for i, c in enumerate(row.iter(q("x:c"))):
            ref = c.get("r")
            col = _col_index(ref) if ref else i
            t, v = c.get("t", "n"), c.find(q("x:v"))
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(q("x:t")))
            elif v is None or v.text is None:
                continue
            elif t == "s":
                val = shared[int(v.text)]
            elif t == "b":
                val = "TRUE" if v.text == "1" else "FALSE"
            elif t in ("str", "e"):
                val = v.text
            else:
                val = _xlsx_number(v.text, styles.get(int(c.get("s", 0))), epoch)
            if val != "":
                cells[col] = val
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def _xlsx_styles(z):
    """Style index -> ("date", None) or ("pad", width) for formats we apply."""
    if "xl/styles.xml" not in z.namelist():
        return {}
    st = ET.fromstring(_member(z, "xl/styles.xml"))
    custom = {int(f.get("numFmtId")): f.get("formatCode", "") for f in st.iter(q("x:numFmt"))}
    out = {}
    xfs = st.find(q("x:cellXfs"))
    for i, xf in enumerate(xfs if xfs is not None else []):
        fid = int(xf.get("numFmtId", 0))
        code = custom.get(fid, "")
        bare = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code)   # drop literals and [colour]/[locale] parts
        if fid in BUILTIN_DATE_FMTS or (fid in custom and re.search(r"[dmyhs]", bare, re.I)):
            out[i] = ("date", None)
        elif re.fullmatch(r"0+", bare):
            out[i] = ("pad", len(bare))
    return out


def _xlsx_number(text, style, epoch):
    try:
        n = float(text)
    except ValueError:
        return text
    if style and style[0] == "date":
        try:
            d = epoch + datetime.timedelta(days=n)
        except OverflowError:
            return text
        d = d.replace(microsecond=0) + datetime.timedelta(seconds=round(d.microsecond / 1e6))
        if n < 1:   # time only
            return d.strftime("%H:%M")
        return d.strftime("%Y-%m-%d") if n == int(n) else d.strftime("%Y-%m-%d %H:%M")
    if style and style[0] == "pad" and n == int(n):
        return str(int(n)).zfill(style[1])
    s = format(n, ".15g")   # Excel shows at most 15 significant digits
    return s[:-2] if s.endswith(".0") else s


def _col_index(ref):
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1
