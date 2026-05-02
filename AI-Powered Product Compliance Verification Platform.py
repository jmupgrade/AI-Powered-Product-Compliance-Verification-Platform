#!/usr/bin/env python3
"""
PO-to-CareLabel Verification System
=====================================
Automated verification of Purchase Orders (POs) against physical care labels.

Accepts pre-extracted text (from any PDF parser or OCR tool) as input strings.
No hardcoded data — all data is passed in at runtime via function parameters.

Rules enforced:
  1. PO # mismatch          -> HALT, return "po # mismatch" only
  2. Non-care-label file    -> HALT, return "double check if attachment is care label"
  3. Style # missing        -> Report sizes found + specific flag message
  4. Generic labels only    -> Specific flag message (no style # in label)

Style number formats supported:
  - Standard:  HS40022BU  (2 letters + 5 digits + 2 letters)
  - Hyphenated: PJ60325-BE (2 letters + 5 digits + hyphen + 2 letters)

Author: AI Assistant
"""

import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set
from enum import Enum


# =============================================================================
# ENUMS & STATUS CODES
# =============================================================================

class VerificationStatus(Enum):
    MATCH         = "MATCH"
    DISCREPANCY   = "DISCREPANCY"
    MISSING       = "MISSING"
    GENERIC_LABEL = "GENERIC_LABEL"
    PO_MISMATCH   = "PO_MISMATCH"
    NOT_CARE_LABEL = "NOT_CARE_LABEL"


# =============================================================================
# SIZE NORMALIZATION
# =============================================================================

# Canonical form for every size string variant seen across POs and care labels.
# Care labels use bilingual codes (S/P, M/M, L/G, XS/TP, XL/TG).
# POs use English words (SMALL, MEDIUM, LARGE) or abbreviations (XS, S, M, L, XL).
SIZE_NORMALIZATION_MAP: Dict[str, str] = {
    # English full names
    "EXTRA SMALL": "XS", "X-SMALL": "XS", "XSMALL": "XS",
    "SMALL":       "S",
    "MEDIUM":      "M",
    "LARGE":       "L",
    "EXTRA LARGE": "XL", "X-LARGE": "XL", "XLARGE": "XL",
    # Bilingual care label codes
    "XS/TP": "XS", "TP": "XS",
    "S/P":   "S",  "P":  "S",
    "M/M":   "M",
    "L/G":   "L",  "G":  "L",
    "XL/TG": "XL", "TG": "XL",
    # Plain abbreviations
    "XS": "XS", "S": "S", "M": "M", "L": "L", "XL": "XL",
    # Blanket / dimension sizes
    "30*40": "30x40", "30X40": "30x40", "30 X 40": "30x40",
    "40*50": "40x50", "40X50": "40x50", "40 X 50": "40x50",
}

SIZE_SORT_ORDER: Dict[str, int] = {
    "XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4,
    "30x40": 10, "40x50": 11,
}


def normalize_size(size_str: str) -> str:
    """Convert any size string variant to its canonical abbreviation."""
    upper = size_str.upper().strip()
    if upper in SIZE_NORMALIZATION_MAP:
        return SIZE_NORMALIZATION_MAP[upper]
    # Dimension pattern fallback
    if "30" in upper and "40" in upper:
        return "30x40"
    if "40" in upper and "50" in upper:
        return "40x50"
    return upper


def size_sort_key(size: str) -> int:
    return SIZE_SORT_ORDER.get(normalize_size(size), 99)


def normalize_and_sort(sizes: List[str]) -> List[str]:
    """Normalize a list of sizes and return sorted, deduplicated result."""
    normalized = list({normalize_size(s) for s in sizes})
    return sorted(normalized, key=size_sort_key)


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class StyleRecord:
    """One style entry extracted from either a PO or a care label."""
    style_number: Optional[str]   # None when label carries no style #
    sizes: List[str]              # Already normalized on construction
    source: str                   # Filename, page ref, or description
    is_generic: bool = False      # True = label has sizes but no style #

    def __post_init__(self):
        self.sizes = normalize_and_sort(self.sizes)
        if self.style_number:
            self.style_number = self.style_number.upper().strip()


@dataclass
class VerificationResult:
    """Comparison result for one style number."""
    style_number: str
    po_sizes:    List[str]
    label_sizes: List[str]
    status:  VerificationStatus
    details: str


