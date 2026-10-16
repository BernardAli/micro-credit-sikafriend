"""Branded management PDF using the same bounded financial summaries as the dashboard."""
from decimal import Decimal
from html import escape
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from weasyprint import HTML
from apps.company.models import CompanyProfile
from apps.core.pdf import LocalPDFResources
from apps.core.export_limits import export_limit_response
from .dashboard_data import build_dashboard_context, quantize_amount


def _q(value):
    return quantize_amount(value)


def _ghs(value):
    return f"GHS {_q(value):,.2f}"


def _company_name():
    return escape(CompanyProfile.get_solo().company_name)


def business_state_pdf_report(request):
    if (limited := export_limit_response(request)) is not None:
        return limited
    today = timezone.localdate()
    context = build_dashboard_context(request.user, report=True)
    total_loans, active_loans, closed_loans, default_loans = (context[key] for key in ('total_loans','active_count','closed_count','default_count'))
    total_borrowers, active_borrowers, closed_borrowers, bad_borrowers = (context[key] for key in ('borrowers_count','borrower_active_count','borrower_closed_count','borrower_bad_count'))
    total_agents, agents_with_loans = context['agents_count'], context['agents_with_loans']
    total_disbursed, active_disbursed = context['total_disbursed'], context['active_disbursed']
    total_expected, active_expected, total_roic, active_roic = (context[key] for key in ('total_expected','active_expected','total_roic','active_roic'))
    total_collected, total_principal_collected, total_roic_collected = (context[key] for key in ('total_collected','total_principal_collected','total_roic_collected'))
    today_collected, week_collected, month_collected, month_disbursed = (context[key] for key in ('today_collected','week_collected','month_collected','month_disbursed'))
    loans_last_30_days = context['last_30_new_loans']
    total_outstanding = context['report_total_outstanding']
    active_outstanding, principal_outstanding, roic_outstanding = (context[key] for key in ('total_outstanding_active','total_principal_outstanding','total_roic_outstanding'))
    collection_rate, avg_loan_size, par_amount, par_count, par_rate = (context[key] for key in ('collections_rate','avg_loan_size','par_amount','par_count','par_rate'))
    category_summary = [{**row,'label':escape(row['label'])} for row in context['category_board']]
    agent_rows = [dict(name=escape(row['agent_name']), loans=row['loans_count'], borrowers=row['borrowers_count'], disbursed=row['disbursed'], expected=row['expected'], collected=row['collected'], balance=row['total_outstanding'], principal_out=row['principal_outstanding'], roic_out=row['roic_outstanding'], rate=row['collection_rate']) for row in context['report_agent_board']]
    top_risky_loans = [dict(id=loan.pk,borrower=escape(loan.borrower.full_name),agent=escape(loan.agent_name.name if loan.agent_name else '-'),category=escape(loan.get_loan_category_display()), status=escape(loan.status),borrower_status=escape(loan.borrower.status), balance=loan.balance_amount,overdue_weeks=loan.overdue_weeks) for loan in context['report_risk_loans']]
    borrower_rows = [dict(name=escape(row['borrower'].full_name), status=escape(row['borrower'].status), loans=row['total_loans'],disbursed=row['disbursed'],expected=row['expected'],collected=row['collected'],balance=row['total_outstanding']) for row in context['top_borrowers_outstanding'] if row['total_loans']]
    generated_at = context['generated_at']
    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        @page {{
          size: A4;
          margin: 18mm 14mm 18mm 14mm;
        }}
        body {{
          font-family: Arial, Helvetica, sans-serif;
          color: #0f172a;
          font-size: 11px;
          line-height: 1.45;
        }}
        .cover {{
          padding: 28px;
          border-radius: 20px;
          color: white;
          background:
            radial-gradient(circle at top right, rgba(14,165,233,.25), transparent 30%),
            radial-gradient(circle at left center, rgba(37,99,235,.18), transparent 28%),
            linear-gradient(135deg, #0f172a 0%, #1e3a8a 52%, #0ea5e9 100%);
          margin-bottom: 18px;
        }}
        h1 {{
          font-size: 28px;
          margin: 0 0 8px 0;
        }}
        .sub {{
          font-size: 13px;
          opacity: .95;
        }}
        .meta {{
          margin-top: 14px;
          font-size: 12px;
          opacity: .95;
        }}
        h2 {{
          font-size: 16px;
          margin: 20px 0 8px 0;
          color: #0f172a;
          padding-bottom: 6px;
          border-bottom: 1px solid #dbe5f1;
        }}
        .kpi-grid {{
          display: table;
          width: 100%;
          border-spacing: 8px;
          margin: 6px 0 10px 0;
        }}
        .kpi-row {{
          display: table-row;
        }}
        .kpi {{
          display: table-cell;
          width: 25%;
          vertical-align: top;
          background: #f8fbff;
          border: 1px solid #dbe5f1;
          border-radius: 12px;
          padding: 12px;
        }}
        .kpi-label {{
          font-size: 10px;
          color: #64748b;
          text-transform: uppercase;
          font-weight: bold;
        }}
        .kpi-value {{
          margin-top: 6px;
          font-size: 18px;
          font-weight: bold;
          color: #0f172a;
        }}
        .kpi-sub {{
          margin-top: 5px;
          color: #64748b;
          font-size: 10px;
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          margin-top: 10px;
        }}
        th {{
          background: #eff6ff;
          color: #1e3a8a;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: .2px;
          border: 1px solid #dbe5f1;
          padding: 8px;
          text-align: left;
        }}
        td {{
          border: 1px solid #e2e8f0;
          padding: 8px;
          vertical-align: top;
        }}
        .right {{
          text-align: right;
        }}
        .center {{
          text-align: center;
        }}
        .badge {{
          display: inline-block;
          padding: 3px 8px;
          border-radius: 999px;
          font-size: 10px;
          font-weight: bold;
        }}
        .green {{ background: #dcfce7; color: #166534; }}
        .amber {{ background: #fef3c7; color: #92400e; }}
        .red {{ background: #fee2e2; color: #991b1b; }}
        .blue {{ background: #dbeafe; color: #1d4ed8; }}
        .note {{
          background: #f8fafc;
          border: 1px solid #e2e8f0;
          border-left: 4px solid #2563eb;
          padding: 12px 14px;
          border-radius: 10px;
          margin-top: 10px;
        }}
        .small {{
          font-size: 10px;
          color: #64748b;
        }}
        .page-break {{
          page-break-before: always;
        }}
      </style>
    </head>
    <body>

      <div class="cover">
        <h1>{_company_name()} Business State Report</h1>
        <div class="sub">
          Comprehensive executive report on the current operating state of the micro-credit business,
          including portfolio health, collections, risk exposure, borrower quality, agent productivity,
          and category concentration.
        </div>
        <div class="meta">
          Report Date: {today.strftime("%d %B %Y")}<br>
          Generated At: {generated_at.strftime("%d %B %Y %H:%M")}<br>
          Prepared For: Management / Executive Decision-Making
        </div>
      </div>

      <h2>1. Executive Snapshot</h2>
      <div class="kpi-grid">
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-label">Total Disbursed</div>
            <div class="kpi-value">{_ghs(total_disbursed)}</div>
            <div class="kpi-sub">Average loan size {_ghs(avg_loan_size)}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Total Expected</div>
            <div class="kpi-value">{_ghs(total_expected)}</div>
            <div class="kpi-sub">Principal + ROIC due</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Total Collected</div>
            <div class="kpi-value">{_ghs(total_collected)}</div>
            <div class="kpi-sub">Collection rate {collection_rate}%</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Total Outstanding</div>
            <div class="kpi-value">{_ghs(total_outstanding)}</div>
            <div class="kpi-sub">Current total exposure</div>
          </div>
        </div>
      </div>

      <div class="kpi-grid">
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-label">Loans</div>
            <div class="kpi-value">{total_loans}</div>
            <div class="kpi-sub">Active {active_loans} · Closed {closed_loans} · Default {default_loans}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Borrowers</div>
            <div class="kpi-value">{total_borrowers}</div>
            <div class="kpi-sub">Active {active_borrowers} · Closed {closed_borrowers} · Bad {bad_borrowers}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Agents</div>
            <div class="kpi-value">{total_agents}</div>
            <div class="kpi-sub">Agents with loans {agents_with_loans}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">PAR Proxy</div>
            <div class="kpi-value">{par_rate}%</div>
            <div class="kpi-sub">PAR amount {_ghs(par_amount)} · PAR count {par_count}</div>
          </div>
        </div>
      </div>

      <div class="note">
        <strong>Management Interpretation:</strong>
        The portfolio currently holds <strong>{_ghs(total_outstanding)}</strong> in total outstanding exposure against
        <strong>{_ghs(total_disbursed)}</strong> disbursed principal. The current recovery rate is
        <strong>{collection_rate}%</strong>. Default exposure stands at <strong>{default_loans}</strong> loans, while
        borrower-quality risk is reflected by <strong>{bad_borrowers}</strong> bad-status borrowers.
      </div>

      <h2>2. Recovery & Liquidity Position</h2>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th class="right">Amount</th>
            <th>Interpretation</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Total Principal Collected</td><td class="right">{_ghs(total_principal_collected)}</td><td>Recovered against principal disbursed</td></tr>
          <tr><td>Total ROIC Collected</td><td class="right">{_ghs(total_roic_collected)}</td><td>Recovered interest / return component</td></tr>
          <tr><td>Principal Outstanding</td><td class="right">{_ghs(principal_outstanding)}</td><td>Remaining unrecovered principal</td></tr>
          <tr><td>ROIC Outstanding</td><td class="right">{_ghs(roic_outstanding)}</td><td>Remaining unrecovered ROIC</td></tr>
          <tr><td>Active Portfolio Outstanding</td><td class="right">{_ghs(active_outstanding)}</td><td>Exposure still open on active loans</td></tr>
          <tr><td>Collected Today</td><td class="right">{_ghs(today_collected)}</td><td>Same-day inflow snapshot</td></tr>
          <tr><td>Collected Last 7 Days</td><td class="right">{_ghs(week_collected)}</td><td>Short-term cash recovery trend</td></tr>
          <tr><td>Collected This Month</td><td class="right">{_ghs(month_collected)}</td><td>Month-to-date collections</td></tr>
          <tr><td>Disbursed This Month</td><td class="right">{_ghs(month_disbursed)}</td><td>Month-to-date loan creation volume</td></tr>
        </tbody>
      </table>

      <h2>3. Portfolio Structure</h2>
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th class="center">Count</th>
            <th class="right">Principal / Exposure View</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><span class="badge amber">ACTIVE</span></td>
            <td class="center">{active_loans}</td>
            <td class="right">{_ghs(active_disbursed)} disbursed · {_ghs(active_expected)} expected · {_ghs(active_roic)} ROIC</td>
          </tr>
          <tr>
            <td><span class="badge green">CLOSED</span></td>
            <td class="center">{closed_loans}</td>
            <td class="right">Fully repaid or no remaining balance</td>
          </tr>
          <tr>
            <td><span class="badge red">DEFAULT</span></td>
            <td class="center">{default_loans}</td>
            <td class="right">Highest recovery attention required</td>
          </tr>
        </tbody>
      </table>

      <h2>4. Loan Category Concentration</h2>
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th class="center">Loans</th>
            <th class="right">Disbursed</th>
            <th class="right">Expected</th>
            <th class="right">Collected</th>
            <th class="right">Balance</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>{c['label']}</td><td class='center'>{c['count']}</td><td class='right'>{_ghs(c['disbursed'])}</td><td class='right'>{_ghs(c['expected'])}</td><td class='right'>{_ghs(c['collected'])}</td><td class='right'>{_ghs(c['balance'])}</td></tr>"
              for c in category_summary
          ) or "<tr><td colspan='6'>No category data found.</td></tr>"}
        </tbody>
      </table>

      <div class="page-break"></div>

      <h2>5. Agent Performance & Exposure</h2>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th class="center">Loans</th>
            <th class="center">Borrowers</th>
            <th class="right">Disbursed</th>
            <th class="right">Expected</th>
            <th class="right">Collected</th>
            <th class="right">Balance</th>
            <th class="right">Rate</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>{a['name']}</td><td class='center'>{a['loans']}</td><td class='center'>{a['borrowers']}</td><td class='right'>{_ghs(a['disbursed'])}</td><td class='right'>{_ghs(a['expected'])}</td><td class='right'>{_ghs(a['collected'])}</td><td class='right'>{_ghs(a['balance'])}</td><td class='right'>{a['rate']}%</td></tr>"
              for a in agent_rows
          ) or "<tr><td colspan='8'>No agent data found.</td></tr>"}
        </tbody>
      </table>

      <h2>6. Highest Risk / Highest Priority Loans</h2>
      <table>
        <thead>
          <tr>
            <th>Loan</th>
            <th>Borrower</th>
            <th>Agent</th>
            <th>Category</th>
            <th>Status</th>
            <th>Borrower Status</th>
            <th class="right">Balance</th>
            <th class="center">Overdue Weeks</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>#{r['id']}</td><td>{r['borrower']}</td><td>{r['agent']}</td><td>{r['category']}</td><td>{r['status']}</td><td>{r['borrower_status']}</td><td class='right'>{_ghs(r['balance'])}</td><td class='center'>{r['overdue_weeks']}</td></tr>"
              for r in top_risky_loans
          ) or "<tr><td colspan='8'>No risky loan data found.</td></tr>"}
        </tbody>
      </table>

      <h2>7. Largest Borrower Exposures</h2>
      <table>
        <thead>
          <tr>
            <th>Borrower</th>
            <th>Status</th>
            <th class="center">Loans</th>
            <th class="right">Disbursed</th>
            <th class="right">Expected</th>
            <th class="right">Collected</th>
            <th class="right">Balance</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
              f"<tr><td>{b['name']}</td><td>{b['status']}</td><td class='center'>{b['loans']}</td><td class='right'>{_ghs(b['disbursed'])}</td><td class='right'>{_ghs(b['expected'])}</td><td class='right'>{_ghs(b['collected'])}</td><td class='right'>{_ghs(b['balance'])}</td></tr>"
              for b in borrower_rows
          ) or "<tr><td colspan='7'>No borrower exposure data found.</td></tr>"}
        </tbody>
      </table>

      <h2>8. Executive Decision Notes</h2>
      <div class="note">
        <strong>Suggested management actions based on current data:</strong>
        <br><br>
        1. Intensify collections and follow-up on default loans and high-overdue accounts immediately.
        <br>
        2. Review agents with high balance exposure but weaker recovery rates.
        <br>
        3. Evaluate whether higher-value categories are producing acceptable recovery quality relative to exposure.
        <br>
        4. Review top borrower exposures for restructuring, escalation, or focused monitoring.
        <br>
        5. Compare new monthly disbursement volume against monthly collections to manage liquidity discipline.
      </div>

      <div class="small" style="margin-top:20px;">
        This document is system-generated from the live {_company_name()} portfolio as of {generated_at.strftime("%d %B %Y %H:%M")}.
      </div>

    </body>
    </html>
    """

    pdf_file = HTML(string=html, base_url=request.build_absolute_uri("/"), url_fetcher=LocalPDFResources()).write_pdf()

    filename = f"{slugify(CompanyProfile.get_solo().company_name)}_business_state_report_{today.strftime('%Y%m%d')}.pdf"
    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
