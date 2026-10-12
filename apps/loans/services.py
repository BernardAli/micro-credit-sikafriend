from .models import Loan


def build_loan_statement(loan: Loan, borrower_display_name: str | None = None) -> str:
    name = borrower_display_name or loan.borrower.full_name

    lines: list[str] = []
    lines.append(f"{name}'s Loan Statement")
    lines.append(f"Customer ID: {loan.borrower.borrower_id}")
    lines.append(f"Portfolio: {loan.portfolio or 'Awaiting assignment'}")
    lines.append(f"Principal: GHS {loan.principal_amount}")
    lines.append(f"ROIC: GHS {loan.roic_amount}")
    lines.append(f"Total Expected Repayment: GHS {loan.total_expected_amount}")
    lines.append(f"Weekly payment: GHS {loan.weekly_payment}")
    lines.append(f"Total expected No. of payments: {loan.expected_payments_count}")
    lines.append("")

    payments = list(loan.payments.filter(is_void=False).order_by("payment_date", "id"))
    for idx, p in enumerate(payments, start=1):
        line = (
            f"{p.payment_date:%d/%m/%Y} payment: {idx}  "
            f"Amount: GHS {p.amount}  "
            f"Principal: GHS {p.principal_paid}  "
            f"ROIC: GHS {p.roic_paid}  "
            f"Customer credit held: GHS {p.customer_credit}"
        )
        if p.reference:
            line += f"  Ref: {p.reference}"
        lines.append(line)

    lines.append("")
    lines.append(f"Actual No. of payments: {loan.actual_payments_count}")
    lines.append(f"Outstanding No. of payment: {loan.outstanding_payments_count}")
    lines.append(f"Total paid: GHS {loan.total_paid_amount}")
    lines.append(f"Cash received: GHS {loan.total_cash_received}")
    lines.append(f"Customer credit held: GHS {loan.total_customer_credit}")
    lines.append(f"Total principal paid: GHS {loan.total_principal_paid}")
    lines.append(f"Total ROIC paid: GHS {loan.total_roic_paid}")
    lines.append(f"Principal outstanding: GHS {loan.principal_outstanding}")
    lines.append(f"ROIC outstanding: GHS {loan.roic_outstanding}")
    lines.append(f"Total outstanding: GHS {loan.balance_amount}")

    return "\n".join(lines)
