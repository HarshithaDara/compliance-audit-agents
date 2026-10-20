"""Synthetic page texts in the layouts of real Indian income-tax / GST bundles (as the PDF text
layer renders them). The taxpayer, identifiers and numbers are invented; no real document's data
is used in tests."""
from __future__ import annotations

from agents.document.pdftext import Page

PAN = "ABCDE1234F"
TAN = "HYDS01234A"
MONTHS = ["April", "May", "June", "July", "August", "September", "October", "November", "December",
          "January", "February", "March"]
# Taxable value per GST period (invoice-date month), April 2022 .. March 2023.
GST_MONTHLY = [100000.00, 200000.00, 210000.00, 205000.00, 198000.00, 202000.00,
               195000.00, 207000.00, 203000.00, 199000.00, 201000.00, 200000.00]


def ind(n: float) -> str:
    """Indian grouping as printed on returns: 2420000 -> 24,20,000; keeps paise when present."""
    whole = int(n)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    frac = round(n - whole, 2)
    return s + (f"{frac:.2f}"[1:] if frac else "")


def itr_ack(total_income=420000, filed="139(4)- After due date", date="15-Dec-2023", fee=1000, tds=24220,
            refund=23220) -> str:
    return f"""Acknowledgement Number:111122223333444 Date of filing : {date}
INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT
Assessment
Year
2023-24
PAN {PAN}
Name SYNTHETIC TRADER
Status Individual Form Number ITR-3
Filed u/s {filed} e-Filing Acknowledgement Number 111122223333444
Current Year business loss, if any 1 0
Total Income 2 {ind(total_income)}
Net tax payable 5 0
Interest and Fee Payable 6 {ind(fee)}
Total tax, interest and Fee payable 7 {ind(fee)}
Taxes Paid 8 {ind(tds)}
(+) Tax Payable /(-) Refundable (7-8) 9 (-) {ind(refund)}
194"""


def itr_44ad(receipts=2420000, digital=None, other=0, presumptive=500000) -> str:
    digital = receipts - other if digital is None else digital
    return f"""Sl.
No. Name Of Business Business Code Description
1 synthetic trader
i Gross Turnover or Gross Receipts (ia+ib) 61i {ind(receipts)}
a
Through a/c payee cheque or a/c payee bank draft or bank electronic
clearing system received or other prescribed electronic modes before
specified date
ia {ind(digital)}
b Any other mode ib {ind(other)}
ii Presumptive income under section 44AD (iia + iib) 61ii {ind(presumptive)}
62 Computation of presumptive Business income under section 44ADA
i Gross Receipts 62i 0
Acknowledgement Number : 111122223333444 Date of Filing : 15-Dec-2023*
210"""


def itr_part_b_ti(other_sources=0, gti=500000, via=80000, total=420000) -> str:
    return f"""5 Income from other sources
a Net Income from Other sources chargeable to tax at NormalApplicable rates (6 of Schedule OS) (enter nil if loss) 5a {ind(other_sources)}
d Total (5a + 5b + 5c)(enter nil if loss) 5d {ind(other_sources)}
10 Gross Total income (8 - 9) (total of serial no (i) to (xiv) of column 5 of Schedule BFLA + 5b + 3iv) 10 {ind(gti)}
12 Deduction under chapter VI-A
c Total (12a +12b) [limited upto (10-11)] 12c {ind(via)}
14 Total income (10 - 12c-13) 14 {ind(total)}
PART B - TI
Acknowledgement Number : 111122223333444 Date of Filing : 15-Dec-2023*
262"""


def itr_tti(tax=8500, rebate=8500) -> str:
    return f"""PART B - TTI - COMPUTATION OF TAX LIABILITY ON TOTAL INCOME
2 Tax payable on total income
a Tax at normal rates on 17 of Part B-TI 2a {ind(tax)}
e Rebate under section 87A 2e {ind(rebate)}
Acknowledgement Number : 111122223333444 Date of Filing : 15-Dec-2023*
264"""


