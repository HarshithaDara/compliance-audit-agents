# Document reader agent: Indian income-tax / GST evidence bundles

Status: approved by user 2026-10-20 ("ok" to the re-scoped plan)

## Goal

Audit a long (300–400 page) PDF that has no ticker, such as an individual proprietor's
income-tax remand / appeal submission. These bundles mix a written submission with annexures:
- the ITR acknowledgement and form;
- the AIS and TIS;
- GSTR-1 and GSTR-3B returns;
- tax invoices;
- bank statements;
- §194N cash-withdrawal certificates;
- agreements and assessment orders.

The system extracts the numbers, records the page each number came from, cross-checks the
sources against each other and against Indian tax law, and tests whether the written
submission explains each discrepancy. The output is the same kind of cited report the SEC
pipeline produces.

## Non-goals

- Company Schedule III financial statements. That would be a later parser set; the
  pipeline is built so it can be added.
- Legal advice or an assessment order. The report is a reviewer's checklist.
- Handwriting recognition. Scanned pages are OCR'd for classification and AI reading only.

## Architecture

```
browser --upload PDF--> gateway --(PDF bytes in Redis, 1h TTL)-->
   audit:document -> document agent -> audit:regulation -> regulation agent -> audit:report -> reporter
                     (extract, OCR,      (Indian corpus when      (template drafter for
                      classify, parse,    msg.kind == "document")  confidential docs)
                      checks, narrative)
```

- **New agent `agents/document/`.** It has its own Dockerfile and its own k8s Deployment. It
  consumes `audit:document` and produces findings in the existing `Finding` schema, then hands
  them to the existing regulation agent. Extraction and checks live in one agent, as in the
  crosscheck agent: checks need the whole fact set, and splitting them out would mean shipping
  every page's facts through Redis twice.
- **PDF transport.** The gateway stores the uploaded bytes at `audit:doc:<job>:pdf` with a
  1-hour TTL. The document agent deletes the key as soon as the text is extracted. No shared
  volume is needed, so the design works the same under compose, kind and local runs. The upload
  limit is `MAX_UPLOAD_MB`, default 64, and is enforced before anything is stored.
- **Message.** `AuditMessage` gains `kind` (`sec` | `document`) and a `document` context (file
  name, sha256, page count, AY, form, masked PAN, AI-reader mode, `allow_cloud`). `Finding`
  gains `evidence`: a list of `{page, printed_page, label, value, quote}`.

## Extraction (`agents/document/pdftext.py`, `classify.py`)

1. **Text.** Read each page with pypdf. A page with fewer than 25 characters of text is rendered
   with pypdfium2 and OCR'd with RapidOCR (ONNX, runs locally, no system install). Each page
   records its method: `text`, `ocr` or `empty`.
2. **Printed page numbers.** Bundles carry their own printed numbers, which differ from PDF
   indices. When the last numeric line on a page is plausible, it is recorded as `printed_page`.
   Evidence shows both numbers.
3. **Classification.** Each page is matched by content signatures, not by the annexure index,
   because indexes are often wrong:
   - `itr_ack`, `itr`, `computation`, `ais`, `tis`;
   - `gstr1`, `gstr3b`, `invoice`, `bank_statement`;
   - `cash_withdrawal_certificate`, `assessment_order`, `agreement`, `submission`, `other`.

   Continuation pages inherit the previous page's type when they carry that type's
   continuation markers. For example, AIS pages carry "Download ID" and GSTR-1 tables carry
   "No. of records".

## Parsers (`agents/document/parsers.py`)

Deterministic regex parsers emit `Fact(key, value, page, quote)`. Every fact quotes the exact
line it came from.

| Source | Facts |
|---|---|
| ITR ack | AY, form, filed-under section (139(1)/139(4)/…), filing date, total income, fee, taxes paid, refund |
| ITR form | 44AD gross receipts (total, digital, other mode), presumptive income, other-sources income, gross total income, Chapter VI-A, total income, tax at normal rates, 87A rebate, TDS2 rows (TAN, gross, TDS, head), TDS claimed total |
| AIS | per information code (TDS-194C/194H/194N, SFT-016, EXC-GSTR3B …): source, count, amount; detail rows (date, amount, TDS, Active/Inactive) |
| TIS | category → processed / accepted values |
| GSTR-1 | tax period, B2B 4A taxable value and tax |
| GSTR-3B | period, 3.1(a) taxable value and tax |
| Tax invoice | invoice ref, invoice date, service-month lines, taxable amount, net payable |
| Bank statement | transactions (date, narration, debit/credit inferred from the running balance), statement summary |
| 194N certificate | month, amount withdrawn, account (masked to last 4) |
| Assessment order | AY, returned income |

Account numbers and PAN are masked in facts. Raw page text never leaves the document agent.

## AI reader (`agents/document/llm.py`), switchable per document

| Mode | Behaviour |
|---|---|
| `local` (default) | Ollama at `OLLAMA_URL` (model `OLLAMA_MODEL`, default `qwen2.5:3b`). If Ollama is unreachable the job continues rules-only and the report says so. |
| `claude` | Uses the Anthropic API. Only allowed when the uploader picks it **and** `ANTHROPIC_API_KEY` is set; otherwise the upload is rejected with 400. |
| `none` | Rules-only parsing. |

The AI reader has two jobs:
- **Key figures on unrecognised pages** (`other`, `assessment_order`, `agreement`, OCR pages; at
  most `DOC_LLM_MAX_PAGES`). It returns `{label, value, quote}` per page. A grounding validator
  keeps a figure only if its number appears on that page's text, so a hallucinated number cannot
  enter the report.
