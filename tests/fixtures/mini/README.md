# Mini fixture

Hand-designed metadata for unit tests: 14 employees, 8 reports, 8 tables, 3 metrics and
6 requests. It deliberately contains cases the generator never produces, such as an
ownership cycle and a dead end. Any change here must keep the expectations in the tests
that use it valid, especially `test_graph.py` and the ownership tests.

## Ownership cases (walk: successor first, else manager; max 3 hops)

| owner | walk | case |
|---|---|---|
| EMP-004 | active | active owner |
| EMP-008 | → 004 | S1: successor |
| EMP-010 | → manager 003 | S2: manager, no successor |
| EMP-007 | → 008 → 004 | C2: successor, successor |
| EMP-009 | → 010 → manager 003 | C2: successor, then manager |
| EMP-006 | → 007 → 008 → 004 | C3: resolved at the limit |
| EMP-005 | → 006 → 007 → 008 (still left) | C4: depth limit, fall back to the Sales head EMP-002 |
| EMP-011 | → 012 → 011 | cycle |
| EMP-013 | no successor, no manager | dead end |

## Lineage (parent → child)

| parent | child |
|---|---|
| TBL-001 stg_sales | TBL-003 int_sales_clean, TBL-007 fct_returns (staging → mart) |
| TBL-002 stg_dealers | TBL-004 int_sales_by_dealer |
| TBL-003 int_sales_clean | TBL-004 int_sales_by_dealer, TBL-005 fct_sales |
| TBL-004 int_sales_by_dealer | TBL-005 fct_sales, TBL-006 dim_region |
| TBL-008 stg_unused | (none) |

Reports: RPT-0001 ← 005, 006 · RPT-0002 ← 005 · RPT-0003 ← 007 · RPT-0004 (deprecated,
replaced by RPT-0005) ← 006 · RPT-0005 ← 006 · RPT-0006 ← 005 · RPT-0007 ← 004 (an
intermediate table) · RPT-0008 ← 007. Metrics: MET-001 ← 005 · MET-002 ← 005, 006 ·
MET-003 ← 007 (no formula).
