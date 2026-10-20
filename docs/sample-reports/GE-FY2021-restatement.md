# Compliance Audit Report - GENERAL ELECTRIC CO (GE)

- **Filing:** Form 10-K, fiscal year 2021 (period ended 2021-12-31), filed 2022-02-11
- **Accession:** [0000040545-22-000008](https://www.sec.gov/Archives/edgar/data/40545/000004054522000008/)
- **Job ID:** `2d73f97f7be3`
- **Data sources:** SEC EDGAR XBRL company facts (live); eCFR Title 17 (Regulations S-X, S-K, G; Exchange Act rules)
- **Drafted by:** template drafter (deterministic)

## Executive summary

**Overall assessment:** Satisfactory with observations.

11 automated checks were run against the XBRL financial data: 8 passed, 2 raised observations and 1 were not applicable to this filer's tagging.

## Observations

1. **Prior-year figures match the previously filed 10-K** (medium, warn). 3 prior-year figure(s) differ from the prior-year 10-K, indicating a restatement, reclassification or discontinued-operations recast that should be disclosed. Relevant provisions: 17 CFR 240.10D-1, 17 CFR 229.304.
2. **Year-over-year net income change** (medium, warn). Net income changed -214.3% year over year; Item 303 requires the MD&A to explain material changes. Relevant provisions: 17 CFR 229.303, 17 CFR 210.10-01.

## Recommended follow-up

- Confirm that recast prior-year amounts are labeled and that the nature of the restatement or reclassification is disclosed.
- Verify that MD&A explains the components driving the change in net income, as Item 303(b)(2) requires.

## Scope and limitations

This report is generated automatically from the company's XBRL-tagged financial data and the text of SEC regulations. It tests arithmetic consistency and disclosure triggers only; it is not an audit opinion under PCAOB standards and does not evaluate internal control over financial reporting, the narrative content of MD&A, or untagged disclosures.

## Appendix A - Check results and evidence

### [WARN] RESTATEMENT - Prior-year figures match the previously filed 10-K
*Severity: medium*  
3 prior-year figure(s) differ from the prior-year 10-K, indicating a restatement, reclassification or discontinued-operations recast that should be disclosed.

| Item | Value |
|---|---|
| prior_accession | 0000040545-21-000011 |
| differences | {"Revenues": {"originally_reported": 79619000000, "as_recast": 75833000000, "change_pct": -4.76}, "Assets": {"originally_reported": 253452000000, "as_recast": 256211000000, "change_pct": 1.09}, "NetCashProvidedByUsedInOperatingActivities": {"originally_reported": 3597000000, "as_recast": 3568000000, "change_pct": -0.81}} |
| split_adjusted | {"EarningsPerShareDiluted": {"originally_reported": 0.58, "as_recast": 4.63, "change_pct": 698.28, "split_ratio": "1-for-8 reverse split"}} |

Governing provisions:
- [17 CFR 240.10D-1](https://www.ecfr.gov/current/title-17/section-240.10D-1) - § 240.10D-1 Listing standards relating to recovery of erroneously awarded compensation. (relevance 1.00)
- [17 CFR 229.304](https://www.ecfr.gov/current/title-17/section-229.304) - § 229.304 (Item 304) Changes in and disagreements with accountants on accounting and financial disclosure. (relevance 0.96)
- [17 CFR 229.402](https://www.ecfr.gov/current/title-17/section-229.402) - § 229.402 (Item 402) Executive compensation. (relevance 0.95)

### [WARN] YOY_NET_INCOME - Year-over-year net income change
*Severity: medium*  
Net income changed -214.3% year over year; Item 303 requires the MD&A to explain material changes.

| Item | Value |
|---|---|
| concept | NetIncomeLoss |
| current | $-6.52B |
| prior | $5.70B |
| change_pct | -214.31 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 210.10-01](https://www.ecfr.gov/current/title-17/section-210.10-01) - § 210.10-01 Interim financial statements. (relevance 0.75)
- [17 CFR 210.11-02](https://www.ecfr.gov/current/title-17/section-210.11-02) - § 210.11-02 Preparation requirements. (relevance 0.74)

### [PASS] BS_COMPONENTS - Liabilities and equity components sum to the reported total
*Severity: info*  
Liabilities plus equity (including any temporary equity) equal the reported total.

| Item | Value |
|---|---|
| Liabilities | $157.26B |
| StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest | $41.61B |
| LiabilitiesAndStockholdersEquity | $198.87B |
| difference | $-148.0M |
| RedeemableNoncontrollingInterestEquityCarryingAmount | $148.0M |

Governing provisions:
- [17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/section-210.5-02) - § 210.5-02 Balance sheets. (relevance 1.00)
- [17 CFR 210.3-04](https://www.ecfr.gov/current/title-17/section-210.3-04) - § 210.3-04 Changes in stockholders' equity and noncontrolling interests. (relevance 0.87)

### [PASS] BS_IDENTITY - Balance sheet totals agree (assets = liabilities + equity)
*Severity: info*  
Total assets equal total liabilities and equity.

| Item | Value |
|---|---|
| Assets | $198.87B |
| LiabilitiesAndStockholdersEquity | $198.87B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/section-210.5-02) - § 210.5-02 Balance sheets. (relevance 1.00)
- [17 CFR 210.3-04](https://www.ecfr.gov/current/title-17/section-210.3-04) - § 210.3-04 Changes in stockholders' equity and noncontrolling interests. (relevance 0.83)

### [PASS] CASH_RECON - Cash flow sections reconcile to the change in cash
*Severity: info*  
Operating + investing + financing (+FX) equals the reported change in cash.

| Item | Value |
|---|---|
| CFO | $3.33B |
| CFI | $21.31B |
| CFF | $-45.18B |
| FX_effect | $-213.0M |
| CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect | $-20.75B |
| computed | $-20.75B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.3-02](https://www.ecfr.gov/current/title-17/section-210.3-02) - § 210.3-02 Consolidated statements of comprehensive income and cash flows. (relevance 1.00)
- [17 CFR 210.10-01](https://www.ecfr.gov/current/title-17/section-210.10-01) - § 210.10-01 Interim financial statements. (relevance 0.96)

### [PASS] EPS_DILUTED - Diluted EPS consistent with net income and diluted share count
*Severity: info*  
Implied diluted EPS matches the reported figure within rounding.

| Item | Value |
|---|---|
| NetIncomeLossAvailableToCommonStockholdersDiluted | $-6.77B |
| WeightedAverageNumberOfDilutedSharesOutstanding | $1.10B |
| EarningsPerShareDiluted | -6.16 |
| implied_eps | -6.16 |

Governing provisions:
- [17 CFR 210.5-03](https://www.ecfr.gov/current/title-17/section-210.5-03) - § 210.5-03 Statements of comprehensive income. (relevance 1.00)
- [17 CFR 210.11-02](https://www.ecfr.gov/current/title-17/section-210.11-02) - § 210.11-02 Preparation requirements. (relevance 0.97)

### [PASS] FILING_TIMELINESS - 10-K filed within the deadline for the filer's category
*Severity: info*  
Filed 42 days after fiscal year end; deadline for a large accelerated filer is 60 days.

| Item | Value |
|---|---|
| days_to_file | 42 |
| deadline_days | 60 |
| public_float | $116.50B |
| filer_category | large accelerated filer |
| filed | 2022-02-11 |
| period_end | 2021-12-31 |

Governing provisions:
- [17 CFR 240.12b-25](https://www.ecfr.gov/current/title-17/section-240.12b-25) - § 240.12b-25 Notification of inability to timely file all or any required portion of a Form 10-K, 20-F, 11-K, N-CEN , N-CSR, 10-Q, or 10-D. (relevance 1.00)
- [17 CFR 240.12b-2](https://www.ecfr.gov/current/title-17/section-240.12b-2) - § 240.12b-2 Definitions. (relevance 1.00)

### [PASS] LIQUIDITY - Liquidity and going-concern indicators
*Severity: info*  
Positive equity and operating cash flow; no going-concern indicators.

| Item | Value |
|---|---|
| StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest | $41.61B |
| CFO | $3.33B |
| current_ratio | 1.28 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 229.201](https://www.ecfr.gov/current/title-17/section-229.201) - § 229.201 (Item 201) Market price of and dividends on the registrant's common equity and related stockholder matters. (relevance 0.79)

### [PASS] XBRL_CONSISTENCY - No conflicting values tagged for the same fact
*Severity: info*  
Each key fact has a single value per period in this filing.

Governing provisions:
- [17 CFR 232.405](https://www.ecfr.gov/current/title-17/section-232.405) - § 232.405 Interactive Data File submissions. (relevance 1.00)
- [17 CFR 229.601](https://www.ecfr.gov/current/title-17/section-229.601) - § 229.601 (Item 601) Exhibits. (relevance 0.98)

### [PASS] YOY_REVENUE - Year-over-year revenue change
*Severity: info*  
Revenue changed -2.2% year over year (below the 20% review threshold).

| Item | Value |
|---|---|
| concept | Revenues |
| current | $74.20B |
| prior | $75.83B |
| change_pct | -2.16 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 229.304](https://www.ecfr.gov/current/title-17/section-229.304) - § 229.304 (Item 304) Changes in and disagreements with accountants on accounting and financial disclosure. (relevance 0.73)

### [N/A] GROSS_PROFIT - Gross profit equals revenue minus cost of revenue
*Severity: info*  
Revenue, cost of revenue or gross profit not all tagged (common for banks/insurers).


## Appendix B - Agent trace

| Agent | Pod | Note |
|---|---|---|
| gateway | gateway-1 | accepted |
| crosscheck | crosscheck-2 | 11 checks, 2 flagged, accn 0000040545-22-000008 |
| regulation | regulation-1 | round 0: 22 citations |
| reporter | reporter-1 | drafting with template drafter (deterministic) |