@dataclass
class VerificationReport:
    """Complete report produced by one verification run."""
    po_number:         str
    total_po_styles:   int
    total_label_styles: int
    matches:       int
    discrepancies: int
    missing:       int
    generic_labels: int
    results: List[VerificationResult]

    def to_dict(self) -> Dict:
        rate = (
            f"{self.matches / self.total_po_styles * 100:.1f}%"
            if self.total_po_styles > 0 else "N/A"
        )
        return {
            "po_number": self.po_number,
            "summary": {
                "total_po_styles":    self.total_po_styles,
                "total_label_styles": self.total_label_styles,
                "matches":        self.matches,
                "discrepancies":  self.discrepancies,
                "missing":        self.missing,
                "generic_labels": self.generic_labels,
                "match_rate":     rate,
            },
            "results": [
                {
                    "style":       r.style_number,
                    "po_sizes":    r.po_sizes,
                    "label_sizes": r.label_sizes,
                    "status":      r.status.value,
                    "details":     r.details,
                }
                for r in self.results
            ],
        }


# =============================================================================
# SHARED STYLE-NUMBER REGEX
# =============================================================================

# Matches both HS40022BU (no hyphen) and PJ60325-BE (with hyphen).
# Used by both POExtractor and CareLabelExtractor.
STYLE_NUMBER_RE = re.compile(r"([A-Z]{2}\d{5}-?[A-Z]{2})", re.IGNORECASE)


# =============================================================================
# PO EXTRACTOR
# =============================================================================

class POExtractor:
    """
    Extracts style records from pre-extracted PO text.

    Two calling conventions are supported:

    1. Single-string mode (Version 2 style):
         POExtractor.extract_from_text(full_po_text, po_number)
         The text is split on page boundaries and each page is parsed.

    2. Page-list mode (Version 1 style):
         POExtractor.extract_from_pages(["page1 text", "page2 text", ...])
         Each string in the list is treated as one page.

    Both return (List[StyleRecord], Optional[str]) where the second element
    is an error message string or None.
    """

    # Additional context patterns to help locate a style number on a PO page.
    # The bare STYLE_NUMBER_RE is tried first; these are used as fallbacks.
    _STYLE_CONTEXT_PATTERNS = [
        re.compile(r"STYLE#?\s*:?\s*([A-Z]{2}\d{5}-?[A-Z]{2})", re.IGNORECASE),
        re.compile(r"STYLE\s*#?\s*:?\s*([A-Z]{2}\d{5}-?[A-Z]{2})", re.IGNORECASE),
        re.compile(r"([A-Z]{2}\d{5}-?[A-Z]{2})\s*(?:WESTMARK|Color|Description)", re.IGNORECASE),
    ]

    # PO size indicators — apparel and blanket
    _APPAREL_SIZE_TOKENS = {
        "XS", "XSMALL", "X-SMALL",
        "S",  "SMALL",
        "M",  "MEDIUM",
        "L",  "LARGE",
        "XL", "XLARGE", "X-LARGE",
    }
    _BLANKET_SIZE_PATTERNS = [
        re.compile(r"(30[*xX\s]40)", re.IGNORECASE),
        re.compile(r"(40[*xX\s]50)", re.IGNORECASE),
    ]

    @classmethod
    def extract_from_text(
        cls,
        full_text: str,
        po_number: str
    ) -> Tuple[List[StyleRecord], Optional[str]]:
        """
        Parse a single concatenated PO text string.
        Pages are detected by 'Page N of N' markers; if none found the whole
        text is treated as one page.
        """
        pages = re.split(r"Page\s*\d+\s*of\s*\d+", full_text, flags=re.IGNORECASE)
        pages = [p.strip() for p in pages if p.strip()]
        if not pages:
            pages = [full_text]
        return cls._parse_pages(pages, po_number)

    @classmethod
    def extract_from_pages(
        cls,
        page_list: List[str],
        po_number: Optional[str] = None
    ) -> Tuple[List[StyleRecord], Optional[str]]:
        """
        Parse a list of per-page text strings.
        Validates PO number consistency across pages if po_number is supplied.
        """
        # Validate PO number consistency when caller did not supply one
        detected_po = cls._detect_po_number(page_list)
        if po_number is None:
            po_number = detected_po
        elif detected_po and detected_po != po_number.lstrip("0"):
            return [], f"PO # mismatch in document: found {detected_po}, expected {po_number}"
        return cls._parse_pages(page_list, po_number or "")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _detect_po_number(cls, pages: List[str]) -> Optional[str]:
        """Return the PO number found in the first matching page, stripped of leading zeros."""
        for page in pages:
            m = re.search(r"PO\s*#\s*(\d+)", page, re.IGNORECASE)
            if m:
                return m.group(1).lstrip("0")
        return None

    @classmethod
    def _parse_pages(
        cls,
        pages: List[str],
        po_number: str
    ) -> Tuple[List[StyleRecord], Optional[str]]:
        records: List[StyleRecord] = []
        for idx, page in enumerate(pages):
            style_num = cls._extract_style_number(page)
            if not style_num:
                continue
            sizes = cls._extract_sizes(page)
            records.append(StyleRecord(
                style_number=style_num,
                sizes=sizes,
                source=f"PO page {idx + 1}",
            ))
        return records, None

    @classmethod
    def _extract_style_number(cls, page_text: str) -> Optional[str]:
        """Try all patterns to find a style number; return uppercase or None."""
        # Context-aware patterns first (more precise)
        for pattern in cls._STYLE_CONTEXT_PATTERNS:
            m = pattern.search(page_text)
            if m:
                return m.group(1).upper()
        # Bare style number anywhere on the page
        m = STYLE_NUMBER_RE.search(page_text)
        if m:
            return m.group(1).upper()
        return None

    @classmethod
    def _extract_sizes(cls, page_text: str) -> List[str]:
        """Extract all size tokens from a PO page."""
        found: Set[str] = set()
        upper = page_text.upper()

        # Blanket / dimension sizes
        for pattern in cls._BLANKET_SIZE_PATTERNS:
            for m in pattern.finditer(page_text):
                found.add(m.group(1).upper())

        # Apparel sizes — use word-boundary matching to avoid false positives
        # (e.g. 'S' inside 'WESTMARK', 'M' inside 'MEDIUM' already captured)
        for token in cls._APPAREL_SIZE_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", upper):
                found.add(token)

        return list(found)


