"""Data files: tables.read_table(). Spreadsheets are built in memory."""

import io
import json
import unittest
import zipfile

import tables

ODS_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')

# Two sheets; only the first is read. Its rows end in the repeated empty cells
# and rows that LibreOffice writes out to the edge of the sheet.
ODS_BODY = """<office:body><office:spreadsheet>
<table:table table:name="One">
  <table:table-row>
    <table:table-cell><text:p>code</text:p></table:table-cell>
    <table:table-cell table:number-columns-repeated="2"/>
    <table:table-cell><text:p>name</text:p></table:table-cell>
  </table:table-row>
  <table:table-row>
    <table:table-cell><text:p>A1</text:p></table:table-cell>
    <table:table-cell table:number-columns-repeated="2"/>
    <table:table-cell>
      <text:p>Two<text:s text:c="2"/>spaces</text:p><text:p>second line</text:p>
      <office:annotation><text:p>a comment</text:p></office:annotation>
    </table:table-cell>
    <table:table-cell table:number-columns-repeated="1020"/>
  </table:table-row>
  <table:table-row table:number-rows-repeated="1048574">
    <table:table-cell table:number-columns-repeated="1024"/>
  </table:table-row>
</table:table>
<table:table table:name="Two">
  <table:table-row><table:table-cell><text:p>other</text:p></table:table-cell></table:table-row>
</table:table>
</office:spreadsheet></office:body>"""

ODS_ROWS = [["code", "", "", "name"], ["A1", "", "", "Two  spaces\nsecond line"]]

X_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

# Cell styles: 0 general, 1 built-in date, 2 zero-padded, 3 custom date and
# time, 4 currency (not applied)
XLSX_STYLES = f"""<styleSheet {X_NS}>
<numFmts>
  <numFmt numFmtId="164" formatCode="00000"/>
  <numFmt numFmtId="165" formatCode="yyyy\\-mm\\-dd hh:mm"/>
  <numFmt numFmtId="166" formatCode="&quot;$&quot;#,##0.00"/>
</numFmts>
<cellXfs><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="165"/><xf numFmtId="166"/></cellXfs>
</styleSheet>"""

XLSX_SHARED = f"""<sst {X_NS}>
<si><t>code</t></si>
<si><r><t>Ri</t></r><r><t>ch</t></r></si>
</sst>"""

XLSX_SHEET = f"""<worksheet {X_NS}><sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>when</t></is></c><c r="C1" t="s"><v>1</v></c></row>
<row r="2"><c r="A2" s="2"><v>42</v></c><c r="B2" s="1"><v>45000</v></c><c r="D2" t="b"><v>1</v></c></row>
<row r="3"><c r="A3"><v>0.30000000000000004</v></c><c r="B3" s="3"><v>45000.5</v></c><c r="C3" s="4"><v>1234.5</v></c></row>
<row r="4"><c r="A4"><v>3</v></c><c r="B4" s="3"><v>0.75</v></c><c r="C4" s="1"/></row>
</sheetData></worksheet>"""

XLSX_ROWS = [
    ["code", "when", "Rich"],
    ["00042", "2023-03-15", "", "TRUE"],
    ["0.3", "2023-03-15 12:00", "1234.5"],
    ["3", "18:00"],
]


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, text in files.items():
            z.writestr(path, text)
    return buf.getvalue()


def ods():
    return zipped({
        "mimetype": "application/vnd.oasis.opendocument.spreadsheet",
        "content.xml": f'<?xml version="1.0" encoding="UTF-8"?>\n'
                       f"<office:document-content {ODS_NS}>{ODS_BODY}</office:document-content>",
    })


def xlsx(sheet=XLSX_SHEET, date1904=False, changes=None):
    """A workbook. `changes` replaces parts by path, or with None leaves them out."""
    files = {
        "xl/workbook.xml": f'<workbook {X_NS} {R_NS}><workbookPr date1904="{int(date1904)}"/>'
                           f'<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels":
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet"/></Relationships>',
        "xl/sharedStrings.xml": XLSX_SHARED,
        "xl/styles.xml": XLSX_STYLES,
        "xl/worksheets/sheet1.xml": sheet,
    }
    files.update(changes or {})
    return zipped({k: v for k, v in files.items() if v is not None})


