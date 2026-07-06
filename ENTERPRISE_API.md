# Enterprise API Reference

This document describes the current Enterprise-owner API exposed from the public schema.

## Access Model

The API is available only when all of the following are true:

- the caller belongs to a tenant owner account
- the tenant subscription is Enterprise or otherwise API-enabled
- the tenant workspace is active
- the tenant is not suspended, cancelled, or expired

Authentication options:

- bearer API key
- authenticated tenant owner session on the public schema

Recommended production usage:

- use bearer API keys

Current API version:

- `v1`

## Authentication

Send the API key as a bearer token:

```http
Authorization: Bearer sk_live_...
```

Example:

```bash
curl -H "Authorization: Bearer <YOUR_API_KEY>" \
  http://localhost:8000/api/v1/enterprise/overview/
```

If authentication is missing or invalid, the API returns `403 Forbidden`.

## How to Create a Key

1. Sign in as the tenant owner on the public domain
2. Open `/account/`
3. Go to `Enterprise API`
4. Enter a key name
5. Click `Create API Key`

Important:

- the raw key is shown only once
- store it securely
- if lost, create a replacement and revoke the old key

## Base URL

Development example:

```text
http://localhost:8000
```

All endpoints are public-schema endpoints under:

```text
/api/v1/enterprise/
```

The repository also includes a ready-to-run request collection in `enterprise_api.http`.

## Pagination and Filtering

Collection endpoints currently use offset pagination.

- `limit`
  - default `50`
  - max `200`
- `offset`
  - default `0`

Endpoint-specific filters:

- borrowers: `q`
- loans: `status`

## Endpoints

### 1. Overview

```http
GET /api/v1/enterprise/overview/
```

Purpose:

- returns tenant summary plus a tenant-workspace portfolio overview

Example response:

```json
{
  "ok": true,
  "tenant": {
    "id": 2,
    "name": "Acme Capital",
    "schema_name": "acme",
    "status": "ACTIVE",
    "plan": "Enterprise",
    "plan_tier": "ENTERPRISE",
    "owner_email": "owner@example.com",
    "primary_domain": "acme.localhost",
    "is_white_label": false,
    "borrower_count": 120,
    "agent_count": 8,
    "trial_ends_at": null,
    "current_period_start": "2026-05-01T00:00:00+00:00",
    "current_period_end": "2026-05-31T23:59:59+00:00",
    "features": {
      "api": true,
      "accounting": true,
      "assets": true,
      "marketing": true,
      "payroll": true
    }
  },
  "workspace": {
    "company": {
      "company_name": "Acme Capital",
      "currency_code": "GHS",
      "currency_symbol": "₵",
      "country": "Ghana",
      "repayment_cycle": "weekly"
    },
    "counts": {
      "borrowers": 120,
      "agents": 8,
      "loans": 342,
      "payments": 901
    },
    "portfolio": {
      "total_disbursed": "450000.00",
      "total_expected": "521100.00",
      "total_collected": "308700.00",
      "total_outstanding": "212400.00",
      "active_loans": 167,
      "closed_loans": 149,
      "default_loans": 26
    }
  }
}
```

### 2. Borrowers

```http
GET /api/v1/enterprise/borrowers/
```

Query parameters:

- `q`
  - free-text search across borrower name, borrower ID, phone, email, and national ID
- `limit`
- `offset`

Example:

```http
GET /api/v1/enterprise/borrowers/?q=ama&limit=25&offset=0
```

Response shape:

```json
{
  "ok": true,
  "tenant": {},
  "count": 25,
  "total": 143,
  "limit": 25,
  "offset": 0,
  "results": [
    {
      "id": 1,
      "borrower_id": "BOR-0001",
      "full_name": "Ama Mensah",
      "status": "ACTIVE",
      "phone": "+233244000000",
      "email": "ama@example.com",
      "location": "Accra",
      "group_name": "Market Women",
      "preferred_language": "Twi",
      "loans_count": 3,
      "total_outstanding": "1200.00",
      "created_at": "2026-05-01T10:00:00+00:00"
    }
  ]
}
```

### 3. Loans

```http
GET /api/v1/enterprise/loans/
```

Query parameters:

- `status`
  - optional
  - e.g. `ACTIVE`, `CLOSED`, `DEFAULT`
- `limit`
- `offset`

Example:

```http
GET /api/v1/enterprise/loans/?status=ACTIVE&limit=25&offset=0
```

Response shape:

```json
{
  "ok": true,
  "tenant": {},
  "count": 25,
  "total": 167,
  "limit": 25,
  "offset": 0,
  "results": [
    {
      "id": 91,
      "borrower_id": "BOR-0001",
      "borrower_name": "Ama Mensah",
      "agent_id": "AG-004",
      "agent_name": "Kwame Boateng",
      "status": "ACTIVE",
      "loan_category": "SILVER",
      "amount": "2500.00",
      "weekly_payment": "250.00",
      "duration_weeks": 12,
      "total_expected_amount": "3000.00",
      "total_paid_amount": "1250.00",
      "balance_amount": "1750.00",
      "start_date": "2026-03-01",
      "created_at": "2026-03-01T09:00:00+00:00"
    }
  ]
}
```

### 4. Payments

```http
GET /api/v1/enterprise/payments/
```

Query parameters:

- `limit`
- `offset`

Example:

```http
GET /api/v1/enterprise/payments/?limit=50&offset=0
```

Response shape:

```json
{
  "ok": true,
  "tenant": {},
  "count": 50,
  "total": 901,
  "limit": 50,
  "offset": 0,
  "results": [
    {
      "id": 240,
      "loan_id": 91,
      "borrower_id": "BOR-0001",
      "borrower_name": "Ama Mensah",
      "amount": "250.00",
      "principal_paid": "208.33",
      "roic_paid": "41.67",
      "payment_method": "MOBILE_MONEY",
      "payment_date": "2026-05-10",
      "reference": "MTN-ABC-123",
      "is_pending": false,
      "is_void": false,
      "created_at": "2026-05-10T14:10:00+00:00"
    }
  ]
}
```

## Error Responses

When authentication or entitlement fails, the API returns a `403` response like:

```json
{
  "ok": false,
  "detail": "Enterprise owner authentication is required. Use a valid Enterprise API key or an eligible owner session."
}
```

Other response patterns:

- `405 Method Not Allowed` for non-`GET` requests on the current read-only endpoints
- `200 OK` for successful reads

## Operational Notes

- The API is read-only in the current release.
- Data is always scoped to the authenticated owner tenant.
- Session authentication is useful for manual inspection from the browser, but integrations should use bearer API keys.
- If you rotate a key, update your integration and `enterprise_api.http` immediately because the raw key cannot be recovered later.

## Notes

- all data is tenant-scoped
- responses are JSON only
- current API is read-only
- pagination currently uses `limit` and `offset`
- `enterprise_api.http` contains ready-to-run requests for every current endpoint