def itr_tds2(rows=((5000, 100000, "OS"), (19220, 2320000, "BP"))) -> str:
    lines = [f"{i} Self {TAN} 0 {ind(tds)} 0 0 {ind(tds)} 0 0 {ind(gross)} {head} 0"
             for i, (tds, gross, head) in enumerate(rows, 1)]
    total = sum(r[0] for r in rows)
    return "\n".join(["SCHEDULE TDS2 - DETAILS OF TAX DEDUCTED AT SOURCE (TDS) ON INCOME [AS PER FORM 16 A ISSUED BY DEDUCTOR(S)]",
                      *lines, f"TDS claimed in own hand(total of column 9) {ind(total)}", "267"])


def ais_pages(withdrawals=None, commission=(100000, 5000), contract=(2320000, 19220), sb_interest=1500,
              td_interest=0) -> list[str]:
    """Page 1 opens the 194N section, then prints 194H and 194C; 194N rows continue on page 2."""
    withdrawals = withdrawals if withdrawals is not None else [("2022-04-15", 4000000), ("2022-05-10", 3000000),
                                                              ("2022-06-20", 5000000), ("2022-07-12", 2500000)]
    total = sum(a for _, a in withdrawals)

    def row(i, d, amt, tds=0, status="Active"):
        y, m, day = d.split("-")
        q = {1: "Q4(Jan-Mar)", 2: "Q4(Jan-Mar)", 3: "Q4(Jan-Mar)", 4: "Q1(Apr-Jun)", 5: "Q1(Apr-Jun)", 6: "Q1(Apr-Jun)",
             7: "Q2(Jul-Sep)", 8: "Q2(Jul-Sep)", 9: "Q2(Jul-Sep)"}.get(int(m), "Q3(Oct-Dec)")
        return f"{i} {q} {day}/{m}/{y} {ind(amt)} {ind(tds)} {ind(tds)} {status}"
    first = withdrawals[:2]
    rest = withdrawals[2:]
    p1 = ["Download ID : ABCDE1234F202510021331", "Page 1 of 3",
          "Part B1-Information relating to tax deducted or collected at source",
          "SR.NO. INFORMATION CODE INFORMATION DESCRIPTION INFORMATION SOURCE COUNT AMOUNT",
          f"3 TDS-194N Cash withdrawals (Section 194N) SYNTHETIC BANK LIMITED (HYDS09999Z) {len(withdrawals)} {ind(total)}",
          "SR.NO. QUARTER DATE OF PAYMENT/CREDIT AMOUNT PAID/CREDITED TDS DEDUCTED TDS DEPOSITED STATUS"]
    p1 += [row(i, d, a) for i, (d, a) in enumerate(first, 1)]
    p1 += ["SR.NO. INFORMATION CODE INFORMATION DESCRIPTION INFORMATION SOURCE COUNT AMOUNT",
           f"2 TDS-194H Commission or brokerage received (Section 194H) SYNTHETIC PAYER LIMITED ({TAN}) 1 {ind(commission[0])}",
           row(1, "2022-09-21", commission[0], commission[1]),
           row(2, "2022-09-21", commission[0], commission[1], "Inactive"),
           "SR.NO. INFORMATION CODE INFORMATION DESCRIPTION INFORMATION SOURCE COUNT AMOUNT",
           f"1 TDS-194C Receipts from contract (Section 194C) SYNTHETIC PAYER LIMITED ({TAN}) 1 {ind(contract[0])}",
           row(1, "2023-03-31", contract[0], contract[1]),
           "Date of Birth", "01/01/1980", "Assessment Year 2023-24", "Annual Information Statement (AIS)", "271"]
    p2 = ["PAN", PAN, "Download ID : ABCDE1234F202510021331", "Page 2 of 3"]
    p2 += [row(i, d, a) for i, (d, a) in enumerate(rest, len(first) + 1)]
    p2 += ["Part B2-Information relating to specified financial transaction (SFT)",
           f"2 SFT-016(SB) Interest income (SFT-016) Savings SYNTHETIC BANK LIMITED (AAACS0000K.AB703) 1 {ind(sb_interest)}"]
    if td_interest:
        p2.append(f"1 SFT-016(TD) Interest income (SFT-016) Term Deposit SYNTHETIC POST (AP112) 1 {ind(td_interest)}")
    p2 += [f"1 EXC-GSTR3B Sales reported under GSTR-3B SYNTHETIC TRADER ({PAN}) 12 {ind(round(sum(GST_MONTHLY)))}", "272"]
    return ["\n".join(p1), "\n".join(p2)]


