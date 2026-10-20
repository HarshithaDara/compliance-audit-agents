# Compliance Audit Report - Apple Inc. (AAPL)

- **Filing:** Form 10-K, fiscal year 2025 (period ended 2025-09-27), filed 2025-10-31
- **Accession:** [0000320193-25-000079](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/)
- **Job ID:** `4f1a07edb6a9`
- **Data sources:** SEC EDGAR XBRL company facts (live); eCFR Title 17 (Regulations S-X, S-K, G; Exchange Act rules)
- **Drafted by:** template drafter (deterministic)

## Executive summary

**Overall assessment:** Satisfactory - no exceptions.

11 automated checks were run against the XBRL financial data: 10 passed, 1 raised observations and 0 were not applicable to this filer's tagging.

## Observations

1. **Liquidity and going-concern indicators** (low, warn). Indicators present: current ratio 0.89 below 1.0. Liquidity discussion in MD&A should address these. Relevant provisions: 17 CFR 229.303, 17 CFR 229.201.

## Recommended follow-up

- Confirm that the liquidity and capital resources discussion addresses the flagged indicators.

## Scope and limitations

This report is generated automatically from the company's XBRL-tagged financial data and the text of SEC regulations. It tests arithmetic consistency and disclosure triggers only; it is not an audit opinion under PCAOB standards and does not evaluate internal control over financial reporting, the narrative content of MD&A, or untagged disclosures.

## Appendix A - Check results and evidence

### [WARN] LIQUIDITY - Liquidity and going-concern indicators
*Severity: low*  
Indicators present: current ratio 0.89 below 1.0. Liquidity discussion in MD&A should address these.