class Delimited(unittest.TestCase):

    def test_delimiter_is_sniffed(self):
        for sep in ",;\t|":
            with self.subTest(sep=sep):
                raw = f"code{sep}name\nA1{sep}Bolt\n".encode()
                self.assertEqual(tables.read_table("data.csv", raw), [["code", "name"], ["A1", "Bolt"]])

    def test_quoted_cells(self):
        raw = b'code,name\nA1,"Bolt, M3\nzinc"\n'
        self.assertEqual(tables.read_table("data.csv", raw)[1], ["A1", "Bolt, M3\nzinc"])

    def test_utf8_byte_order_mark_is_dropped(self):
        raw = "code,name\nA1,café\n".encode("utf-8-sig")
        self.assertEqual(tables.read_table("data.csv", raw), [["code", "name"], ["A1", "café"]])

    def test_utf16_with_byte_order_mark(self):
        # Excel's "Unicode Text": UTF-16, tab-separated
        text = "code\tname\r\nA1\tcafé\r\n"
        for raw in (b"\xff\xfe" + text.encode("utf-16-le"), b"\xfe\xff" + text.encode("utf-16-be")):
            with self.subTest(mark=raw[:2]):
                self.assertEqual(tables.read_table("data.txt", raw), [["code", "name"], ["A1", "café"]])

    def test_windows_1252_fallback(self):
        raw = "name,price\ncafé,€3\n".encode("cp1252")
        self.assertEqual(tables.read_table("data.csv", raw)[1], ["café", "€3"])


class Json(unittest.TestCase):

    def read(self, data, name="data.json"):
        return tables.read_table(name, json.dumps(data).encode())

    def test_list_of_objects(self):
        rows = self.read([{"code": "A1", "n": 1, "ok": True},
                          {"code": "B2", "extra": None, "nested": {"x": 1}}])
        self.assertEqual(rows, [
            ["code", "n", "ok", "extra", "nested"],
            ["A1", "1", "true", "", ""],
            ["B2", "", "", "", '{"x": 1}'],
        ])

    def test_list_of_lists_inside_an_object(self):
        self.assertEqual(self.read({"rows": [["a", "b"], [1, 2]]}), [["a", "b"], ["1", "2"]])

    def test_detected_without_an_extension(self):
        self.assertEqual(self.read([["a"], ["b"]], name="data"), [["a"], ["b"]])

    def test_refused(self):
        for raw in (b"[1, 2", b'"text"', b"[1, 2]", b'[["a"], {"b": 1}]'):
            with self.subTest(raw=raw), self.assertRaises(tables.TableError):
                tables.read_table("data.json", raw)


class OpenDocument(unittest.TestCase):

    def test_ods(self):
        self.assertEqual(tables.read_table("data.ods", ods()), ODS_ROWS)

    def test_fods(self):
        raw = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document {ODS_NS} '
               f'office:mimetype="application/vnd.oasis.opendocument.spreadsheet">'
               f"{ODS_BODY}</office:document>").encode()
        self.assertEqual(tables.read_table("data.fods", raw), ODS_ROWS)


class Excel(unittest.TestCase):

    def test_xlsx(self):
        self.assertEqual(tables.read_table("data.xlsx", xlsx()), XLSX_ROWS)

    def test_1904_dates(self):
        sheet = f'<worksheet {X_NS}><sheetData><row r="1"><c r="A1" s="1"><v>1</v></c></row></sheetData></worksheet>'
        self.assertEqual(tables.read_table("data.xlsx", xlsx(sheet, date1904=True)), [["1904-01-02"]])


class Refused(unittest.TestCase):

    def assertRefused(self, name, raw):
        with self.assertRaises(tables.TableError) as cm:
            tables.read_table(name, raw)
        return str(cm.exception)

    def test_binary_data(self):
        msg = self.assertRefused("photo.jpg", bytes(range(256)) * 8)
        self.assertIn(".jpg", msg)

    def test_old_excel(self):
        self.assertIn(".xls", self.assertRefused("data.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504)))

    def test_other_zip(self):
        self.assertRefused("data.zip", zipped({"readme.txt": "hello"}))

    def test_damaged_zip(self):
        self.assertIn("damaged", self.assertRefused("data.xlsx", b"PK\x03\x04" + b"junk" * 50))

    def test_damaged_workbooks(self):
        cases = {
            "no relationships": xlsx(changes={"xl/_rels/workbook.xml.rels": None}),
            "sheet not in the relationships": xlsx(changes={"xl/_rels/workbook.xml.rels":
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'}),
            "no sheet": xlsx(changes={"xl/worksheets/sheet1.xml": None}),
            "cut-off sheet": xlsx(sheet=XLSX_SHEET[:200]),
            "missing shared string": xlsx(sheet=f'<worksheet {X_NS}><sheetData><row r="1">'
                                                f'<c r="A1" t="s"><v>9</v></c></row></sheetData></worksheet>'),
            "bad style number": xlsx(changes={"xl/styles.xml": XLSX_STYLES.replace('numFmtId="14"', 'numFmtId="x"')}),
        }
        for case, raw in cases.items():
            with self.subTest(case):
                self.assertEqual(self.assertRefused("data.xlsx", raw), "The file looks damaged")

    def test_damaged_spreadsheet(self):
        raw = zipped({"content.xml": f"<office:document-content {ODS_NS}><office:body>"})
        self.assertEqual(self.assertRefused("data.ods", raw), "The file looks damaged")
