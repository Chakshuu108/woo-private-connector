# What the agent can and cannot do

## Can
| Need | Tool |
|---|---|
| "Show recent / on-hold / refunded orders", orders in a date range | `list_orders` |
| "What's in order 5001? Where's it shipping (city/country)? What was paid?" | `get_order` |
| "Find orders for Diya Khan / order #5007" | `search_orders` |
| "List products, show out-of-stock items" | `list_products` |
| "Price/stock for SKU-1003" | `get_product`, `search_products` |
| "What needs restocking?" | `get_low_stock_products` |

Results are paginated (≤50/page); the agent is told `total`, `has_more`, and `truncated` so it can say when a view is partial.

## Cannot
- **Write anything**: no refunds, cancellations, status changes, stock edits, notes, emails. The client has no non-GET method.
- **See full customer contact data**: email/phone are masked, street address/postcode omitted (configurable by the operator, not the agent).
- **See** payment card details, customer accounts/passwords, coupons, variations, or analytics reports (not exposed).
- **Filter by arbitrary fields** (e.g. order total > X); it must list then reason, within page limits.
- **Work in real time at scale**: subject to WooCommerce rate limits; large scans are slow and capped.
- **Guarantee correctness of free-text search**; it relies on WooCommerce's own `search` behaviour.

## Safety notes
- Credentials are provided by the operator through env/file; the agent never sees them.
- Tool errors are returned as short messages (`authentication failed`, `resource not found`, rate-limit giving up).
- Use a WooCommerce key with **Read** permission only, as defence in depth.
