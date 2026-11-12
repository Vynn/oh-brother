"""The printer's status: its state, the loaded tape and any error, read over SNMP.

A QL-820NWB says nothing back on port 9100, where jobs go, but it answers SNMP
(v2c, community "public"). Brother's own table there holds the same 32-byte
status block the printer sends over USB in reply to ESC i S, which brother_ql
describes. Its display text is in the standard Printer-MIB. Both were read
from a real QL-820NWB with the cover open and shut, and with continuous,
die-cut and no tape loaded (docs/development.md, "Printer status").

A printer that doesn't answer within the time limit has no status, and the
app goes on as before: it only knows whether port 9100 accepts a connection.

SNMP is encoded and decoded here by hand, with the standard library: a GET
needs only a few bytes, and no package would be smaller than this file.
"""

import secrets
import socket

from brother_ql.reader import RESP_MEDIA_TYPES

import tapes

SNMP_PORT = 161
COMMUNITY = b"public"   # the printer's default, and only read access
TIMEOUT_S = 1.0

STATUS_OID = "1.3.6.1.4.1.2435.3.3.9.1.6.1.0"   # Brother: the 32-byte status block
DISPLAY_OID = "1.3.6.1.2.1.43.16.5.1.2.1.1"     # Printer-MIB: the display's first line

# The status block's error bits, in plain words for the editor. Byte 8 is
# brother_ql's "error information 1", byte 9 its "error information 2"; its
# names are in the comments. Bits a QL-8xx doesn't use are left out.
ERRORS = {
    (8, 0): "No tape",                    # No media when printing
    (8, 1): "The labels have run out",    # End of media (die-cut size only)
    (8, 2): "The cutter is jammed",       # Tape cutter jam
    (8, 5): "The printer is turned off",  # Printer turned off
    (9, 0): "Wrong tape for this job",    # Replace media error
    (9, 1): "The printer's memory is full",  # Expansion buffer full error
    (9, 2): "Transmission error",         # Transmission / Communication error
    (9, 4): "Cover open",                 # Cover opened while printing
    (9, 5): "The printer is overheating",  # Cancel key (not used) or Overheating error
    (9, 6): "The tape can't be fed",      # Media cannot be fed
    (9, 7): "Printer error",              # System error
}
CONTINUOUS, DIE_CUT = {0x0A, 0x4A}, {0x0B, 0x4B}


class SnmpError(ValueError):
    """An answer that isn't a well-formed SNMP reply to our request."""


# ---- SNMP, by hand -----------------------------------------------------------

def _tlv(tag, body):
    n = len(body)
    size = bytes([n]) if n < 0x80 else bytes([0x80 | 2]) + n.to_bytes(2, "big")
    return bytes([tag]) + size + body


def _int(v):
    return _tlv(0x02, v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid):
    arcs = [int(a) for a in oid.split(".")]
    out = bytearray([40 * arcs[0] + arcs[1]])
    for a in arcs[2:]:
        chunk = [a & 0x7F]
        a >>= 7
        while a:
            chunk.append(0x80 | (a & 0x7F))
            a >>= 7
        out += bytes(reversed(chunk))
    return _tlv(0x06, bytes(out))


def get_request(oids, request_id, community=COMMUNITY):
    """An SNMP v2c GET for the given OIDs, as bytes."""
    binds = b"".join(_tlv(0x30, _oid(o) + b"\x05\x00") for o in oids)
    pdu = _tlv(0xA0, _int(request_id) + _int(0) + _int(0) + _tlv(0x30, binds))
    return _tlv(0x30, _int(1) + _tlv(0x04, community) + pdu)   # version 1 is v2c


def _parse(data, i):
    """The TLV at i: (tag, body, index after it). Raises SnmpError past the end."""
    if i + 2 > len(data):
        raise SnmpError("cut short")
    tag, n, i = data[i], data[i + 1], i + 2
    if n & 0x80:
        k = n & 0x7F
        if not 1 <= k <= 4 or i + k > len(data):
            raise SnmpError("bad length")
        n, i = int.from_bytes(data[i:i + k], "big"), i + k
    if i + n > len(data):
        raise SnmpError("cut short")
    return tag, data[i:i + n], i + n


def _items(body):
    out, i = [], 0
    while i < len(body):
        tag, b, i = _parse(body, i)
        out.append((tag, b))
    return out


def parse_response(data, request_id):
    """The values of a GET reply, in order: bytes for each value, None where
    the printer has nothing. Raises SnmpError for anything else."""
    tag, msg, _ = _parse(data, 0)
    parts = _items(msg) if tag == 0x30 else []
    if len(parts) != 3 or parts[2][0] != 0xA2:   # version, community, GetResponse
        raise SnmpError("not a reply")
    fields = _items(parts[2][1])
    if len(fields) != 4 or int.from_bytes(fields[0][1], "big", signed=True) != request_id:
        raise SnmpError("not a reply to this request")
    if int.from_bytes(fields[1][1], "big"):
        raise SnmpError(f"error status {int.from_bytes(fields[1][1], 'big')}")
    values = []
    for _, bind in _items(fields[3][1]):
        pair = _items(bind)
        if len(pair) != 2:
            raise SnmpError("bad value")
        vtag, value = pair[1]
        values.append(value if vtag == 0x04 else None)   # 0x80-0x82: no such object or instance
    return values