def tis_page(sb=1500, td=0, business=2420000, gst=None) -> str:
    gst = round(sum(GST_MONTHLY)) if gst is None else gst
    return f"""General Information
-------------------------------------------------------------------- Taxpayer Information Summary (TIS) --------------------------------------------------------------------
SR. NO. INFORMATION CATEGORY PROCESSED BY
1 Interest from savings bank {ind(sb)} {ind(sb)}
2 Interest from deposit {ind(td)} {ind(td)}
3 Business receipts {ind(business)} {ind(business)}
4 GST turnover {ind(gst)} {ind(gst)}
287"""


def gstr1_page(month: str, value: float, fy="2022-23") -> str:
    tax = round(value * 0.09, 2)
    return f"""FORM GSTR-1
[See rule 59(1)]
Details of outward supplies of goods or services
Financial year {fy}
Tax period {month}
1 GSTIN 36{PAN}1Z5
Description No. of records Document Type Value (₹) Integrated Tax (₹) Central Tax (₹) State/UT Tax (₹) Cess (₹)
4A - Taxable outward supplies made to registered persons (other than reverse charge supplies) - B2B Regular
Total 2 Invoice {ind(value)} 0.00 {ind(tax)} {ind(tax)} 0.00
4B - Taxable outward supplies made to registered persons attracting tax on reverse charge - B2B Reverse charge
Total 0 Invoice 0.00 0.00 0.00 0.00 0.00"""


def gstr3b_page(month: str, value: float, fy="2022-23") -> str:
    tax = round(value * 0.09, 2)
    return f"""Form GSTR-3B
[See rule 61(5)]
Year {fy}
Period {month}
GSTIN of the supplier 36{PAN}1Z5
3.1 Details of Outward supplies and inward supplies liable to reverse charge
(a) Outward taxable supplies (other than zero rated, nil rated and
exempted)
{value:.2f} 0.00 {tax:.2f} {tax:.2f} 0.00
(b) Outward taxable supplies (zero rated) 0.00 0.00 - - 0.00"""


def invoice_page(ref: str, date: str, lines: list[tuple[str, str, float]]) -> str:
    total = round(sum(v for *_, v in lines), 2)
    body = "\n".join(f"{i} {d} {m} {v}" for i, (d, m, v) in enumerate(lines, 1))
    return f"""Supplier SAP Code : S000001 Invoice No. :
Invoice Ref No : {ref} Invoice Date :
Supplier Information Customer Information
SYNTHETIC TRADER Synthetic Payer Limited
PAN No : {PAN} PAN No : AAACP0000Q
Sn. Month Taxable Value
{body}
Supplier Bank details as below :- TAXABLE AMOUNT Rs {total}
NET PAYABLE AMOUNT Rs {round(total * 1.18, 2)}
{ref}
{date}
TAX INVOICE"""


