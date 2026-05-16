"""
Two arithmetic-reconciliation rules called out in the handoff but not yet
implemented in verifier.py:

    Rule A — Pull Ticket allocation sum
        For each WO, sum of allocation rows on the Pull Ticket(s) must equal
        the Total Quantity (lbs or cases) shown on that WO's COA / FPP.

    Rule B — Extra Cases USED case-count sum
        For each new WO that draws from Extra Cases USED forms, the sum of
        case counts on those XC_USED rows must equal the new WO's case count
        (as shown on the SQR Extra-Case Report or COA for that WO).

The rules append CheckResult entries directly to sp.checks the same way the
existing rule blocks do, so they flow through every downstream output (the
issues CSV, marked-up PDF overlay, cross-reference matrix, dashboard).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional


def _to_number(v: Any) -> Optional[float]:
    """Coerce strings like '1,250 lbs' or '25.0' to float; return None if not numeric."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    # Strip common units / thousands separators
    s = s.replace(",", "").replace("$", "").replace("lbs", "").replace("lb", "")
    s = s.replace("cases", "").replace("case", "").replace("ct", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _sum_with_pages(rows: List[Dict[str, Any]], key: str) -> tuple:
    """Sum values found at key across rows; return (total, contributing_pages)."""
    total = 0.0
    pages = []
    seen = False
    for r in rows:
        v = _to_number(r.get(key))
        if v is None:
            continue
        seen = True
        total += v
        pg = r.get("__page_no")
        if pg is not None and pg not in pages:
            pages.append(pg)
    return (total if seen else None, pages)


def check_pull_ticket_allocation_sum(sp, CheckResult, tolerance_lbs: float = 1.0) -> List:
    """
    For each WO in the sub-packet, sum every Pull Ticket allocation row that
    references the WO and compare against the WO's Total Quantity from the
    COA (preferred) or FPP (fallback).

    A Pull Ticket row may carry the allocated weight under a few different
    field names depending on the form revision; we look at the most common ones.
    """
    out = []

    # 1. Collect Pull Ticket pages, broken down by referenced WO
    pull_rows_by_wo: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in sp.pages:
        if p.form_code != "PULL":
            continue
        if p.fields.get("is_backup_source"):
            continue
        page_wo = p.fields.get("wo")
        # Pull Ticket may carry an `allocations` array, OR scalar fields.
        allocs = p.fields.get("allocations") or p.fields.get("allocation_rows")
        if isinstance(allocs, list) and allocs:
            for a in allocs:
                wo = a.get("wo") or page_wo
                if not wo:
                    continue
                row = dict(a)
                row["__page_no"] = p.page_no
                pull_rows_by_wo[str(wo)].append(row)
        else:
            wo = page_wo
            if not wo:
                continue
            row = {
                "lbs": p.fields.get("total_lbs") or p.fields.get("allocated_lbs"),
                "cases": p.fields.get("cases") or p.fields.get("allocated_cases"),
                "__page_no": p.page_no,
            }
            pull_rows_by_wo[str(wo)].append(row)

    if not pull_rows_by_wo:
        return out  # No Pull Ticket pages → rule is silent (not a fail).

    # 2. Build the WO → Total Quantity map from COA (preferred) / FPP / SQR_XC.
    wo_total_lbs: Dict[str, tuple] = {}    # wo → (lbs, source_page)
    for p in sp.pages:
        if p.fields.get("is_backup_source"):
            continue
        if p.form_code not in ("COA", "FPP", "SQR_XC"):
            continue
        wo = p.fields.get("wo")
        tot = _to_number(p.fields.get("total_lbs"))
        if wo and tot is not None:
            # Prefer COA over FPP over SQR_XC
            priority = {"COA": 0, "FPP": 1, "SQR_XC": 2}.get(p.form_code, 3)
            existing = wo_total_lbs.get(str(wo))
            if existing is None or priority < existing[2]:
                wo_total_lbs[str(wo)] = (tot, p.page_no, priority)

    # 3. For each WO that has Pull Ticket rows, run the reconciliation
    for wo, rows in sorted(pull_rows_by_wo.items()):
        sum_lbs, contributing_pages = _sum_with_pages(rows, "lbs")
        ref = wo_total_lbs.get(wo)
        if sum_lbs is None:
            out.append(CheckResult(
                f"Pull Ticket allocation sum [WO {wo}]",
                "info",
                f"Could not extract allocation lbs from Pull Ticket page(s) "
                f"{contributing_pages or '?'} — please verify totals visually.",
                contributing_pages, sub_packet=sp.index))
            continue
        if ref is None:
            out.append(CheckResult(
                f"Pull Ticket allocation sum [WO {wo}]",
                "info",
                f"Allocation rows sum to {sum_lbs:.0f} lbs on pages "
                f"{contributing_pages}, but no COA/FPP Total Qty found for WO {wo} "
                f"to reconcile against.",
                contributing_pages, sub_packet=sp.index))
            continue
        ref_lbs, ref_page, _ = ref
        diff = abs(sum_lbs - ref_lbs)
        if diff <= tolerance_lbs:
            out.append(CheckResult(
                f"Pull Ticket allocation sum [WO {wo}]",
                "pass",
                f"Allocations sum to {sum_lbs:.0f} lbs (pages {contributing_pages}) "
                f"= Total Qty {ref_lbs:.0f} lbs on COA/FPP p{ref_page} ✓",
                contributing_pages + [ref_page], sub_packet=sp.index))
        else:
            out.append(CheckResult(
                f"Pull Ticket allocation sum [WO {wo}]",
                "fail",
                f"Allocations sum to {sum_lbs:.0f} lbs (pages {contributing_pages}) "
                f"≠ Total Qty {ref_lbs:.0f} lbs on COA/FPP p{ref_page} "
                f"(off by {diff:.0f} lbs)",
                contributing_pages + [ref_page], sub_packet=sp.index))
    return out


def check_extra_cases_used_sum(sp, CheckResult, tolerance_cases: float = 0.0) -> List:
    """
    For each new WO with associated Extra Cases USED (XC_USED) form pages,
    the sum of `cases` on those pages must equal the new WO's case count
    on its SQR Extra-Case Report (SQR_XC) or COA.
    """
    out = []

    # 1. Collect XC_USED rows by `new_wo` (the WO they're being applied to).
    xc_rows_by_new_wo: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in sp.pages:
        if p.form_code != "XC_USED":
            continue
        if p.fields.get("is_backup_source"):
            continue
        # `new_wo` is the WO this form contributes cases TO; falls back to
        # the page's primary WO when the field name isn't standardized yet.
        new_wo = (p.fields.get("new_wo")
                  or p.fields.get("applied_to_wo")
                  or p.fields.get("destination_wo")
                  or p.fields.get("wo"))
        if not new_wo:
            continue
        # Allow per-row entries for multi-row XC_USED forms
        rows = p.fields.get("rows")
        if isinstance(rows, list) and rows:
            for r in rows:
                row = dict(r)
                row["__page_no"] = p.page_no
                xc_rows_by_new_wo[str(new_wo)].append(row)
        else:
            xc_rows_by_new_wo[str(new_wo)].append({
                "cases": p.fields.get("cases"),
                "__page_no": p.page_no,
            })

    if not xc_rows_by_new_wo:
        return out

    # 2. Build the WO → case-count map from SQR_XC (preferred) / COA / FPP
    wo_cases: Dict[str, tuple] = {}
    for p in sp.pages:
        if p.fields.get("is_backup_source"):
            continue
        if p.form_code not in ("SQR_XC", "COA", "FPP"):
            continue
        wo = p.fields.get("wo")
        cases = _to_number(p.fields.get("cases"))
        if wo and cases is not None:
            priority = {"SQR_XC": 0, "COA": 1, "FPP": 2}.get(p.form_code, 3)
            existing = wo_cases.get(str(wo))
            if existing is None or priority < existing[2]:
                wo_cases[str(wo)] = (cases, p.page_no, priority)

    # 3. Reconcile per WO
    for wo, rows in sorted(xc_rows_by_new_wo.items()):
        sum_cases, contributing_pages = _sum_with_pages(rows, "cases")
        ref = wo_cases.get(wo)
        if sum_cases is None:
            out.append(CheckResult(
                f"Extra Cases USED case-count sum [WO {wo}]",
                "info",
                f"Could not extract case counts from XC_USED page(s) "
                f"{contributing_pages or '?'} — please verify visually.",
                contributing_pages, sub_packet=sp.index))
            continue
        if ref is None:
            out.append(CheckResult(
                f"Extra Cases USED case-count sum [WO {wo}]",
                "info",
                f"XC_USED rows sum to {sum_cases:.0f} cases on pages "
                f"{contributing_pages}, but no SQR_XC/COA case count found "
                f"for WO {wo} to reconcile against.",
                contributing_pages, sub_packet=sp.index))
            continue
        ref_cases, ref_page, _ = ref
        diff = abs(sum_cases - ref_cases)
        if diff <= tolerance_cases:
            out.append(CheckResult(
                f"Extra Cases USED case-count sum [WO {wo}]",
                "pass",
                f"USED cases sum to {sum_cases:.0f} (pages {contributing_pages}) "
                f"= WO {wo} case count {ref_cases:.0f} on p{ref_page} ✓",
                contributing_pages + [ref_page], sub_packet=sp.index))
        else:
            out.append(CheckResult(
                f"Extra Cases USED case-count sum [WO {wo}]",
                "fail",
                f"USED cases sum to {sum_cases:.0f} (pages {contributing_pages}) "
                f"≠ WO {wo} case count {ref_cases:.0f} on p{ref_page} "
                f"(off by {diff:.0f} cases)",
                contributing_pages + [ref_page], sub_packet=sp.index))
    return out


def run_arithmetic_rules(sp, CheckResult, rules_cfg: Dict[str, Any]) -> None:
    """
    Append both arithmetic-rule CheckResults to sp.checks. Both rules are
    on by default; either can be disabled via rules.yaml:

        rules:
          pull_ticket_allocation_sum:
            enabled: true
            severity: fail              # or 'info'
            tolerance_lbs: 1.0
          extra_cases_used_sum:
            enabled: true
            severity: fail
            tolerance_cases: 0.0
    """
    cfg_a = rules_cfg.get("pull_ticket_allocation_sum", {"enabled": True})
    if cfg_a.get("enabled", True):
        results = check_pull_ticket_allocation_sum(
            sp, CheckResult, tolerance_lbs=cfg_a.get("tolerance_lbs", 1.0))
        # Honor severity override
        sev = cfg_a.get("severity")
        if sev:
            for r in results:
                if r.status == "fail":
                    r.status = sev
        sp.checks.extend(results)

    cfg_b = rules_cfg.get("extra_cases_used_sum", {"enabled": True})
    if cfg_b.get("enabled", True):
        results = check_extra_cases_used_sum(
            sp, CheckResult, tolerance_cases=cfg_b.get("tolerance_cases", 0.0))
        sev = cfg_b.get("severity")
        if sev:
            for r in results:
                if r.status == "fail":
                    r.status = sev
        sp.checks.extend(results)
