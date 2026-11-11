// Fields: the {{names}} in a layout, and the values that fill them. Each
// function takes the editor's state `s` (S in app.mjs) and reads from it:
//   s.placeholders  the layout's field names, from the last preview
//   s.fixed         field key -> fixed text
//   s.data          the loaded data file, {headers, rows}, or null
//   s.mapping       field key -> column name ("" = fixed text)
//   s.meta          /api/meta: field_pattern and builtin_fields are the
//                   server's own, so fields are found here exactly as it fills them

export const tags = (text, pattern) => text.matchAll(new RegExp(pattern, "g"));

// Field names are case-insensitive: {{Code}} and {{code}} are one field.
// Values and column choices are stored under the lowercase key; the Data
// table shows the name as first spelled in the layout.
export const fkey = (p) => p.toLowerCase();

// Re-key a {name: value} object by lowercase name (older templates and saved
// state used the spelling). Where two spellings collide, the first value set wins.
export function lowerKeys(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj && typeof obj === "object" ? obj : {})) {
    const key = fkey(k);
    if (!(key in out) || (out[key] === "" && v !== "")) out[key] = v;
  }
  return out;
}

// A field takes fixed text unless data is loaded and it's mapped to a column
export const isFixed = (s, p) => !(s.data && s.mapping[fkey(p)]);

// The layout's fields, plus any field named inside a fixed value, so that
// {{code}} = "{{item}}" gives Item a row even when the layout doesn't use it.
// Data column names are left out: those come straight from the row.
export function fields(s) {
  const out = [...s.placeholders], keys = new Set(out.map(fkey));
  const cols = new Set((s.data?.headers || []).map(fkey));
  for (let i = 0; i < out.length; i++) {
    if (!isFixed(s, out[i])) continue;
    for (const m of tags(s.fixed[fkey(out[i])] || "", s.meta.field_pattern)) {
      const k = fkey(m[1]);
      if (!keys.has(k) && !s.meta.builtin_fields.includes(k) && !cols.has(k)) { keys.add(k); out.push(m[1]); }
    }
  }
  return out;
}

// Fields whose fixed values may themselves contain {{tags}} (sent as "chain")
export const chain = (s) => fields(s).filter((p) => isFixed(s, p));

// Build the field->value record for one data row (or fixed values only). The
// row's own columns go in first, so a fixed value can refer to any column.
export function record(s, row) {
  const rec = row ? { ...row } : {};
  for (const p of fields(s)) {
    rec[p] = isFixed(s, p) ? (s.fixed[fkey(p)] ?? "") : (row?.[s.mapping[fkey(p)]] ?? "");
  }
  return rec;
}

// Give each field without a column choice the column of the same name, if
// the data has one. A choice already made stays, unless its column is gone.
export function autoMap(s) {
  if (!s.data) return;
  for (const p of fields(s)) {
    const m = s.mapping[fkey(p)];
    if (m !== undefined && (m === "" || s.data.headers.includes(m))) continue;
    const hit = s.data.headers.find((c) => fkey(c) === fkey(p));
    s.mapping[fkey(p)] = hit || "";
  }
}