def invoices_by_service_month(values=None) -> list[str]:
    """One invoice per service month Apr-22..Mar-23, each dated on the 15th of the next month."""
    values = values or [200000.00, 210000.00, 205000.00, 198000.00, 202000.00, 195000.00, 207000.00, 203000.00,
                        199000.00, 201000.00, 200000.00, 200000.00]
    codes = ["APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "JAN", "FEB", "MAR"]
    dates = ["15-May-2022", "15-Jun-2022", "15-Jul-2022", "15-Aug-2022", "15-Sep-2022", "15-Oct-2022", "15-Nov-2022",
             "15-Dec-2022", "15-Jan-2023", "15-Feb-2023", "15-Mar-2023", "15-Apr-2023"]
    return [invoice_page(f"INV22{i:02d}", d, [("Cash Loading", c, v)]) for i, (c, d, v) in enumerate(zip(codes, dates, values))]


def bank_pages() -> list[str]:
    p1 = """SYNTHETIC BANK Ltd.                                      Page No .:   1                                          Statement of accounts
Account No :50100000001234   OTHER
Statement From  :  01/04/2022         To  :  31/03/2023
Date Narration Chq./Ref.No. Value Dt Withdrawal Amt. Deposit Amt. Closing Balance
05/04/22 POS 400000XXXXXX1111 FUEL STATION 0000209502796425 05/04/22 1000 9000
26/04/22 NEFT CR-ANZB0000001-SYNTHETIC PAYER LIMITED-SYNTHETIC TRADER-ANZBH22116244432 26/04/22 150000.50 159000.5
22/07/22 RTGS CR-BARB0SIRIPU-ACME ENTERPRISES-SYNTHETIC TRADER-BARBR52022072200960585BARBR5202207220096058522/07/22 300000 459000.5
22/07/22 RTGS DR-ANZB0000001-SECURITY DEPOSITHDFCR5202207228405356722/07/22 100000 359000.
178"""
    p2 = """Date Narration Chq./Ref.No. Value Dt Withdrawal Amt. Deposit Amt. Closing Balance
26/09/22 CASH DEPOSIT-XXXXXXXXXX1234-BRANCH - CITY0000000000005207 26/09/22 49000 408000.5
29/09/22 CASH DEP HOME BRN CHGS 280322-CDT2211508783039 29/09/22 59 407941.5
STATEMENT SUMMARY  :-
Opening Balance Debits Credits Closing Bal
10000 101059 499000.5 407941.5
179"""
    return [p1, p2]


def certificate_page(month: str, year: int, amount: int, account="1111222233334444") -> str:
    return f"""Date: 08-Sep-2022 Letter No: SYN / CP / {month.upper()} {year}/0226
To
The Branch Manager
SYNTHETIC BANK
Subject: No TDS @ 2% u/s 194N from Cash withdrawal for ATM Cash replenishment
Please note that during the month of {month.upper()} {year}, total sum of Rs {amount}.00 (Rs. some words
only) has been withdrawn from the account number {account} maintained with your bank for the purpose of
replenishing cash in the Automated Teller Machines operated by Synthetic WLA Ltd.
149"""


SUBMISSION = """SYNTHETIC TRADER
A.Y.2023-24
Remand Proceedings
The assessee respectfully submits that the receipts were commission and fees earned from the franchise.
The assessee offered income under section 44AD at 20.66% of gross receipts, which is higher than prescribed.
The withdrawals reflected in the bank account pertain to ATM replenishment, and the WLATMO issues a monthly
certificate to the bank confirming the withdrawals.
The assessee prays that the Annexure documents may kindly be taken on record.
4"""


def bundle(**overrides) -> list[Page]:
    """A complete synthetic bundle in page order. Pass a list under a key to replace that part."""
    parts = {
        "submission": [SUBMISSION],
        "invoices": invoices_by_service_month(),
        "gstr1": [gstr1_page(m, v) for m, v in zip(MONTHS, GST_MONTHLY)],
        "gstr3b": [gstr3b_page(m, v) for m, v in zip(MONTHS, GST_MONTHLY)],
        "certificates": [certificate_page("May", 2022, 3000000), certificate_page("Jun", 2022, 5000000)],
        "bank": bank_pages(),
        "itr": [itr_ack(), itr_44ad(), itr_part_b_ti(), itr_tti(), itr_tds2()],
        "ais": ais_pages(),
        "tis": [tis_page()],
    }
    parts.update(overrides)
    texts = [t for key in ("submission", "invoices", "gstr1", "gstr3b", "certificates", "bank", "itr", "ais", "tis")
             for t in parts[key]]
    return [Page(i, t, "text") for i, t in enumerate(texts, 1)]


def to_pdf(pages: list[str | None]) -> bytes:
    """A real PDF: text pages via fpdf2; None makes an image-only (scanned) page."""
    from fpdf import FPDF
    pdf = FPDF(orientation="L", format="A3")  # wide enough that no line wraps, like real statements
    pdf.set_font("helvetica", size=7)
    for text in pages:
        pdf.add_page()
        if text is None:
            pdf.rect(20, 20, 100, 60, style="F")  # no text layer
        else:  # the built-in font is latin-1 only
            pdf.multi_cell(0, 5, text.replace("₹", "Rs.").encode("latin-1", "replace").decode("latin-1"))
    return bytes(pdf.output())


def bundle_pdf() -> bytes:
    return to_pdf([p.text for p in bundle()])


# ------------------------------------------------------------------ case papers

def notice_page(ay="2023-24", asks_ledger=True) -> str:
    ledger = (" Further, you need to furnish the ledger account extract of all the persons from whom you have made "
              "transactions." if asks_ledger else "")
    return f"""GOVERNMENT OF INDIA
INCOME TAX DEPARTMENT
To, SYNTHETIC TRADER
PAN: {PAN}
Assessment Year: {ay}
Dated: 01/09/2026
Subject : Remand Report in the case of SYNTHETIC TRADER A.Y {ay} - Furnishing of documents - reg.
In this connection you are requested to submit all the documents listed as additional evidences i.e. Sl.No. 1 to 3
for verification. You are also requested to furnish the brief reasons for acceptance of these additional evidences.{ledger}
The above details may please be furnished on or before 18.09.2026."""


def evidence_index_page() -> str:
    return """ANNEXURES
S. No. Documents submitted as an Additional Evidence Annexure No. Page no's
1 Tax Invoices for the F.Y . 2022-23 1 5 - 16
2 Service agreement with Synthetic Payer Limited
dated 01.10.2023.
2 17 - 20
3 Bank statement 3 21 - 22
26"""


SUBMISSION_CASE = """SYNTHETIC TRADER
A.Y.2023-24
Remand Proceedings
2. REASON FOR FURNISHING THE DOCUMENTS AS ADDITIONAL EVIDENCE - SUFFICIENT CAUSE:
The assessee respectfully submits that the documents could not be produced before the Assessing Officer owing to a
medical exigency faced by the assessee, which was a sufficient cause beyond the control of the assessee.
It is particularly relevant that an identical issue was examined in the subsequent assessment year and the returned
income was accepted without any addition.
The bank accounts 111122223333 are maintained exclusively for the purpose of the franchise business and the
assessee has complied with this requirement in all respects.
The assessee earned commission and fees from the franchise and declared income at 20.66% of gross receipts.
5"""


def fee_receipt_page(amount: int, dates: list[str]) -> str:
    return f"""SYNTHETIC UNIVERSITY Fees Receipt
STUDENT NAME : A STUDENT
Received Fees as Per Following Particular Amount
Tuition Fee {ind(amount)} Total {ind(amount)} (Rupees in words)
{' '.join(dates)}"""


def order_pages(ay="2023-24", additions=(("Addition u/s 69A on account of unexplained bank credits", 1500000),),
                returned=420000) -> list[str]:
    rows = [f"1 Income as per ITR filed u/s 139 {ind(returned)}/-"]
    rows += [f"{i} {d} {ind(a)}/-" for i, (d, a) in enumerate(additions, 2)]
    total = returned + sum(a for _, a in additions)
    variation = "4. Cases where variation is proposed:" if additions else \
        "3. Cases where variation is not proposed:\nReason for inference drawn that no variation is required on this issue."
    return [f"""ASSESSMENT ORDER
4. Assessment Year {ay}
13. Order passed under section 143(3) read with section 144B of the Income-tax Act
14. Returned Income Rs. {ind(returned)}
ITBA/AST/S/143(3)/2025-26/1000000001(1)
{variation}
The bank statement shows total credits of Rs. 4,99,000 in the account and the assessee has shown total gross receipts at Rs. 24,20,000.""",
            f"""A.Y. {ay}
ITBA/AST/S/143(3)/2025-26/1000000001(1)
Subject to the above, the total income of the assessee is computed as under:
Sl No Description Amount (in INR)
{chr(10).join(rows)}
{len(rows) + 1} Assessed income {ind(total)}/-"""]


def case_bundle(**overrides) -> list[Page]:
    """The synthetic bundle as a remand response: notice, submission, evidence index, deduction receipts."""
    parts = {"notice": [notice_page()], "index": [evidence_index_page()], "submission": [SUBMISSION_CASE, SUBMISSION],
             "receipts": [fee_receipt_page(50000, ["15-06-2022"]), fee_receipt_page(20000, ["20-06-2024"])],
             "orders": order_pages(ay="2024-25", additions=())}
    parts.update({k: overrides.pop(k) for k in list(overrides) if k in parts})
    base = bundle(**overrides)
    texts = parts["notice"] + parts["submission"] + parts["index"] + [p.text for p in base[1:]] + parts["receipts"] + \
        parts["orders"]
    return [Page(i, t, "text") for i, t in enumerate(texts, 1)]