def snmp_get(host, oids, port=None, timeout=TIMEOUT_S):
    """The values of `oids` on `host`, or None if it doesn't answer in time."""
    request_id = secrets.randbelow(1 << 30)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, SNMP_PORT if port is None else port))   # replies from elsewhere are dropped
            s.send(get_request(oids, request_id))
            return parse_response(s.recv(4096), request_id)
        except (OSError, SnmpError):   # no answer, refused, or an answer we can't use
            return None


# ---- the status block --------------------------------------------------------

def decode(block, display=""):
    """The printer's status from its 32-byte status block, or None if it isn't one.

    state: "ready", "printing" or "error"; errors: plain words; tape: what's
    loaded, None when nothing is, with the ids of the tapes in tapes.py it
    could be (`matches`).
    """
    if not block or len(block) < 32 or block[:3] != b"\x80\x20\x42":
        return None
    errors = [msg for (byte, bit), msg in ERRORS.items() if block[byte] & (1 << bit)]
    media, width, length = block[11], block[10], block[17]
    tape = None
    if media:
        kind = "continuous" if media in CONTINUOUS else "die-cut" if media in DIE_CUT else "other"
        # Byte 25: 0x81 with black-and-red DK-2251 loaded, 0x01 with a black-only
        # roll. Taken to mean two-colour tape; seen on one printer only.
        two_colour = bool(block[25] & 0x80)
        tape = {"kind": kind, "width_mm": width, "length_mm": length, "two_colour": two_colour,
                "name": RESP_MEDIA_TYPES.get(media, "Unknown tape"),
                "matches": matching_tapes(kind, width, length, two_colour)}
    if errors or block[18] == 0x02:   # status type 2: an error occurred
        state = "error"
        errors = errors or ["Printer error"]
    elif block[19] == 0x01:   # phase: printing
        state = "printing"
    else:
        state = "ready"
    return {"state": state, "errors": errors, "tape": tape, "display": display.strip()}


def matching_tapes(kind, width, length, two_colour):
    """Ids of the tapes in tapes.py that a loaded roll could be.

    The printer gives whole millimetres, and brother_ql's sizes are Brother's
    nominal ones, which are a millimetre out for a few labels (39 × 90 mm is
    38 × 90 in its table, 60 × 86 is 60 × 87). An exact match wins; failing
    that, anything within a millimetre.
    """
    if kind == "other":
        return []
    found = {}   # how far out -> ids
    for t in tapes.tape_list():
        w, h = t["tape_mm"]
        if t["endless"]:
            if kind != "continuous" or t["red"] != two_colour or abs(w - width) > 1:
                continue
            off = abs(w - width)
        else:
            if kind != "die-cut" or abs(w - width) > 1 or abs(h - length) > 1:
                continue
            off = abs(w - width) + abs(h - length)
        found.setdefault(off, []).append(t["id"])
    return found[min(found)] if found else []


def fits(layout_tape, status):
    """None if a layout for `layout_tape` can go to the printer as it is, or
    the reason it can't, in words: an error, no tape, or another tape loaded."""
    if status is None:
        return None   # nothing known: print as before
    if status["errors"]:
        return status["errors"][0]
    if status["tape"] is None:
        return "No tape"
    other = mismatch(layout_tape, status)
    if other is None:
        return None
    wanted = f"; this layout is for {other['wanted']}" if other["wanted"] else ""
    return f"The printer has {other['loaded']} loaded{wanted}"


def mismatch(layout_tape, status):
    """{"loaded", "wanted"} in words if the printer has a tape loaded that a
    layout for `layout_tape` doesn't suit, else None. The editor shows it in
    the print bar; fits() puts it in a sentence."""
    tape = status and status["tape"]
    if not layout_tape or not tape or not tape["matches"] or layout_tape in tape["matches"]:
        return None   # no layout tape given, no tape, a tape the app doesn't know, or the right one
    # Black on two-colour tape prints, as black only
    if layout_tape == "62" and "62red" in tape["matches"]:
        return None
    names = {t["id"]: t["name"] for t in tapes.tape_list()}
    return {"loaded": describe_tape(tape), "wanted": names.get(layout_tape, "")}


def describe_tape(tape):
    """The loaded tape in words: "62 mm black/red continuous tape"."""
    if tape["kind"] == "continuous":
        return f"{tape['width_mm']} mm {'black/red ' if tape['two_colour'] else ''}continuous tape"
    if tape["kind"] == "die-cut":
        return f"{tape['width_mm']} × {tape['length_mm']} mm labels"
    return tape["name"].lower()


def summary(status):
    """The status in a few words, for the printer chip and the Test button."""
    if status["state"] == "error":
        return "; ".join(status["errors"])
    if status["state"] == "printing":
        return "Printing"
    return "Ready · " + (describe_tape(status["tape"]) if status["tape"] else "no tape")


def read(host, port=None, timeout=TIMEOUT_S):
    """The printer's status (see decode()), or None if it doesn't give one."""
    values = snmp_get(host, [STATUS_OID, DISPLAY_OID], port=port, timeout=timeout)
    if not values:
        return None
    display = (values[1] or b"").decode("ascii", "replace") if len(values) > 1 else ""
    return decode(values[0], display)
