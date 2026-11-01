"""Fields: {{name}} tags in a layout, filled from a record.

Names are case-insensitive. Fixed text typed by the user may hold further
tags; data cells are used as written. Text is tidied after empty fields.
"""

import datetime
import re

PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
# Built-in fields, filled when the record has no value of its own: name -> strftime format
BUILTINS = {"date": "%Y-%m-%d", "time": "%H:%M", "datetime": "%Y-%m-%d %H:%M"}


def placeholders(layout):
    """Unique placeholder names used anywhere in the layout, in order.

    Names are case-insensitive: each is listed once, as first spelled.
    """
    seen, keys = [], set()
    for el in layout.get("elements", []):
        for key in ("text", "data"):
            for m in PLACEHOLDER.finditer(str(el.get(key, ""))):
                if m.group(1).lower() not in keys:
                    keys.add(m.group(1).lower())
                    seen.append(m.group(1))
    return seen


def fill(template, record, keep_missing, chain=(), warnings=None):
    """Replace {{Name}} with the record's value, or else a built-in date or time.

    Values of the fields named in `chain` (fixed text typed by the user) may
    themselves contain {{Name}} and are filled in turn. Other values (data
    cells) are used exactly as they are. Empty fields fill as nothing. A
    field that refers back to itself, directly or through others, is reported
    and, with keep_missing (the preview), left as its tag.
    Names are case-insensitive: {{Code}}, {{code}} and {{CODE}} are one field.
    """
    # Later keys win, so the record's fields override same-named data columns
    record = {str(k).lower(): v for k, v in record.items()}
    chain = {str(c).lower() for c in chain}
    now = datetime.datetime.now()
    builtins = {k: now.strftime(f) for k, f in BUILTINS.items()}

    def expand(text, path):
        def sub(m):
            key = m.group(1).lower()
            if key in path:
                if warnings is not None:
                    msg = "Fields refer to each other in a loop: " + " → ".join(
                        "{{%s}}" % k for k in path[path.index(key):] + (key,))
                    if msg not in warnings:
                        warnings.append(msg)
                return m.group(0) if keep_missing else ""
            if key in record and record[key] not in (None, ""):
                v = str(record[key])
                return expand(v, path + (key,)) if key in chain else v
            if key in builtins:
                return builtins[key]
            return ""

        return PLACEHOLDER.sub(sub, text)

    return expand(str(template), ())


EMPTY = "\x00"   # marks where an empty field was, while tidying a line
# Punctuation typed between fields. Beside an empty field, one is dropped so
# none is left doubled or dangling. Brackets and colons aren't separators.
SEPARATORS = "·,;/|-–—"
_SEP = "([%s])?" % re.escape(SEPARATORS)
_AROUND_EMPTY = re.compile(r"( *)%s( *)\x00( *)%s( *)" % (_SEP, _SEP))


def _tidy_empty(m):
    """Replacement for one empty field, the spaces beside it, and a separator.

    "A · _ · B" keeps one separator, "A · _" and "_ · B" lose theirs, and
    "A _ · B" keeps it for B. A separator with nothing before it starts the
    line ("- _ Bolt") and stays.
    """
    ls, lsep, lsp, rsp, rsep, rs = (g or "" for g in m.groups())
    before, after = m.start() > 0, m.end() < len(m.string)
    if lsep and rsep:
        return ls + lsep + rs
    if lsep:
        return "" if before and not after else ls + lsep + lsp
    if rsep:
        return rsp + rsep + rs if before else ""
    return " " if ls and rsp else ""   # a single space stays between words


def fill_text(template, record, keep_missing, chain=(), warnings=None):
    """Fill a text element. Returns (text, hide).

    Tidies up after empty fields: spaces beside one are dropped (a single
    space stays between words on both sides), so is a separator it would
    leave doubled or dangling (see _tidy_empty), and a line that had fields
    but is left blank is removed. Lines typed blank stay. `hide` is true when
    the text has fields and all of them are empty, so fixed text around them
    (a "SKU" label, an inverted bar) isn't drawn on its own.
    """
    has_field = filled = False
    lines = []
    for line in str(template).split("\n"):
        if not PLACEHOLDER.search(line):
            lines.append(line)
            continue
        has_field = True

        def one(m):
            nonlocal filled
            v = fill(m.group(0), record, keep_missing, chain, warnings)
            filled = filled or v != ""
            return v if v != "" else EMPTY

        out = PLACEHOLDER.sub(one, line)
        # One empty field at a time, left to right, so each sees the line as
        # the one before left it: "A · _ · _ · B" becomes "A · B"
        while EMPTY in out:
            out = _AROUND_EMPTY.sub(_tidy_empty, out, count=1)
        if out.strip():
            lines.append(out)
    if has_field and not filled:
        return "", True
    return "\n".join(lines), False

