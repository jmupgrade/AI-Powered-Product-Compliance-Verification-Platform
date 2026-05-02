# PO-to-CareLabel Verification System

## Description

Automated tool that compares Purchase Orders (POs) against physical care labels to verify that every style number and its size range match exactly. It was built to replace a manual, error-prone cross-check process in garment sourcing. It catches size mismatches, missing styles, non-care-label attachments, and PO number mismatches before production errors occur.

## Key Features

- Accepts pre-extracted text from any PDF parser or OCR tool — no file reading dependency
- Two PO input modes: per-page list (one string per page) or single concatenated text block
- Two care label input modes: structured per-label text with keyword validation, or raw STYLE#-delimited blob (Chinese/bilingual format)
- Correctly handles the raw care label format where sizes appear **before** the STYLE# marker, not after
- Normalizes all size variants to canonical form: `S/P → S`, `M/M → M`, `L/G → L`, `XS/TP → XS`, `SMALL → S`, `MEDIUM → M`, `LARGE → L`, `30*40 → 30x40`, etc.
- Supports both style number formats: standard (`HS40022BU`) and hyphenated (`PJ60325-BE`)
- Care label gate: scores text against English/French/Spanish wash-instruction keywords to detect non-care-label attachments
- Enforced halt rules: PO number mismatch, non-care-label file, missing style #, generic labels with no style #
- Three output formats: plain text, Markdown table, JSON

## Setup / How to Run

No external dependencies — uses Python standard library only.

```
git clone <your-repo-url>
cd <your-project-folder>
python3 po_carelabel_verification_system.py
```

Running the file directly executes the built-in demo using PO 9648 data.

## Usage in Your Own Code

```python
from po_carelabel_verification_system import run_verification

# Option A — raw care label blob (STYLE# delimited, bilingual/Chinese format)
result = run_verification(
    requested_po="9648",
    po_pages=["PO # 0000009648 HS40022BU SMALL MEDIUM LARGE QTY: 1304 ..."],
    label_raw_text="正 1304 PCS S/P M/M L/G\nSTYLE# HS40022BU\n...",
    output_format="text",   # or "markdown" / "json" / "all"
)

# Option B — individual care label files (each text block validated as a care label)
result = run_verification(
    requested_po="9648",
    po_full_text="<full concatenated PO text with Page N of N markers>",
    label_texts=[
        ("MACHINE WASH COLD ... STYLE# HS40022BU ... S/P M/M L/G", "label_HS40022BU.pdf"),
        ("MACHINE WASH COLD ... STYLE# SW24004BU ... S/P M/M L/G", "label_SW24004BU.pdf"),
    ],
    output_format="markdown",
)

print(result)
```

## Rules Enforced

| Condition | Behaviour |
|-----------|-----------|
| PO number in document ≠ requested PO | HALT — `po # mismatch` |
| Attached file is not a care label | HALT — `double check if attachment is care label` |
| Style # present, sizes mismatch | DISCREPANCY row with exact diff |
| Style # on PO not found in any label | MISSING row |
| Care label has sizes but no style # | GENERIC row + warning message |
| All styles and sizes align | MATCH — clean report |
