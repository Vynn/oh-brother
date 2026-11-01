"""Tapes: the labels brother_ql knows, as the editor lists them, and the
size of the canvas a layout is drawn on. 300 dpi throughout."""

from brother_ql.labels import ALL_LABELS, FormFactor

DPI = 300
DPMM = DPI / 25.4


def tape_list(model="QL-820NWB"):
    """Labels usable on the given model (P-touch tapes excluded)."""
    out = []
    for lbl in ALL_LABELS:
        if lbl.form_factor == FormFactor.PTOUCH_ENDLESS:
            continue
        if lbl.restricted_to_models and model not in lbl.restricted_to_models:
            continue
        endless = lbl.form_factor == FormFactor.ENDLESS
        w, h = lbl.tape_size
        if endless:
            name = f"{w} mm continuous" + (" · black/red" if lbl.color else "")
        elif lbl.form_factor == FormFactor.ROUND_DIE_CUT:
            name = f"{w} mm round die-cut"
        else:
            name = f"{w} × {h} mm die-cut"
        out.append({
            "id": lbl.identifier,
            "name": name,
            "endless": endless,
            "red": bool(lbl.color),
            "round": lbl.form_factor == FormFactor.ROUND_DIE_CUT,
            "dots": list(lbl.dots_printable),
            "printable_mm": [round(d / DPMM, 1) for d in lbl.dots_printable],
            # Physical (cut) size; height 0 = continuous. The printer feeds
            # feed_mm of blank tape before and after a continuous label.
            "tape_mm": list(lbl.tape_size),
            "feed_mm": round(lbl.feed_margin / DPMM, 2) if endless else 0,
        })
    # Two-colour tape first, then continuous, then die-cut
    out.sort(key=lambda t: (not t["red"], not t["endless"], t["dots"][0], t["dots"][1]))
    return out


def label(tape_id):
    """brother_ql's label for a tape id, such as "62red" or "29x90"."""
    for lbl in ALL_LABELS:
        if lbl.identifier == tape_id:
            return lbl
    raise ValueError(f"unknown tape: {tape_id}")


def canvas_dots(layout):
    """Canvas size in dots as designed (before any print rotation)."""
    lbl = label(layout.get("tape", "62red"))
    w, h = lbl.dots_printable
    if lbl.form_factor == FormFactor.ENDLESS:
        h = max(1, round(float(layout.get("length_mm", 50)) * DPMM))
    if layout.get("orientation") == "landscape":
        w, h = h, w
    return w, h

