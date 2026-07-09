# Working in this repo

This folder contains **real, sensitive bank statements**. Treat every statement
PDF and every derived export (CSV/XLSX) as confidential.

## Never read an unredacted PDF

Do **not** open, `Read`, `cat`, `pdfplumber.extract_text`, or in any other way
pull the *contents* of a non-redacted PDF into the conversation. This applies to
**any** PDF whose filename does not contain `redacted` — originals
(`boi_statement_*.pdf`), `*_unlocked.pdf`, or anything new — regardless of what
the permission rules happen to catch. Once contents enter context they are sent
to the API; that is the thing we are preventing.

## If you need to look at a statement's contents: redact first

1. **Ask the user to confirm `redact_terms.txt` is up to date** before redacting.
   Confirm it still lists every piece of PII in the *current* document — name,
   account number, IBAN, address, and anything new. A stale term list silently
   leaves PII exposed, which is the most dangerous failure mode.
2. Dry-run to verify every term is found (watch for the "NOT found" warning):
   `python redact_pdf.py STATEMENT.pdf out.pdf --terms-file redact_terms.txt --dry-run`
3. Apply, writing a `*_redacted*.pdf` output:
   `python redact_pdf.py STATEMENT.pdf STATEMENT_redacted.pdf --terms-file redact_terms.txt`
4. Only ever read the resulting `*_redacted*.pdf`. It is rasterized, so it has no
   recoverable text layer.

## Permissions (`.claude/settings.json`)

- Reading is blocked for originals, `*_unlocked.pdf`, CSV/XLSX exports, and the
  term lists. `*_redacted*.pdf` files are readable.
- Permission globs can't express "every PDF except redacted," so the behavioral
  rule above is the real guarantee — follow it even when a file isn't blocked.
- Settings load at Claude Code startup and do not hot-reload; changes need a
  session restart to take effect.

## Data hygiene

- Never send statement data to external services, feedback, or `/bug` reports.
- The redacted PDFs are for sharing/archiving; they are image-only and cannot be
  parsed by `boi_statement_parser.py` (it needs the text layer of an original).
