#!/usr/bin/env python
"""
redact_pdf.py — find specific text in a PDF and permanently black it out.

Safety model: this does TRUE redaction. It locates the text, renders each page
to a raster image, paints solid black over the matches, and rebuilds the PDF
from those images. The original text layer is destroyed, so redacted content
cannot be selected, copied, or extracted afterwards.

Usage:
    python redact_pdf.py INPUT.pdf OUTPUT.pdf --term "12345678" --term "John Doe"
    python redact_pdf.py INPUT.pdf OUTPUT.pdf --terms-file secrets.txt
    python redact_pdf.py INPUT.pdf OUTPUT.pdf --term "AC.*NO" --regex
    python redact_pdf.py INPUT.pdf OUTPUT.pdf --term "12345678" --dry-run   # report only

By default matching is case-insensitive and literal (special characters are not
treated as regex). Pass --regex to treat each term as a regular expression, and
--case-sensitive to require an exact case match.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw


def load_terms(args) -> list[str]:
    terms: list[str] = list(args.term or [])
    if args.terms_file:
        for line in Path(args.terms_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line)
    # de-duplicate while preserving order
    seen, unique = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def find_boxes(page, terms, use_regex, case_sensitive):
    """Return list of (term, (x0, top, x1, bottom)) boxes in pdfplumber points."""
    boxes = []
    counts = {t: 0 for t in terms}
    for term in terms:
        try:
            matches = page.search(term, regex=use_regex, case=case_sensitive)
        except Exception as e:  # noqa: BLE001 - surface which term/page failed
            print(f"  ! error searching for {term!r}: {e}", file=sys.stderr)
            matches = []
        for m in matches:
            boxes.append((term, (m["x0"], m["top"], m["x1"], m["bottom"])))
            counts[term] += 1
    return boxes, counts


def redact(args) -> int:
    terms = load_terms(args)
    if not terms:
        print("No terms given. Use --term or --terms-file.", file=sys.stderr)
        return 2

    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 2

    print(f"Redacting {len(terms)} term(s) from {src.name}")
    total_counts = {t: 0 for t in terms}
    images: list[Image.Image] = []

    pdfium_doc = pdfium.PdfDocument(str(src)) if not args.dry_run else None
    scale = args.dpi / 72.0

    with pdfplumber.open(str(src)) as pdf:
        for i, page in enumerate(pdf.pages):
            boxes, counts = find_boxes(page, terms, args.regex, args.case_sensitive)
            for t, c in counts.items():
                total_counts[t] += c
            if boxes:
                found = ", ".join(f"{t!r} x{counts[t]}" for t in terms if counts[t])
                print(f"  page {i + 1}: {len(boxes)} box(es)  [{found}]")

            if args.dry_run:
                continue

            # Render the page to a raster image (destroys the text layer).
            pil = pdfium_doc[i].render(scale=scale).to_pil().convert("RGB")
            # Map pdfplumber points -> rendered pixels using actual image size,
            # which auto-corrects for DPI regardless of the page's box.
            sx = pil.width / float(page.width)
            sy = pil.height / float(page.height)
            draw = ImageDraw.Draw(pil)
            pad = args.pad
            for _term, (x0, top, x1, bottom) in boxes:
                rect = [
                    x0 * sx - pad,
                    top * sy - pad,
                    x1 * sx + pad,
                    bottom * sy + pad,
                ]
                draw.rectangle(rect, fill=(0, 0, 0))
            images.append(pil)

    # Report terms that were never found — a redaction you *think* happened but
    # didn't is the dangerous case, so make it loud.
    missing = [t for t, c in total_counts.items() if c == 0]
    if missing:
        print("\n  WARNING: these terms were NOT found (nothing redacted for them):")
        for t in missing:
            print(f"    - {t!r}")
        print("  Check spelling/spacing, or try --regex. Text split oddly across")
        print("  the PDF (e.g. wide letter-spacing) can prevent a literal match.")

    if args.dry_run:
        print("\nDry run -- no file written. Re-run without --dry-run to apply.")
        return 0

    if not images:
        print("No pages produced; aborting.", file=sys.stderr)
        return 1

    out = Path(args.output)
    images[0].save(
        str(out), "PDF", save_all=True, append_images=images[1:], resolution=args.dpi
    )
    print(f"\nWrote redacted (rasterized) PDF -> {out}")
    print("Verify: open it and try to select/copy a redacted area -- nothing should copy.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="source PDF")
    p.add_argument("output", help="destination PDF (rasterized)")
    p.add_argument("--term", action="append", help="text to redact (repeatable)")
    p.add_argument("--terms-file", help="file with one term per line (# = comment)")
    p.add_argument("--regex", action="store_true", help="treat terms as regular expressions")
    p.add_argument("--case-sensitive", action="store_true", help="require exact case")
    p.add_argument("--dpi", type=int, default=200, help="render resolution (default 200)")
    p.add_argument("--pad", type=float, default=1.0, help="extra pixels around each box (default 1)")
    p.add_argument("--dry-run", action="store_true", help="report matches without writing a file")
    return redact(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
