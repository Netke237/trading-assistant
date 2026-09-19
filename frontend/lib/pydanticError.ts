/** Rendering FastAPI/pydantic validation errors (`detail: [{loc, msg, type}]`)
 *  as something a human can act on.
 *
 *  ONE implementation, deliberately. Two existed: `apiError` in lib/api.ts and
 *  `errorDetail` in lib/portfolioStore.ts, and they disagreed — api.ts prefixed
 *  each message with its field, portfolioStore dropped the field on the grounds
 *  that "these are all single-position posts", which does not follow (a single
 *  position posts several `gt=0` fields, and they fail with identical messages).
 *  The tree therefore rendered the same wire shape two different ways depending
 *  on which call site produced it.
 *
 *  That is the same defect class as the piece this module was written during:
 *  one fact represented in two places, drifting. Hence a shared helper rather
 *  than a copied fix. */

/** FastAPI's `loc[0]` says where the value came from, not which field it was. */
const LOC_FRAMES = ['body', 'query', 'path', 'header', 'cookie'];

/** `["body","entry_price"]` → `"entry_price"`; `["body","targets",0,"price"]` →
 *  `"targets.0.price"`; `["body"]` → `""` (no field to name).
 *
 *  Strips the LEADING frame only. A blanket filter over every segment erases
 *  real field names at depth, and this app has one: `NoteIn` in
 *  backend/app/routers/symbol_notes.py has a field called `body`, so a 422
 *  there carries loc `["body","body"]`. */
export function fieldPathFromLoc(rawLoc: unknown): string {
  if (!Array.isArray(rawLoc)) return '';
  const segments = LOC_FRAMES.includes(String(rawLoc[0])) ? rawLoc.slice(1) : rawLoc;
  return segments.map((seg) => String(seg)).join('.');
}

/** One `detail[]` entry → `"field: message"`, or `"message"` when the entry
 *  names no field, or null when it carries no usable `msg` at all (the caller
 *  then falls back to the raw body rather than inventing text). */
export function validationMessage(entry: unknown): string | null {
  if (!entry || typeof entry !== 'object' || !('msg' in entry)) return null;
  const msg = String((entry as { msg: unknown }).msg);
  if (msg.trim() === '') return null;
  const path = fieldPathFromLoc((entry as { loc?: unknown }).loc);
  return path ? `${path}: ${msg}` : msg;
}

/** A whole `detail[]` → the joined human-readable string, or null when nothing
 *  in it was usable. */
export function validationMessages(detail: readonly unknown[]): string | null {
  const messages = detail
    .map(validationMessage)
    .filter((m): m is string => m != null);
  return messages.length > 0 ? messages.join('; ') : null;
}