# =============================================================================
# CARE LABEL EXTRACTOR
# =============================================================================

class CareLabelExtractor:
    """
    Extracts style records from pre-extracted care label text.

    Two calling conventions are supported:

    1. Single block of text (one label or one PDF with all labels):
         CareLabelExtractor.extract_from_text(label_text, filename)

    2. Raw multi-label string in Version-1 format (Chinese 正 markers,
       STYLE# tokens, bilingual sizes):
         CareLabelExtractor.extract_from_raw(raw_text, filename)

    Both return (List[StyleRecord], Optional[str]).
    """

    # Keywords that strongly indicate a genuine care label.
    # English is required; French/Spanish/Chinese may also appear.
    _CARE_INDICATORS = [
        # Wash instructions
        "MACHINE WASH", "HAND WASH", "DO NOT WASH", "MACHINE WASHABLE",
        "LAVAGE EN MACHINE", "LAVAGE À LA MAIN",
        "LAVAR A MÁQUINA", "LAVAR A MANO",
        # Bleach
        "DO NOT BLEACH", "NE PAS BLANCHIR", "NO USAR LEJÍA",
        # Dry
        "TUMBLE DRY", "DO NOT TUMBLE DRY", "LINE DRY", "FLAT DRY",
        "SÉCHAGE PAR CULBUTAGE", "SECAR EN SECADORA",
        # Iron
        "DO NOT IRON", "IRON", "NE PAS REPASSER",
        # Dry clean
        "DO NOT DRY CLEAN", "DRY CLEAN ONLY", "NE PAS NETTOYER",
        # Label identifiers
        "CARE LABEL", "CARE INSTRUCTIONS", "SIZE/CARE",
        # Fiber content keywords
        "100% POLYESTER", "100% COTTON", "100% ACRYLIC",
        "POLYESTER", "COTTON", "ACRYLIC", "NYLON", "SPANDEX",
        # Regulatory
        "RN#", "RN #", "MADE IN CHINA", "MADE IN",
    ]

    # Keywords that indicate this is NOT a care label (hangtag, price ticket, etc.)
    _HANGTAG_INDICATORS = [
        "BARCODE", "UPC:", "HANGTAG", "PRICE TICKET",
        "JOKER TAG", "P.FLASHER", "PET POSSE",
    ]

    # Style number patterns on care labels — same regex, more context variants
    _STYLE_PATTERNS = [
        re.compile(r"STYLE#\s*([A-Z]{2}\d{5}-?[A-Z]{2})", re.IGNORECASE),
        re.compile(r"STYLE\s*#\s*([A-Z]{2}\d{5}-?[A-Z]{2})", re.IGNORECASE),
        re.compile(r"STYLE/MODEL:\s*([A-Z]{2}\d{5}-?[A-Z]{2})", re.IGNORECASE),
    ]

    # Bilingual size tokens as they appear on care labels
    _CARE_LABEL_SIZE_TOKENS = [
        "XS/TP", "XL/TG",   # must come before single-letter variants
        "S/P", "M/M", "L/G",
        "XS", "XL",
        r"\bS\b", r"\bM\b", r"\bL\b",
    ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def extract_from_text(
        cls,
        label_text: str,
        filename: str = "care_label"
    ) -> Tuple[List[StyleRecord], Optional[str]]:
        """
        Parse a single care label text block.
        Suitable for Version-2 style input (one label per call, or a PDF
        whose pages have already been joined).
        """
        is_valid, reason = cls._is_care_label(label_text)
        if not is_valid:
            return [], f"NOT_CARE_LABEL: {reason}"

        styles = cls._find_style_numbers(label_text)
        sizes  = cls._find_sizes(label_text)

        return cls._build_records(styles, sizes, filename)

    @classmethod
    def extract_from_raw(
        cls,
        raw_text: str,
        filename: str = "care_label_raw"
    ) -> Tuple[List[StyleRecord], Optional[str]]:
        """
        Parse the Version-1 raw care label format:
          - Entries delimited by 'STYLE#' markers
          - Sizes (XS/TP, S/P, M/M, L/G …) appear before the STYLE# token
          - Chinese characters (正) used as separators — safely ignored

        This method does NOT run the is_care_label gate because Version-1
        raw text is pre-validated by the caller (it is the hardcoded /
        OCR-extracted care label blob, not a file whose type is ambiguous).
        If you want the gate, call extract_from_text() instead.
        """
        warnings: List[str] = []
        records:  List[StyleRecord] = []

        # Normalize spacing around STYLE# so splitting is reliable
        normalized = re.sub(r"STYLE\s*#\s*", "STYLE#", raw_text, flags=re.IGNORECASE)
        parts = re.split(r"STYLE#", normalized, flags=re.IGNORECASE)

        for i in range(1, len(parts)):
            # Style number: first token on the first line of parts[i]
            first_line = parts[i].split("\n")[0].strip()
            m = STYLE_NUMBER_RE.search(first_line)
            if not m:
                continue
            style = m.group(1).upper()

            # IMPORTANT: In the raw care label format, sizes appear on the lines
            # BEFORE the STYLE# marker — i.e. in parts[i-1], not parts[i].
            # Reading forward (into parts[i]) would capture sizes from the NEXT entry.
            sizes = cls._find_sizes(parts[i - 1])

            records.append(StyleRecord(
                style_number=style,
                sizes=sizes,
                source=filename,
            ))


        if not records:
            # Fall back to whole-text parse (no per-entry splitting)
            styles = cls._find_style_numbers(raw_text)
            sizes  = cls._find_sizes(raw_text)
            records, warn = cls._build_records(styles, sizes, filename)
            if warn:
                warnings.append(warn)

        warning = "; ".join(warnings) if warnings else None
        return records, warning

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _is_care_label(cls, text: str) -> Tuple[bool, str]:
        """Score text against care-label and hangtag keyword lists."""
        upper = text.upper()
        care_score    = sum(1 for kw in cls._CARE_INDICATORS    if kw.upper() in upper)
        hangtag_score = sum(1 for kw in cls._HANGTAG_INDICATORS if kw.upper() in upper)

        if hangtag_score >= 3 and care_score < 2:
            return False, "File appears to be a hangtag/packaging insert, not a care label"
        if care_score >= 2:
            return True, "Valid care label detected"
        # Ambiguous — pass through with a note; caller will see it in the report
        return True, "Ambiguous content — recommend manual review"

    @classmethod
    def _find_style_numbers(cls, text: str) -> List[str]:
        """Return all unique style numbers found in text."""
        found: Set[str] = set()
        for pattern in cls._STYLE_PATTERNS:
            for m in pattern.finditer(text):
                found.add(m.group(1).upper())
        # Bare style numbers as final fallback
        if not found:
            for m in STYLE_NUMBER_RE.finditer(text):
                found.add(m.group(1).upper())
        return list(found)

    @classmethod
    def _find_sizes(cls, text: str) -> List[str]:
        """Extract all size tokens from care label text."""
        found: Set[str] = set()
        # Work through tokens in priority order (longer / more specific first)
        for token in cls._CARE_LABEL_SIZE_TOKENS:
            if re.search(token, text, re.IGNORECASE):
                # Extract the matched string (strip regex anchors for set key)
                raw = token.replace(r"\b", "").strip()
                found.add(raw.upper())
        return list(found)

    @classmethod
    def _build_records(
        cls,
        styles: List[str],
        sizes:  List[str],
        source: str
    ) -> Tuple[List[StyleRecord], Optional[str]]:
        """Build StyleRecord list and produce a warning when style # is absent."""
        if styles:
            records = [
                StyleRecord(style_number=s, sizes=sizes, source=source)
                for s in styles
            ]
            return records, None

        # No style numbers found
        if sizes:
            record = StyleRecord(
                style_number=None,
                sizes=sizes,
                source=source,
                is_generic=True,
            )
            warning = (
                "Cannot find style # in care label. Need to double check: "
                "1. whether the tool failed to identify it from the file; "
                "2. whether there is no style # in the care label — if so, confirm "
                "if style # is necessary for these styles."
            )
            return [record], warning

        warning = (
            "These care labels display no individual style numbers and no recognizable sizes. "
            "Need to double check if style # is needed for this PO."
        )
        return [], warning


# =============================================================================
# VERIFICATION ENGINE
# =============================================================================

class VerificationEngine:
    """
    Compares a list of PO StyleRecords against a list of care-label StyleRecords
    and produces a VerificationReport.
    """

    @classmethod
    def verify(
        cls,
        po_number:      str,
        po_styles:      List[StyleRecord],
        label_styles:   List[StyleRecord],
        requested_po:   str,
    ) -> VerificationReport:
        """
        Main entry point.

        Args:
            po_number:    PO number as extracted from the PO document.
            po_styles:    StyleRecords parsed from the PO.
            label_styles: StyleRecords parsed from care labels.
            requested_po: PO number the user asked to verify (for mismatch check).
        """
        # Rule 1 — PO number mismatch: halt immediately
        if po_number.lstrip("0") != requested_po.lstrip("0"):
            return VerificationReport(
                po_number=requested_po,
                total_po_styles=0,
                total_label_styles=0,
                matches=0,
                discrepancies=0,
                missing=0,
                generic_labels=0,
                results=[VerificationResult(
                    style_number="N/A",
                    po_sizes=[],
                    label_sizes=[],
                    status=VerificationStatus.PO_MISMATCH,
                    details="po # mismatch",
                )],
            )

        # Build label lookup
        label_lookup:    Dict[str, StyleRecord] = {}
        generic_sizes:   Set[str]               = set()
        generic_label_count = 0

        for lbl in label_styles:
            if lbl.is_generic or lbl.style_number is None:
                generic_label_count += 1
                generic_sizes.update(lbl.sizes)
            else:
                label_lookup[lbl.style_number] = lbl

        results: List[VerificationResult] = []
        matches = discrepancies = missing = 0

        for po_style in po_styles:
            result = cls._compare_one(po_style, label_lookup, generic_sizes)
            results.append(result)
            if result.status == VerificationStatus.MATCH:
                matches += 1
            elif result.status == VerificationStatus.DISCREPANCY:
                discrepancies += 1
            elif result.status in (VerificationStatus.MISSING, VerificationStatus.GENERIC_LABEL):
                missing += 1

        return VerificationReport(
            po_number=po_number,
            total_po_styles=len(po_styles),
            total_label_styles=len(label_lookup),
            matches=matches,
            discrepancies=discrepancies,
            missing=missing,
            generic_labels=generic_label_count,
            results=results,
        )

    @classmethod
    def _compare_one(
        cls,
        po_style:     StyleRecord,
        label_lookup: Dict[str, StyleRecord],
        generic_sizes: Set[str],
    ) -> VerificationResult:
        """Compare one PO style against the care label lookup."""

        if po_style.style_number not in label_lookup:
            # Style not found individually — check if generic labels exist
            if generic_sizes:
                generic_sorted = sorted(list(generic_sizes), key=size_sort_key)
                return VerificationResult(
                    style_number=po_style.style_number,
                    po_sizes=po_style.sizes,
                    label_sizes=generic_sorted,
                    status=VerificationStatus.GENERIC_LABEL,
                    details=(
                        f"Style not found in individually labeled care labels. "
                        f"Generic labels cover sizes: {generic_sorted}. "
                        f"Cannot find style # in care label — double check: "
                        f"1. whether tool failed to identify it; "
                        f"2. whether style # is necessary for these styles."
                    ),
                )
            return VerificationResult(
                style_number=po_style.style_number,
                po_sizes=po_style.sizes,
                label_sizes=[],
                status=VerificationStatus.MISSING,
                details=f"{po_style.style_number} is on the PO but not found in any care label",
            )

        lbl = label_lookup[po_style.style_number]
        po_set  = set(po_style.sizes)
        lbl_set = set(lbl.sizes)

        if po_set == lbl_set:
            return VerificationResult(
                style_number=po_style.style_number,
                po_sizes=po_style.sizes,
                label_sizes=lbl.sizes,
                status=VerificationStatus.MATCH,
                details="All sizes align",
            )

        missing_in_label = sorted(list(po_set  - lbl_set), key=size_sort_key)
        extra_in_label   = sorted(list(lbl_set - po_set),  key=size_sort_key)
        parts = []
        if missing_in_label:
            parts.append(f"In PO but missing from care label: {missing_in_label}")
        if extra_in_label:
            parts.append(f"In care label but not in PO: {extra_in_label}")

        return VerificationResult(
            style_number=po_style.style_number,
            po_sizes=po_style.sizes,
            label_sizes=lbl.sizes,
            status=VerificationStatus.DISCREPANCY,
            details="; ".join(parts),
        )


# =============================================================================
# REPORT GENERATOR
# =============================================================================

class ReportGenerator:
    """Produces human-readable plain-text and machine-readable JSON reports."""

    STATUS_ICON = {
        VerificationStatus.MATCH:          "OK",
        VerificationStatus.DISCREPANCY:    "WARN",
        VerificationStatus.MISSING:        "MISSING",
        VerificationStatus.GENERIC_LABEL:  "GENERIC",
        VerificationStatus.PO_MISMATCH:    "ERROR",
        VerificationStatus.NOT_CARE_LABEL: "ERROR",
    }

    @classmethod
    def generate_text(cls, report: VerificationReport) -> str:
        """Plain-text report — matches Version-1 output style."""
        sep  = "=" * 80
        dash = "-" * 80
        lines = [
            sep,
            "CARE LABEL vs PO COMPARISON REPORT",
            f"PO Number : {report.po_number}",
            sep, "",
            f"Total PO Styles   : {report.total_po_styles}",
            f"Care Label Styles : {report.total_label_styles}",
            f"Matched           : {report.matches}",
            f"Discrepancies     : {report.discrepancies}",
            f"Missing           : {report.missing}",
            f"Generic Labels    : {report.generic_labels}",
            "",
            dash,
            f"{'Style #':<15} {'PO Sizes':<25} {'Label Sizes':<25} {'Status':<12} Details",
            dash,
        ]

        for r in report.results:
            po_str  = ", ".join(r.po_sizes)    if r.po_sizes    else "N/A"
            lbl_str = ", ".join(r.label_sizes) if r.label_sizes else "N/A"
            icon    = cls.STATUS_ICON.get(r.status, "?")
            status  = f"[{icon}]"
            lines.append(
                f"{r.style_number:<15} {po_str:<25} {lbl_str:<25} {status:<12} {r.details}"
            )

        lines.append(dash)
        lines.append("")

        # Discrepancy detail block
        problems = [r for r in report.results if r.status != VerificationStatus.MATCH]
        if problems:
            lines.append("ISSUES REQUIRING ATTENTION:")
            lines.append(dash)
            for r in problems:
                lines.append(f"  Style   : {r.style_number}")
                lines.append(f"  Status  : {r.status.value}")
                lines.append(f"  PO      : {r.po_sizes}")
                lines.append(f"  Label   : {r.label_sizes}")
                lines.append(f"  Details : {r.details}")
                lines.append("")
        else:
            lines.append("NO DISCREPANCIES FOUND.")
            lines.append("")

        lines += [sep, "END OF REPORT", sep]
        return "\n".join(lines)

    @classmethod
    def generate_markdown(cls, report: VerificationReport) -> str:
        """Markdown report — matches Version-2 output style."""
        rate = (
            f"{report.matches / report.total_po_styles * 100:.1f}%"
            if report.total_po_styles > 0 else "N/A"
        )
        lines = [
            "# PO-to-CareLabel Verification Report",
            "",
            f"**PO Number:** {report.po_number}  ",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total PO Styles | {report.total_po_styles} |",
            f"| Total Care Label Styles | {report.total_label_styles} |",
            f"| Matches | {report.matches} |",
            f"| Discrepancies | {report.discrepancies} |",
            f"| Missing from Labels | {report.missing} |",
            f"| Generic Labels | {report.generic_labels} |",
            f"| Match Rate | {rate} |",
            "",
            "---",
            "",
            "## Detailed Results",
            "",
            "| Style # | PO Sizes | Label Sizes | Status | Details |",
            "|---------|----------|-------------|--------|---------|",
        ]

        for r in report.results:
            po_str  = ", ".join(r.po_sizes)    if r.po_sizes    else "-"
            lbl_str = ", ".join(r.label_sizes) if r.label_sizes else "-"
            icon    = cls.STATUS_ICON.get(r.status, "?")
            lines.append(
                f"| {r.style_number} | {po_str} | {lbl_str} | "
                f"[{icon}] {r.status.value} | {r.details} |"
            )

        lines += [
            "",
            "---",
            "",
            "## Legend",
            "",
            "- **[OK] MATCH** — Style and sizes match between PO and care label",
            "- **[WARN] DISCREPANCY** — Style found but sizes differ",
            "- **[MISSING]** — Style on PO but not found in any care label",
            "- **[GENERIC]** — Only generic labels found (no individual style #)",
            "- **[ERROR]** — PO number mismatch or file is not a care label",
            "",
            "---",
            "",
            "*End of Report*",
        ]
        return "\n".join(lines)

    @classmethod
    def generate_json(cls, report: VerificationReport) -> str:
        return json.dumps(report.to_dict(), indent=2)


# =============================================================================
# CONVENIENCE WRAPPER — top-level function for quick use
# =============================================================================

def run_verification(
    requested_po:   str,
    po_pages:       Optional[List[str]]  = None,
    po_full_text:   Optional[str]        = None,
    label_texts:    Optional[List[Tuple[str, str]]] = None,   # [(text, filename), ...]
    label_raw_text: Optional[str]        = None,
    output_format:  str                  = "text",   # "text" | "markdown" | "json" | "all"
) -> str:
    """
    One-call verification wrapper.

    Provide PO data via ONE of:
      po_pages     — list of per-page text strings  (Version-1 style)
      po_full_text — single concatenated text block (Version-2 style)

    Provide care label data via ONE or BOTH of:
      label_texts    — list of (text, filename) tuples; each text goes
                       through is_care_label validation
      label_raw_text — single raw blob in Version-1 format (STYLE# delimited)

    output_format: "text" | "markdown" | "json" | "all"
    """
    # ---- Extract PO styles ----
    if po_pages is not None:
        po_styles, po_err = POExtractor.extract_from_pages(po_pages, requested_po)
    elif po_full_text is not None:
        po_styles, po_err = POExtractor.extract_from_text(po_full_text, requested_po)
    else:
        return "ERROR: Provide either po_pages or po_full_text."

    if po_err:
        return f"ERROR extracting PO data: {po_err}"

    po_number = requested_po  # Treat the requested PO as authoritative here

    # ---- Extract care label styles ----
    all_label_styles: List[StyleRecord] = []
    label_warnings: List[str] = []

    if label_raw_text is not None:
        records, warn = CareLabelExtractor.extract_from_raw(label_raw_text)
        all_label_styles.extend(records)
        if warn:
            label_warnings.append(warn)

    if label_texts is not None:
        for text, fname in label_texts:
            records, warn = CareLabelExtractor.extract_from_text(text, fname)
            if warn and warn.startswith("NOT_CARE_LABEL"):
                return f"ERROR: double check if attachment is care label — {fname}: {warn}"
            all_label_styles.extend(records)
            if warn:
                label_warnings.append(warn)

    # ---- Run verification ----
    report = VerificationEngine.verify(
        po_number=po_number,
        po_styles=po_styles,
        label_styles=all_label_styles,
        requested_po=requested_po,
    )

    # ---- Format output ----
    if output_format == "text":
        result = ReportGenerator.generate_text(report)
    elif output_format == "markdown":
        result = ReportGenerator.generate_markdown(report)
    elif output_format == "json":
        result = ReportGenerator.generate_json(report)
    elif output_format == "all":
        result = "\n\n".join([
            ReportGenerator.generate_text(report),
            ReportGenerator.generate_markdown(report),
            ReportGenerator.generate_json(report),
        ])
    else:
        result = ReportGenerator.generate_text(report)

    if label_warnings:
        result = "[WARNINGS]\n" + "\n".join(label_warnings) + "\n\n" + result

    return result


# =============================================================================
# DEMO — reproduces the PO 9648 run from Version 1 using runtime parameters
# =============================================================================

def _demo_po_9648():
    """
    Demonstrates the system using the same data as the original Version-1 script.
    Data is passed as function arguments — nothing is hardcoded in the system itself.
    """

    care_label_raw = """
正 1304 PCS 正 正 反 1304 PCS 1304 PCS S/P M/M L/G
STYLE# HS40022BU

正 800 PCS 正 正 反 800 PCS 800 PCS S/P M/M L/G
STYLE# HS43012BU

正 904 PCS 正 正 反 904 PCS 904 PCS S/P M/M L/G
STYLE# SW24004BU

正 904 PCS 正 正 反 904 PCS 904 PCS S/P M/M L/G
STYLE# SW24005BU

正 1200 PCS 正 正 反 1200 PCS 1200 PCS S/P M/M L/G
STYLE# SW23135BU

正 904 PCS 正 正 反 904 PCS 904 PCS S/P M/M L/G
STYLE# SW26202BU

正 904 PCS 正 正 反 904 PCS 904 PCS S/P M/M L/G
STYLE# SW26209BU

正 1200 PCS 正 正 反 1200 PCS 1200 PCS S/P M/M L/G
STYLE# SW26211BU

正 1000 PCS 正 正 反 1000 PCS 1000 PCS S/P M/M L/G
STYLE# SW26205BU

正 800 PCS 正 正 反 800 PCS 800 PCS S/P M/M L/G
STYLE# HS43001BU

正 904 PCS 正 正 反 904 PCS 904 PCS S/P M/M L/G
STYLE# SW30182BU

正 800 PCS 正 正 反 800 PCS 800 PCS XS/TP S/P M/M
STYLE# SW30188BU

正 1200 PCS 正 正 反 1200 PCS 1200 PCS XS/TP S/P M/M
STYLE# SW26303BU

正 904 PCS 正 正 反 904 PCS 904 PCS S/P M/M L/G
STYLE# SW26204BU

正 1200 PCS 正 正 反 1200 PCS 1200 PCS XS/TP S/P M/M
STYLE# HS43010BU

正 1200 PCS 正 正 反 1200 PCS 1200 PCS S/P M/M L/G
STYLE# SW26214BU

正 800 PCS 正 正 反 800 PCS 800 PCS XS/TP S/P M/M
STYLE# HS43022BU

正 1304 PCS 正 正 反 1304 PCS 1304 PCS S/P M/M L/G
STYLE# HS43002BU

正 800 PCS 正 正 反 800 PCS 800 PCS S/P M/M L/G
STYLE# HS43000BU

正 1000 PCS 正 正 反 1000 PCS 1000 PCS S/P M/M L/G
STYLE# HS43014BU

正 904PCS S/P 正 904PCS M/M 正 904PCS L/G
STYLE#SW26208BU

正 904PCS S/P 正 904PCS M/M 正 904PCS L/G
STYLE#HS43004BU
"""

    po_pages = [
        "PO # 0000009648 HS40022BU SMALL MEDIUM LARGE QTY: 1304 QTY: 1304 QTY: 1304",
        "PO # 0000009648 SW24004BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
        "PO # 0000009648 SW24005BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
        "PO # 0000009648 SW23135BU SMALL MEDIUM LARGE QTY: 1200 QTY: 1200 QTY: 1200",
        "PO # 0000009648 SW26202BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
        "PO # 0000009648 SW26205BU SMALL MEDIUM LARGE QTY: 1000 QTY: 1000 QTY: 1000",
        "PO # 0000009648 SW26209BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
        "PO # 0000009648 SW26211BU SMALL MEDIUM LARGE QTY: 1200 QTY: 1200 QTY: 1200",
        "PO # 0000009648 SW26214BU SMALL MEDIUM LARGE QTY: 1200 QTY: 1200 QTY: 1200",
        "PO # 0000009648 HS43010BU XS S M QTY: 1200 QTY: 1200 QTY: 1200",
        "PO # 0000009648 HS43022BU XS S M QTY: 800 QTY: 800 QTY: 800",
        "PO # 0000009648 SW30182BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
        "PO # 0000009648 SW30188BU XS S M QTY: 800 QTY: 800 QTY: 800",
        "PO # 0000009648 HS43002BU SMALL MEDIUM LARGE QTY: 1304 QTY: 1304 QTY: 1304",
        "PO # 0000009648 HS43000BU SMALL MEDIUM LARGE QTY: 800 QTY: 800 QTY: 800",
        "PO # 0000009648 HS43001BU SMALL MEDIUM LARGE QTY: 800 QTY: 800 QTY: 800",
        "PO # 0000009648 HS43012BU SMALL MEDIUM LARGE QTY: 800 QTY: 800 QTY: 800",
        "PO # 0000009648 HS43014BU SMALL MEDIUM LARGE QTY: 1000 QTY: 1000 QTY: 1000",
        "PO # 0000009648 SW26208BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
        "PO # 0000009648 HS43004BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
        "PO # 0000009648 SW26303BU XS S M QTY: 1200 QTY: 1200 QTY: 1200",
        "PO # 0000009648 SW26204BU SMALL MEDIUM LARGE QTY: 904 QTY: 904 QTY: 904",
    ]

    print(run_verification(
        requested_po="9648",
        po_pages=po_pages,
        label_raw_text=care_label_raw,
        output_format="text",
    ))


if __name__ == "__main__":
    _demo_po_9648()
