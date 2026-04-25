PO#9626 Hang Tag ↔ PO Verification System
Design Document | Generated: 2026-04-24 | Confidential
---
<div style="background:#d4edda; border:2px solid #28a745; border-radius:6px; padding:12px; text-align:center;">
✅ ALL VERIFIED — 21 Styles, 41 UPCs — ZERO DISCREPANCIES
</div>
---
1. Problem Statement
Manufacturing QA requires cross-referencing physical hang tag artwork against purchase order (PO) data to ensure Style #, Size, and UPC barcode accuracy before mass production. Manual verification of 21 styles × 41 UPCs across 13 image files and a 21-page PO PDF is error-prone and scales poorly.
---
2. System Architecture
Layer	Component	Input	Output
Ingestion	File Parser	13× JPG hang tags + 1× PDF PO	Raw image bytes + extracted text
Extraction	OCR / Visual Reader	High-res artwork images	Structured `{style, size, upc}` tuples
Normalization	Data Cleaner	Raw extracted strings	Canonical 12-digit UPCs, normalized sizes
Comparison	Diff Engine	Hang tag tuples ↔ PO tuples	Match / Mismatch / Missing flags
Review	Human-in-the-Loop	Flagged discrepancies	Re-examined, corrected verdicts
Report	Doc Generator	Final verified dataset	PDF design doc
---
3. Data Extraction Pipeline
3.1 Hang Tag Extraction
Each hang tag image contains 1 front panel + 1–3 back panels (one per size).
Field	Location	Format Example
STYLE/MODEL	Back panel header	`PJ60325-BE`
SIZE/TAILLE	Below style #	`XS`, `S`, `M`
UPC Barcode	Below size label	EAN-12: `840243561346`
Brand Info	Below barcode	`PET POSSE / RN#163699`
Images processed:
`PO#9626 狗衣服吊牌-01.jpg` through `-10.jpg` (dog clothes, 3 sizes each)
`PO#9626 单层狗毯吊牌30X40.jpg` (single-layer blankets, 6 styles)
`PO#9626 双层狗毯卡头40X50.jpg` (double-layer blankets, 5 styles)
3.2 PO Extraction
PO PDF is 21 pages; each style occupies 1 page with a Size Breakdown table.
Field	Location	Format Example
Style #	Page header	`PJ60325-BE`
Size	Size Breakdown column	`XS`, `S`, `M` (or `30×40`, `40×50`)
UPC	Per-size row	`840243561346`
Description	Below style #	`Brown All over word Fleece`
---
4. Comparison Algorithm
```
Step 1: PO Index Build      → HashMap<(style, size) → upc> from PDF
Step 2: Hang Tag Index Build → HashMap<(style, size) → upc> from images
Step 3: Inner Join           → For each key in HT, lookup PO; flag MISSING if absent
Step 4: UPC Compare          → String equality check; normalize whitespace first
Step 5: Discrepancy Review   → Human re-examines flagged items at pixel level
Step 6: Correction & Commit  → Update verdict; regenerate report
```
Key design decision: Join key is `(style_number, size)` — this ensures we compare UPCs for the exact same product variant, not just the same style family.
---
5. Lessons from Review & Re-Examination
The False Positive Incident
During initial pass, a false discrepancy was reported: an alleged "extra 1" in hang tag UPCs (e.g., `8402431561346` vs PO `840243561346`).
	Initial Reading	After Re-Examination
