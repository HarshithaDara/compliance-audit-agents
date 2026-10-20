# Compliance Audit Report - NVIDIA CORP (NVDA)

- **Filing:** Form 10-K, fiscal year 2022 (period ended 2022-01-30), filed 2022-03-18
- **Accession:** [0001045810-22-000036](https://www.sec.gov/Archives/edgar/data/1045810/000104581022000036/)
- **Job ID:** `633bc20247e7`
- **Data sources:** SEC EDGAR XBRL company facts (live); eCFR Title 17 (Regulations S-X, S-K, G; Exchange Act rules)
- **Drafted by:** template drafter (deterministic)

## Executive summary

**Overall assessment:** Satisfactory with observations.

11 automated checks were run against the XBRL financial data: 9 passed, 2 raised observations and 0 were not applicable to this filer's tagging.

## Observations

1. **Year-over-year net income change** (medium, warn). Net income changed +125.1% year over year; Item 303 requires the MD&A to explain material changes. Relevant provisions: 17 CFR 229.303, 17 CFR 210.10-01.
2. **Year-over-year revenue change** (medium, warn). Revenue changed +61.4% year over year; Item 303 requires the MD&A to explain material changes. Relevant provisions: 17 CFR 229.303, 17 CFR 229.304.

## Recommended follow-up

- Verify that MD&A explains the components driving the change in net income, as Item 303(b)(2) requires.
- Verify that MD&A quantifies and explains the drivers of the revenue change, as Item 303(b)(2) requires.

## Scope and limitations

This report is generated automatically from the company's XBRL-tagged financial data and the text of SEC regulations. It tests arithmetic consistency and disclosure triggers only; it is not an audit opinion under PCAOB standards and does not evaluate internal control over financial reporting, the narrative content of MD&A, or untagged disclosures.

## Appendix A - Check results and evidence

### [WARN] YOY_NET_INCOME - Year-over-year net income change
*Severity: medium*  
Net income changed +125.1% year over year; Item 303 requires the MD&A to explain material changes.

| Item | Value |
|---|---|
| concept | NetIncomeLoss |
| current | $9.75B |
| prior | $4.33B |
| change_pct | 125.12 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 210.10-01](https://www.ecfr.gov/current/title-17/section-210.10-01) - § 210.10-01 Interim financial statements. (relevance 0.75)
- [17 CFR 210.11-02](https://www.ecfr.gov/current/title-17/section-210.11-02) - § 210.11-02 Preparation requirements. (relevance 0.74)

### [WARN] YOY_REVENUE - Year-over-year revenue change
*Severity: medium*  
Revenue changed +61.4% year over year; Item 303 requires the MD&A to explain material changes.

| Item | Value |
|---|---|
| concept | Revenues |
| current | $26.91B |
| prior | $16.68B |
| change_pct | 61.40 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 229.304](https://www.ecfr.gov/current/title-17/section-229.304) - § 229.304 (Item 304) Changes in and disagreements with accountants on accounting and financial disclosure. (relevance 0.73)
- [17 CFR 229.302](https://www.ecfr.gov/current/title-17/section-229.302) - § 229.302 (Item 302) Supplementary financial information. (relevance 0.67)

### [PASS] BS_COMPONENTS - Liabilities and equity components sum to the reported total
*Severity: info*  
Liabilities plus equity (including any temporary equity) equal the reported total.

| Item | Value |
|---|---|
| Liabilities | $17.57B |
| StockholdersEquity | $26.61B |
| LiabilitiesAndStockholdersEquity | $44.19B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/section-210.5-02) - § 210.5-02 Balance sheets. (relevance 1.00)
- [17 CFR 210.3-04](https://www.ecfr.gov/current/title-17/section-210.3-04) - § 210.3-04 Changes in stockholders' equity and noncontrolling interests. (relevance 0.87)

### [PASS] BS_IDENTITY - Balance sheet totals agree (assets = liabilities + equity)
*Severity: info*  
Total assets equal total liabilities and equity.

| Item | Value |
|---|---|
| Assets | $44.19B |
| LiabilitiesAndStockholdersEquity | $44.19B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/section-210.5-02) - § 210.5-02 Balance sheets. (relevance 1.00)
- [17 CFR 210.3-04](https://www.ecfr.gov/current/title-17/section-210.3-04) - § 210.3-04 Changes in stockholders' equity and noncontrolling interests. (relevance 0.83)

### [PASS] CASH_RECON - Cash flow sections reconcile to the change in cash
*Severity: info*  
Operating + investing + financing (+FX) equals the reported change in cash.

| Item | Value |
|---|---|
| CFO | $9.11B |
| CFI | $-9.83B |
| CFF | $1.86B |
| CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect | $1.14B |
| computed | $1.14B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.3-02](https://www.ecfr.gov/current/title-17/section-210.3-02) - § 210.3-02 Consolidated statements of comprehensive income and cash flows. (relevance 1.00)
- [17 CFR 210.10-01](https://www.ecfr.gov/current/title-17/section-210.10-01) - § 210.10-01 Interim financial statements. (relevance 0.96)

### [PASS] EPS_DILUTED - Diluted EPS consistent with net income and diluted share count
*Severity: info*  
Implied diluted EPS matches the reported figure within rounding.

| Item | Value |
|---|---|
| NetIncomeLoss | $9.75B |
| WeightedAverageNumberOfDilutedSharesOutstanding | $2.54B |
| EarningsPerShareDiluted | 3.85 |
| implied_eps | 3.85 |

Governing provisions:
- [17 CFR 210.5-03](https://www.ecfr.gov/current/title-17/section-210.5-03) - § 210.5-03 Statements of comprehensive income. (relevance 1.00)
- [17 CFR 210.11-02](https://www.ecfr.gov/current/title-17/section-210.11-02) - § 210.11-02 Preparation requirements. (relevance 0.97)

### [PASS] FILING_TIMELINESS - 10-K filed within the deadline for the filer's category
*Severity: info*  
Filed 47 days after fiscal year end; deadline for a large accelerated filer is 60 days.

| Item | Value |
|---|---|
| days_to_file | 47 |
| deadline_days | 60 |
| public_float | $467.25B |
| filer_category | large accelerated filer |
| filed | 2022-03-18 |
| period_end | 2022-01-30 |

Governing provisions:
- [17 CFR 240.12b-25](https://www.ecfr.gov/current/title-17/section-240.12b-25) - § 240.12b-25 Notification of inability to timely file all or any required portion of a Form 10-K, 20-F, 11-K, N-CEN , N-CSR, 10-Q, or 10-D. (relevance 1.00)
- [17 CFR 240.12b-2](https://www.ecfr.gov/current/title-17/section-240.12b-2) - § 240.12b-2 Definitions. (relevance 1.00)

### [PASS] GROSS_PROFIT - Gross profit equals revenue minus cost of revenue
*Severity: info*  
Revenue less cost of revenue equals reported gross profit.

| Item | Value |
|---|---|
| Revenues | $26.91B |
| CostOfRevenue | $9.44B |
| GrossProfit | $17.48B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.5-03](https://www.ecfr.gov/current/title-17/section-210.5-03) - § 210.5-03 Statements of comprehensive income. (relevance 1.00)
- [17 CFR 210.8-03](https://www.ecfr.gov/current/title-17/section-210.8-03) - § 210.8-03 Interim financial statements. (relevance 0.95)

### [PASS] LIQUIDITY - Liquidity and going-concern indicators
*Severity: info*  
Positive equity and operating cash flow; no going-concern indicators.

| Item | Value |
|---|---|
| StockholdersEquity | $26.61B |
| CFO | $9.11B |
| current_ratio | 6.65 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 229.201](https://www.ecfr.gov/current/title-17/section-229.201) - § 229.201 (Item 201) Market price of and dividends on the registrant's common equity and related stockholder matters. (relevance 0.79)

### [PASS] RESTATEMENT - Prior-year figures match the previously filed 10-K
*Severity: info*  
Key prior-year figures match those in the prior-year 10-K. Per-share amounts were retroactively adjusted for a stock split (4-for-1 split), which is not a restatement.

| Item | Value |
|---|---|
| prior_accession | 0001045810-21-000010 |
| split_adjusted | {"EarningsPerShareDiluted": {"originally_reported": 6.9, "as_recast": 1.73, "change_pct": -74.93, "split_ratio": "4-for-1 split"}} |

Governing provisions:
- [17 CFR 240.10D-1](https://www.ecfr.gov/current/title-17/section-240.10D-1) - § 240.10D-1 Listing standards relating to recovery of erroneously awarded compensation. (relevance 1.00)
- [17 CFR 229.304](https://www.ecfr.gov/current/title-17/section-229.304) - § 229.304 (Item 304) Changes in and disagreements with accountants on accounting and financial disclosure. (relevance 0.96)

### [PASS] XBRL_CONSISTENCY - No conflicting values tagged for the same fact
*Severity: info*  
Each key fact has a single value per period in this filing.

Governing provisions:
- [17 CFR 232.405](https://www.ecfr.gov/current/title-17/section-232.405) - § 232.405 Interactive Data File submissions. (relevance 1.00)
- [17 CFR 229.601](https://www.ecfr.gov/current/title-17/section-229.601) - § 229.601 (Item 601) Exhibits. (relevance 0.98)


## Appendix B - Agent trace

| Agent | Pod | Note |
|---|---|---|
| gateway | gateway-1 | accepted |
| crosscheck | crosscheck-2 | 11 checks, 2 flagged, accn 0001045810-22-000036 |
| regulation | regulation-1 | round 0: 24 citations |
| reporter | reporter-1 | drafting with template drafter (deterministic) |