| Item | Value |
|---|---|
| StockholdersEquity | $73.73B |
| CFO | $111.48B |
| current_ratio | 0.89 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 229.201](https://www.ecfr.gov/current/title-17/section-229.201) - § 229.201 (Item 201) Market price of and dividends on the registrant's common equity and related stockholder matters. (relevance 0.79)
- [17 CFR 229.601](https://www.ecfr.gov/current/title-17/section-229.601) - § 229.601 (Item 601) Exhibits. (relevance 0.46)

### [PASS] BS_COMPONENTS - Liabilities and equity components sum to the reported total
*Severity: info*  
Liabilities plus equity (including any temporary equity) equal the reported total.

| Item | Value |
|---|---|
| Liabilities | $285.51B |
| StockholdersEquity | $73.73B |
| LiabilitiesAndStockholdersEquity | $359.24B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/section-210.5-02) - § 210.5-02 Balance sheets. (relevance 1.00)
- [17 CFR 210.3-04](https://www.ecfr.gov/current/title-17/section-210.3-04) - § 210.3-04 Changes in stockholders' equity and noncontrolling interests. (relevance 0.87)

### [PASS] BS_IDENTITY - Balance sheet totals agree (assets = liabilities + equity)
*Severity: info*  
Total assets equal total liabilities and equity.

| Item | Value |
|---|---|
| Assets | $359.24B |
| LiabilitiesAndStockholdersEquity | $359.24B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/section-210.5-02) - § 210.5-02 Balance sheets. (relevance 1.00)
- [17 CFR 210.3-04](https://www.ecfr.gov/current/title-17/section-210.3-04) - § 210.3-04 Changes in stockholders' equity and noncontrolling interests. (relevance 0.83)

### [PASS] CASH_RECON - Cash flow sections reconcile to the change in cash
*Severity: info*  
Operating + investing + financing (+FX) equals the reported change in cash.

| Item | Value |
|---|---|
| CFO | $111.48B |
| CFI | $15.20B |
| CFF | $-120.69B |
| CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect | $5.99B |
| computed | $5.99B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.3-02](https://www.ecfr.gov/current/title-17/section-210.3-02) - § 210.3-02 Consolidated statements of comprehensive income and cash flows. (relevance 1.00)
- [17 CFR 210.10-01](https://www.ecfr.gov/current/title-17/section-210.10-01) - § 210.10-01 Interim financial statements. (relevance 0.96)

### [PASS] EPS_DILUTED - Diluted EPS consistent with net income and diluted share count
*Severity: info*  
Implied diluted EPS matches the reported figure within rounding.

| Item | Value |
|---|---|
| NetIncomeLoss | $112.01B |
| WeightedAverageNumberOfDilutedSharesOutstanding | $15.00B |
| EarningsPerShareDiluted | 7.46 |
| implied_eps | 7.46 |

Governing provisions:
- [17 CFR 210.5-03](https://www.ecfr.gov/current/title-17/section-210.5-03) - § 210.5-03 Statements of comprehensive income. (relevance 1.00)
- [17 CFR 210.11-02](https://www.ecfr.gov/current/title-17/section-210.11-02) - § 210.11-02 Preparation requirements. (relevance 0.97)

### [PASS] FILING_TIMELINESS - 10-K filed within the deadline for the filer's category
*Severity: info*  
Filed 34 days after fiscal year end; deadline for a large accelerated filer is 60 days.

| Item | Value |
|---|---|
| days_to_file | 34 |
| deadline_days | 60 |
| public_float | $3,253.43B |
| filer_category | large accelerated filer |
| filed | 2025-10-31 |
| period_end | 2025-09-27 |

Governing provisions:
- [17 CFR 240.12b-25](https://www.ecfr.gov/current/title-17/section-240.12b-25) - § 240.12b-25 Notification of inability to timely file all or any required portion of a Form 10-K, 20-F, 11-K, N-CEN , N-CSR, 10-Q, or 10-D. (relevance 1.00)
- [17 CFR 240.12b-2](https://www.ecfr.gov/current/title-17/section-240.12b-2) - § 240.12b-2 Definitions. (relevance 1.00)

### [PASS] GROSS_PROFIT - Gross profit equals revenue minus cost of revenue
*Severity: info*  
Revenue less cost of revenue equals reported gross profit.

| Item | Value |
|---|---|
| RevenueFromContractWithCustomerExcludingAssessedTax | $416.16B |
| CostOfGoodsAndServicesSold | $220.96B |
| GrossProfit | $195.20B |
| difference | 0 |

Governing provisions:
- [17 CFR 210.5-03](https://www.ecfr.gov/current/title-17/section-210.5-03) - § 210.5-03 Statements of comprehensive income. (relevance 1.00)
- [17 CFR 210.8-03](https://www.ecfr.gov/current/title-17/section-210.8-03) - § 210.8-03 Interim financial statements. (relevance 0.95)

### [PASS] RESTATEMENT - Prior-year figures match the previously filed 10-K
*Severity: info*  
Key prior-year figures match those in the prior-year 10-K.

| Item | Value |
|---|---|
| prior_accession | 0000320193-24-000123 |

Governing provisions:
- [17 CFR 240.10D-1](https://www.ecfr.gov/current/title-17/section-240.10D-1) - § 240.10D-1 Listing standards relating to recovery of erroneously awarded compensation. (relevance 1.00)
- [17 CFR 229.304](https://www.ecfr.gov/current/title-17/section-229.304) - § 229.304 (Item 304) Changes in and disagreements with accountants on accounting and financial disclosure. (relevance 0.96)

### [PASS] XBRL_CONSISTENCY - No conflicting values tagged for the same fact
*Severity: info*  
Each key fact has a single value per period in this filing.

Governing provisions:
- [17 CFR 232.405](https://www.ecfr.gov/current/title-17/section-232.405) - § 232.405 Interactive Data File submissions. (relevance 1.00)
- [17 CFR 229.601](https://www.ecfr.gov/current/title-17/section-229.601) - § 229.601 (Item 601) Exhibits. (relevance 0.98)

### [PASS] YOY_NET_INCOME - Year-over-year net income change
*Severity: info*  
Net income changed +19.5% year over year (below the 20% review threshold).

| Item | Value |
|---|---|
| concept | NetIncomeLoss |
| current | $112.01B |
| prior | $93.74B |
| change_pct | 19.50 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 210.10-01](https://www.ecfr.gov/current/title-17/section-210.10-01) - § 210.10-01 Interim financial statements. (relevance 0.75)

### [PASS] YOY_REVENUE - Year-over-year revenue change
*Severity: info*  
Revenue changed +6.4% year over year (below the 20% review threshold).

| Item | Value |
|---|---|
| concept | RevenueFromContractWithCustomerExcludingAssessedTax |
| current | $416.16B |
| prior | $391.04B |
| change_pct | 6.43 |

Governing provisions:
- [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) - § 229.303 (Item 303) Management's discussion and analysis of financial condition and results of operations. (relevance 1.00)
- [17 CFR 229.304](https://www.ecfr.gov/current/title-17/section-229.304) - § 229.304 (Item 304) Changes in and disagreements with accountants on accounting and financial disclosure. (relevance 0.73)


## Appendix B - Agent trace

| Agent | Pod | Note |
|---|---|---|
| gateway | gateway-1 | accepted |
| crosscheck | crosscheck-1 | 11 checks, 1 flagged, accn 0000320193-25-000079 |
| regulation | regulation-1 | round 0: 23 citations |
| reporter | reporter-1 | drafting with template drafter (deterministic) |