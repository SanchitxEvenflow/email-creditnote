# GRN Push — Backend API Reference

Base URL: `http://localhost:8000`
All endpoints: `POST`, `Content-Type: application/json`

---

## Overview — 3-Step Flow

Call three endpoints in sequence. Output of each step feeds directly into the next.

```
Step 1: POST /grn-push/receipts
        → returns list of GRN codes per facility

Step 2: POST /grn-push/fetch-details
        → takes Step 1 output, returns grouped bill objects

Step 3: POST /grn-push/create-bills
        → takes Step 2 output, pushes drafts to Zoho Books
```

---

## Step 1 — List GRN Codes

### `POST /grn-push/receipts`

Fetches all GRN (inflow receipt) codes from Unicommerce for a date range.
Queries 3 hardcoded facilities: `EL_BLR_APEX`, `EL_BLR_APEX_QC`, `EL_VIRTUAL_BLR`.

**Request**
```json
{
  "start": "2026-06-01",
  "end": "2026-06-16"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `start` | string | Start date `YYYY-MM-DD` (inclusive) |
| `end` | string | End date `YYYY-MM-DD` (inclusive) |

**Response**
```json
{
  "receipts": [
    { "grn_code": "G3612", "facility": "EL_BLR_APEX" },
    { "grn_code": "G3613", "facility": "EL_BLR_APEX" },
    { "grn_code": "G2005", "facility": "EL_BLR_APEX_QC" }
  ],
  "errors": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `receipts` | array | GRN code + facility pairs |
| `receipts[].grn_code` | string | Unicommerce GRN code e.g. `"G3612"` |
| `receipts[].facility` | string | Warehouse facility code |
| `errors` | array | Per-facility error strings (empty if all OK) |

**UI notes**
- Show total GRN count found: `"Found N GRNs"`
- If `errors` non-empty, show per-facility warning banners but still proceed
- Pass the full `receipts` array as-is to Step 2

---

## Step 2 — Fetch Details & Group by Bill

### `POST /grn-push/fetch-details`

Fetches full GRN details from Unicommerce and groups them by vendor invoice number (= Zoho bill number).
Multiple GRNs sharing the same invoice number are merged into one bill object.

**Request** — pass `receipts` from Step 1:
```json
{
  "receipts": [
    { "grn_code": "G3612", "facility": "EL_BLR_APEX" },
    { "grn_code": "G3613", "facility": "EL_BLR_APEX" }
  ]
}
```

**Response**
```json
{
  "bills": [
    {
      "bill_number": "26-27/142",
      "po_code": "EL/KN/PO/2526/3205",
      "grn_codes": ["G3612"],
      "facilities": ["EL_BLR_APEX"],
      "vendor_code": "EL_METROBAG",
      "vendor_name": "METRO BAG",
      "date": "2026-06-16",
      "invoice_date": "2026-06-13",
      "line_items": [
        {
          "name": "Insulated Lunch Bag, Rectangle, Black",
          "description": "SKU FRW-LNCH-REC-BAG-BLK",
          "quantity": 600,
          "rate": 122.72,
          "sku": "FRW-LNCH-REC-BAG-BLK"
        }
      ],
      "notes": "Uniware GRN(s) G3612 | PO EL/KN/PO/2526/3205 | Vendor EL_METROBAG | Gate Entry IGP2003"
    }
  ]
}
```

### BillGroup fields

| Field | Type | Description |
|-------|------|-------------|
| `bill_number` | string | Vendor invoice number — becomes Zoho Bill # |
| `po_code` | string | Purchase order code |
| `grn_codes` | string[] | All Unicommerce GRN codes in this bill |
| `facilities` | string[] | Warehouses the GRNs came from |
| `vendor_code` | string | Unicommerce vendor code |
| `vendor_name` | string | Vendor display name |
| `date` | string \| null | Earliest GRN date `YYYY-MM-DD` |
| `invoice_date` | string \| null | Vendor invoice date `YYYY-MM-DD` |
| `line_items` | array | See below |
| `notes` | string | Auto-built: GRN codes, PO, vendor code, gate entry |

### Line item fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Item name from Unicommerce |
| `description` | string | SKU code e.g. `"SKU FRW-LNCH-REC-BAG-BLK"` |
| `quantity` | number | Received quantity |
| `rate` | number | Unit price (ex-tax) |
| `sku` | string | SKU code (used internally in Step 3 for Zoho item lookup) |

**UI notes**
- Show a preview table before Step 3 — suggested columns:
  `Bill #` | `Vendor` | `GRNs` | `Items` | `Total Value` | `Will Skip?`
- Total value = sum of `quantity × rate` across all line items
- Bills with `bill_number` containing "kitting", "dekitting", or "return" will be auto-skipped in Step 3 — mark these visually (grey out / badge)
- Pass the full `bills` array as-is to Step 3

---

## Step 3 — Create Draft Bills in Zoho

### `POST /grn-push/create-bills`

Pushes each bill group as a draft bill to Zoho Books.
Per bill: checks duplicate, resolves vendor, picks intra/interstate GST, looks up item IDs, creates bill.

**Request** — pass `bills` from Step 2:
```json
{
  "bills": [ /* BillGroup objects from Step 2 */ ]
}
```

**Response**
```json
{
  "total": 6,
  "ok": 4,
  "failed": 1,
  "results": [
    { "bill_number": "26-27/142",    "status": "ok",      "bill_id": "727927000219115022", "error": null },
    { "bill_number": "26-27/140",    "status": "ok",      "bill_id": "727927000219115028", "error": null },
    { "bill_number": "dekitting ",   "status": "skipped", "bill_id": null,                 "error": null },
    { "bill_number": "2026-27/54",   "status": "ok",      "bill_id": "727927000219115044", "error": null },
    { "bill_number": "INFI26-27/27", "status": "ok",      "bill_id": "727927000219115049", "error": null },
    { "bill_number": "XYZ/001",      "status": "error",   "bill_id": null,                 "error": "Bill 'XYZ/001' already exists in Zoho" }
  ]
}
```

### Response fields

| Field | Type | Description |
|-------|------|-------------|
| `total` | number | Total bills processed (including skipped) |
| `ok` | number | Successfully created in Zoho |
| `failed` | number | Errored (skipped not counted) |
| `results` | array | Per-bill result |
| `results[].bill_number` | string | Bill / invoice number |
| `results[].status` | string | `"ok"` \| `"error"` \| `"skipped"` |
| `results[].bill_id` | string \| null | Zoho bill ID (only when `status = "ok"`) |
| `results[].error` | string \| null | Error message (only when `status = "error"`) |

### Status values

| Status | Meaning | UI suggestion |
|--------|---------|---------------|
| `ok` | Draft bill created in Zoho Books | Green ✓, show bill_id |
| `error` | Creation failed | Red ✗, show `error` message |
| `skipped` | Bill name contains "kitting", "dekitting", or "return" — not pushed | Grey —, show "Skipped" |

### Common error messages

| Error message | Cause & action |
|---------------|----------------|
| `Bill 'X' already exists in Zoho` | Duplicate run — bill already exists, no action needed |
| `Zoho vendor not found: 'CODE'` | Vendor not in Zoho — create vendor in Zoho Books first |

---

## What Happens Inside Step 3

Per bill, in order:

1. **Skip check** — bill_number contains "kitting"/"dekitting"/"return" → status `skipped`
2. **Duplicate check** — query Zoho for bill with same number → error if already exists
3. **Vendor lookup** — search 459 cached Zoho vendors by name (exact → substring → word-overlap)
4. **Interstate detection** — vendor GST state code vs Karnataka (29) → picks IGST or GST
5. **Item lookup** — per SKU, fetch Zoho item → `item_id` + intra/inter tax IDs
6. **Bill creation** — POST to Zoho Books as `status: "draft"` with correct vendor, items, taxes

---

## Error Handling Summary

| Scenario | HTTP status | How error surfaces |
|----------|-------------|-------------------|
| Individual GRN fetch fails (Step 2) | 200 | GRN silently skipped; bill may have fewer items |
| Individual bill fails (Step 3) | 200 | `results[].status = "error"` with message |
| Unicommerce not configured | 503 | `{ "detail": "UNICOMMERCE_USERNAME / UNICOMMERCE_PASSWORD not configured" }` |

Steps 1–3 always return HTTP 200 for per-item failures — check `results[].status` not HTTP status.

---

## Suggested UI Layout

```
┌─────────────────────────────────────────┐
│  GRN Push                               │
│                                         │
│  Date Range:  [2026-06-01] → [2026-06-16] [Fetch GRNs] │
│                                         │
│  ● Found 8 GRNs across 3 facilities    │  ← Step 1 result
│                                         │
│  [Load Bill Preview]                    │
│                                         │
│  Bill Preview:                          │  ← Step 2 result
│  ┌──────────────┬────────────┬──────┬──────────┬────────┐
│  │ Bill #       │ Vendor     │ GRNs │ Value    │ Status │
│  ├──────────────┼────────────┼──────┼──────────┼────────┤
│  │ 26-27/142    │ METRO BAG  │ 1    │ ₹73,632  │ Ready  │
│  │ dekitting    │ Rusabl     │ 1    │ ₹14,689  │ Skip   │
│  └──────────────┴────────────┴──────┴──────────┴────────┘
│                                         │
│  [Push to Zoho]                         │
│                                         │
│  Results:                               │  ← Step 3 result
│  ✓ 26-27/142  →  bill_id 72792700...   │
│  —  dekitting  →  Skipped               │
│  ✗ XYZ/001    →  Already exists        │
└─────────────────────────────────────────┘
```