- **Judging narrative coverage.** It decides whether a submission passage addresses a given
  discrepancy. It can only promote a keyword miss to "explained" when it quotes a sentence that
  exists on the page.

`allow_cloud` is true only in `claude` mode. The reporter uses the deterministic template drafter
whenever `allow_cloud` is false, so a confidential document is never sent to Claude by the
reporter either. Logs carry job ids and counts, never file names or page text.

## Checks (`agents/document/checks.py`)

Every finding carries evidence with page numbers. Tolerance is the larger of ₹1,000 and 0.5%,
unless stated otherwise.

| ID | Check |
|---|---|
| TURNOVER_AIS_VS_ITR | AIS/TIS business receipts (194C + 194H, active rows) vs ITR gross receipts |
| TURNOVER_GST_VS_ITR | GSTR-3B annual taxable value (and AIS EXC-GSTR3B) vs ITR gross receipts. When invoices are present, the turnover is re-bucketed by *service month*: if that explains the gap, the finding says "timing difference: GST is reported by invoice date". |
| GSTR1_VS_GSTR3B | month-by-month taxable value |
| INVOICES_VS_GSTR1 | sum of invoices by invoice-date month vs GSTR-1 B2B value |
| OTHER_INCOME_OMITTED | AIS SFT-016 interest (savings + deposits) vs ITR income from other sources; computes the tax effect after the §80TTA deduction and the §87A rebate |
| TDS_CREDIT | ITR TDS claimed vs AIS TDS deducted (active rows), per section |
| TDS_HEAD | TDS2 rows booked under a head with no income (e.g. head OS while other-sources income is 0) |
| PRESUMPTIVE_44AD | rate ≥ 6% digital / 8% other; turnover within the ₹2 crore limit (₹3 crore from AY 2024-25 when cash receipts are ≤ 5%); §44AD(6) exclusion risk when receipts are reported as commission (194H) or the submission describes commission/agency income |
| AUDIT_44AB | turnover vs the §44AB thresholds (₹1 crore; ₹10 crore when cash ≤ 5%) |
| TAX_COMPUTATION | recomputes old-regime slab tax on total income and the §87A rebate; compares with the ITR |
| LATE_FILING | filed under 139(4) / after the due date; checks the §234F fee (₹1,000 when total income ≤ ₹5 lakh, else ₹5,000) |
| CASH_WITHDRAWAL_194N | AIS 194N withdrawals above ₹1 crore with zero TDS; WLATMO certificates on file for every month that has withdrawals; certificate totals vs AIS monthly totals |
| BANK_STATEMENT_INTEGRITY | parsed debits/credits vs the statement summary, and opening + credits − debits = closing |
| BANK_THIRD_PARTY_CREDITS | credits not from the declared payer (above ₹50,000, or cash deposits). These are flagged as needing a source explanation (§68 risk). |
| NARRATIVE_COVERAGE | for every WARN/FAIL above: does the written submission address it? It lists the pages that do, and the discrepancies left unexplained. |

A check that lacks its inputs returns `not_applicable` and names the missing document.

## Indian rule corpus (`scraper/scrape_india_tax.py`)

The sources below are scraped and are all official:
- Memoranda explaining the Finance Bills (indiabudget.gov.in, 2016-17 … 2024-25). They
  explain the amendments to §44AD, §44AB, §194N, §234F, §87A and others.
- The Finance (No. 2) Bill 2019, which contains the text that inserted §194N.
- The CGST Act 2017, from the India Code DSpace API.

incometaxindia.gov.in and indiankanoon.org return 403 to automated clients and are not used.

Records are keyed by statutory section (`ITA-44AD`, `CGST-39`), so the retriever returns one hit
per section. The best chunk among all memoranda that discuss that section supplies the excerpt.
Citations look like `Income-tax Act, 1961 s.44AD`, and the source URL is the PDF with `#page=N`.
The corpus has its own index (`data/index_in/`). The regulation agent picks the retriever by
`msg.kind`. Pinning resolves "section 44AD" in a query directly to that section.

## Gateway and UI

- **`POST /documents`.** Accepts multipart `file` and `ai_reader` (`local` | `claude` | `none`).
  It checks the `%PDF-` magic bytes and the size limit, then returns 202 with `job_id`. Status
  and report use the existing `/audits/{id}` endpoints.
- **UI.** A second tab, "Audit a document (PDF)", with a file picker and an AI-reader choice. It
  says "stays on this computer" for local/none and "sent to Anthropic" for Claude. The pipeline
  view adds the `reading_document` and `checking_document` stages, and finding cards show the
  page references.

## Testing

- Unit tests use synthetic page texts that mimic the real layouts (fake taxpayer, fake PAN,
  different numbers), covering the parsers, the classification and each check.
- A generated PDF (fpdf2) covers the pypdf path, the printed-page detection and the OCR fallback.
  The OCR engine is stubbed so CI stays fast.
- Pipeline tests over fakeredis: upload → document agent → regulation (Indian corpus, BM25) →
  reporter, plus these failure modes:
  - a non-PDF or oversized upload;
  - claude mode without a key;
  - the PDF blob expiring before pickup;
  - the template drafter being forced when `allow_cloud` is false.
- A local-only test runs against `data/private/*.pdf` when present. Its expected values live in
  the git-ignored `data/private/expected.json`. It is skipped in CI.
- The real document and anything extracted from it are never committed (`data/private/` is
  git-ignored).

## Error handling

- PDF missing or expired, or unreadable/encrypted: the job fails without retry and gives the
  reason.
- Ollama down: continue rules-only and note it in the trace and the report. A Claude API error
  in claude mode is handled the same way.
- OCR engine missing: OCR'd pages are reported as `empty`, and the coverage section counts them.