Perceived	`8-40243-1-56134-6` (extra "1" inserted)	❌ Incorrect
Actual	`8-40243-56134-6` (no extra digit)	✅ Correct
Root Cause: Optical misreading of barcode digit grouping. The human eye naturally segments 12-digit UPCs into groups. The digit "1" in "56134" was incorrectly perceived as an inserted character rather than part of the natural sequence.
Prevention: Future pipelines should enforce digit-by-digit OCR confidence scoring (≥95% per character) and display raw OCR output alongside human-readable grouping to prevent grouping bias.
> ⚠️ **CRITICAL:** Always re-examine flagged discrepancies at the individual digit level before reporting mismatches.
---
6. Final Verification Results
6.1 Summary
Metric	Value	Status
Total Styles in PO	21	✅
Styles Found in Hang Tags	21	✅
Styles Missing from Hang Tags	0	✅
Total UPCs Verified	41	✅
UPC Mismatches	0	✅
False Positives (corrected)	1	⚠️
6.2 Style Breakdown
Category	Styles	Sizes	UPCs	Result
Dog Clothes (PJ)	10	XS / S / M	30	✅ All Match
Blankets 30"×40" (BL)	6	30×40	6	✅ All Match
Blankets 40"×50" (BL)	5	40×50	5	✅ All Match
6.3 Complete Verified List
<details>
<summary><b>Click to expand: All 41 verified records</b></summary>
Style #	Size	Hang Tag UPC	PO UPC	Status
BL10502-BE	40×50	840243561223	840243561223	✅ MATCH
BL10503-BE	40×50	840243561230	840243561230	✅ MATCH
BL10528-BE	40×50	840243550937	840243550937	✅ MATCH
BL10531-BE	40×50	840243550951	840243550951	✅ MATCH
BL10533-BE	40×50	840243561247	840243561247	✅ MATCH
BL12000-BE	30×40	840243561254	840243561254	✅ MATCH
BL12001-BE	30×40	840243561261	840243561261	✅ MATCH
BL12002-BE	30×40	840243561278	840243561278	✅ MATCH
BL12003-BE	30×40	840243561285	840243561285	✅ MATCH
BL12004-BE	30×40	840243561292	840243561292	✅ MATCH
BL12005-BE	30×40	840243561308	840243561308	✅ MATCH
PJ30147-BE	XS	840243562671	840243562671	✅ MATCH
PJ30147-BE	S	840243562688	840243562688	✅ MATCH
PJ30147-BE	M	840243562695	840243562695	✅ MATCH
PJ30157-BE	XS	840243561827	840243561827	✅ MATCH
PJ30157-BE	S	840243561834	840243561834	✅ MATCH
PJ30157-BE	M	840243561841	840243561841	✅ MATCH
PJ35000-BE	XS	840243562404	840243562404	✅ MATCH
PJ35000-BE	S	840243562411	840243562411	✅ MATCH
PJ35000-BE	M	840243562428	840243562428	✅ MATCH
PJ37000-BE	XS	840243561858	840243561858	✅ MATCH
PJ37000-BE	S	840243561865	840243561865	✅ MATCH
PJ37000-BE	M	840243561872	840243561872	✅ MATCH
PJ37001-BE	XS	840243562435	840243562435	✅ MATCH
PJ37001-BE	S	840243562442	840243562442	✅ MATCH
PJ37001-BE	M	840243562459	840243562459	✅ MATCH
PJ60306-BE	XS	840243562466	840243562466	✅ MATCH
PJ60306-BE	S	840243562473	840243562473	✅ MATCH
PJ60306-BE	M	840243562480	840243562480	✅ MATCH
PJ60317-BE	XS	840243561315	840243561315	✅ MATCH
PJ60317-BE	S	840243561322	840243561322	✅ MATCH
PJ60317-BE	M	840243561339	840243561339	✅ MATCH
PJ60325-BE	XS	840243561346	840243561346	✅ MATCH
PJ60325-BE	S	840243561353	840243561353	✅ MATCH
PJ60325-BE	M	840243561360	840243561360	✅ MATCH
PJ60331-BE	XS	840243562497	840243562497	✅ MATCH
PJ60331-BE	S	840243562503	840243562503	✅ MATCH
PJ60331-BE	M	840243562510	840243562510	✅ MATCH
PJ60353-BE	XS	840243561377	840243561377	✅ MATCH
PJ60353-BE	S	840243561384	840243561384	✅ MATCH
PJ60353-BE	M	840243561391	840243561391	✅ MATCH
</details>
---
7. Recommendations for Production Deployment
7.1 Automated OCR Pipeline
Integrate Tesseract or cloud vision API with custom UPC barcode models. Validate EAN-12 checksum (mod-10) to catch transcription errors before comparison.
7.2 Confidence Thresholding
Reject any OCR result with per-character confidence < 95% for manual review. UPC digits are high-contrast; low confidence usually indicates image quality issues.
7.3 Structured Output Schema
Enforce JSON schema for all extractions to prevent free-text parsing ambiguities:
```json
{
  "style": "PJ60325-BE",
  "size": "XS",
  "upc": "840243561346",
  "upc_checksum_valid": true,
  "source": "hang_tag_image_01.jpg",
  "ocr_confidence": 0.98
}
```
7.4 Two-Pass Verification
First pass: Automated comparison
Second pass: Human review of ALL flagged items + random 5% sample of "matched" items to catch false negatives
7.5 Version Control
Store extracted data and image hashes in Git to enable audit trails and regression testing when artwork revisions occur.
---
— End of Document —
