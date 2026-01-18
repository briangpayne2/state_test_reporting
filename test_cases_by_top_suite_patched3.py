#!/usr/bin/env python3
"""
List UNIQUE test cases under each TOP-LEVEL suite in a given Test Plan,
with an aggregated "Outcome" (no execution history).

- Top-level suites are the first folders under the plan (e.g., Commerce - UAT 1, DOE - UAT 1, etc.).
- A test case can appear multiple times (points/configs, multiple child suites). We deduplicate
  per top-level suite and compute ONE aggregated outcome using precedence:
  Failed > Blocked > Paused > Active > NotApplicable > None/empty > Passed
- We also collect all SuitePaths (Top/Child/Subchild) where the case appears, joined by "; ".
- Produces EXACTLY one CSV per top-level suite + an optional combined CSV.

.env required:
  ADO_ORG, ADO_PROJECT, ADO_PAT, TEST_PLAN_NAME
Optional:
  OUTPUT_DIR   (default: exports)
"""

import base64, os
from urllib.parse import quote
from typing import Dict, Any, List, Optional, Set
import requests
from dotenv import dotenv_values
import pandas as pd

# ------------- .env -------------
cfg = dotenv_values(".env")
ADO_ORG        = (cfg.get("ADO_ORG") or "").strip()
ADO_PROJECT    = (cfg.get("ADO_PROJECT") or "").strip()
ADO_PAT        = (cfg.get("ADO_PAT") or "").strip()
TEST_PLAN_NAME = (cfg.get("TEST_PLAN_NAME") or "").strip()
OUTPUT_DIR     = (cfg.get("OUTPUT_DIR") or "exports").strip()

if not (ADO_ORG and ADO_PROJECT and ADO_PAT and TEST_PLAN_NAME):
    raise SystemExit("Missing one of: ADO_ORG, ADO_PROJECT, ADO_PAT, TEST_PLAN_NAME")

# ------------- API bases -------------
BASE = (ADO_ORG if ADO_ORG.startswith(("http://","https://"))
        else f"https://dev.azure.com/{ADO_ORG}").rstrip("/")
PROJECT_PATH = quote(ADO_PROJECT, safe="")  # handle spaces

TESTPLAN_API_VER = "7.1-preview.1"  # stable for plans/suites
VER_POINTS       = ["7.1-preview.2", "7.1-preview.1", "7.0", "6.0"]  # fallback for points
VER_RUNS         = ["7.1-preview.7", "7.1-preview.1", "7.0", "6.0"]  # fallback for runs
VER_RESULTS      = ["7.1-preview.6", "7.1-preview.1", "7.0", "6.0"]  # fallback for results

def H() -> Dict[str,str]:
    tok = base64.b64encode(f":{ADO_PAT}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "Accept": "application/json"}

def urlp(suffix: str) -> str:
    return f"{BASE}/{PROJECT_PATH}{suffix if suffix.startswith('/') else '/'+suffix}"

def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = requests.get(url, headers=H(), params=params or {})
    print(f"GET {r.url}")
    if r.status_code >= 400:
        raise SystemExit(f"HTTP {r.status_code} for GET {r.url}\n{r.text}")
    return r.json()

def get_json_paginated_fallback(url: str, versions: List[str], params: Optional[Dict[str, Any]] = None,
                                value_key: str = "value") -> List[Dict[str, Any]]:
    last = ""
    for ver in versions:
        out: List[Dict[str, Any]] = []
        token: Optional[str] = None
        while True:
            q = dict(params or {})
            q["api-version"] = ver
            if token:
                q["continuationToken"] = token
            r = requests.get(url, headers=H(), params=q)
            print(f"GET {r.url}")
            if r.status_code >= 400:
                last = f"{r.status_code} {r.text}"
                out = []
                break
            body = r.json()
            chunk = body.get(value_key, body if isinstance(body, list) else [])
            out.extend(chunk if isinstance(chunk, list) else [chunk])
            token = r.headers.get("x-ms-continuationtoken")
            if not token:
                return out
    raise SystemExit(f"All versions failed for {url}\n{last}")

# ------------- Plans & Suites -------------
def resolve_plan_id_by_name(plan_name: str) -> str:
    plans = get_json(urlp("/_apis/testplan/plans"), {"api-version": TESTPLAN_API_VER}).get("value", [])
    wanted = plan_name.lower().strip()
    exact = [p for p in plans if p.get("name","").lower().strip() == wanted]
    if not exact:
        partial = [p for p in plans if wanted in p.get("name","").lower()]
        if not partial: raise SystemExit(f"Plan '{plan_name}' not found")
        exact = partial
    pid = str(exact[0]["id"])
    print(f"[OK] Plan '{exact[0]['name']}' ID={pid}")
    return pid

def list_suites(plan_id: str) -> List[Dict[str, Any]]:
    resp = get_json(urlp(f"/_apis/testplan/Plans/{plan_id}/suites"),
                    {"api-version": TESTPLAN_API_VER})
    suites = resp.get("value", resp.get("suites", [])) or []
    for s in suites:
        s["id"] = str(s.get("id"))
        par = (s.get("parentSuite") or {}).get("id")
        s["parentId"] = str(par) if par is not None else None
    return suites

def build_suite_path_lookup(suites: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return dict of suiteId -> 'Top/Child/Subchild' path string."""
    by_id = {s["id"]: s for s in suites}
    cache: Dict[str, str] = {}
    def path_for(sid: str) -> str:
        if sid in cache:
            return cache[sid]
        parts = []
        cur = by_id[sid]
        while cur is not None:
            parts.append(cur["name"])
            pid = cur.get("parentId")
            cur = by_id.get(pid) if pid is not None else None
        parts.reverse()
        cache[sid] = "/".join(parts)
        return cache[sid]
    for s in suites:
        _ = path_for(s["id"])
    return cache

# ------------- Points (latest outcomes) -------------
def get_points_for_suite(plan_id: str, suite_id: str) -> List[Dict[str, Any]]:
    pts = get_json_paginated_fallback(
        urlp("/_apis/test/points"),
        VER_POINTS,
        params={"planId": plan_id, "suiteId": suite_id, "includePointDetails": "true", "returnIdentityRef": "true"},
        value_key="value"
    )
    for p in pts:
        if "id" in p: p["id"] = int(p["id"])
        p["resolvedOutcome"] = resolve_point_outcome(p)
    return pts

# ------------- Outcome precedence & util -------------
OUTCOME_ORDER = {
    "Failed": 6,
    "Blocked": 5,
    "Paused": 4,
    "Active": 3,
    "NotApplicable": 2,
    "Passed": 0,
    None: -1, "": -1, "None": -1, "NeverRun": -1
}


def resolve_point_outcome(point: dict):
    """
    Return the best available outcome for a test point.
    Preference order:
      1) point["outcome"]
      2) point["mostRecentResult"]["outcome"]
      3) point["lastTestRun"]["outcome"]
      4) point["lastResultDetails"]["outcome"]
    """
    # direct outcome
    o = point.get("outcome")
    if o:
        return o
    # mostRecentResult
    mrr = point.get("mostRecentResult") or {}
    o = mrr.get("outcome")
    if o:
        return o
    # lastTestRun (some tenants expose this)
    ltr = point.get("lastTestRun") or {}
    o = ltr.get("outcome")
    if o:
        return o
    # lastResultDetails fallback
    lrd = point.get("lastResultDetails") or {}
    return lrd.get("outcome")


def worse(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return the worse (higher precedence value) of two outcomes."""
    va = OUTCOME_ORDER.get(a, -1)
    vb = OUTCOME_ORDER.get(b, -1)
    return a if va >= vb else b

def slugify(name: str, maxlen: int = 80) -> str:
    import re
    s = name.strip().lower().replace("&", "and")
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s).strip("_")
    return s[:maxlen] if len(s) > maxlen else s


# ------------- Runs & Results (for backfilling outcomes) -------------
def list_runs_for_plan(plan_id: str) -> List[Dict[str, Any]]:
    """Fetch runs for the plan (no date filter), newest first."""
    params = {"planId": plan_id}
    runs = get_json_paginated_fallback(urlp("/_apis/test/runs"), VER_RUNS, params=params)
    # normalize id and sort desc by lastUpdatedDate if present
    for r in runs:
        if "id" in r:
            r["id"] = int(r["id"])
    try:
        runs.sort(key=lambda x: x.get("lastUpdatedDate") or x.get("completedDate") or "", reverse=True)
    except Exception:
        pass
    return runs

def list_results_for_run(run_id: int) -> List[Dict[str, Any]]:
    results = get_json_paginated_fallback(urlp(f"/_apis/test/Runs/{run_id}/results"),
                                          VER_RESULTS, params={})
    for r in results:
        if "id" in r:
            r["id"] = int(r["id"])
        # normalize pointId from nested structure
        if "testPoint" in r and isinstance(r["testPoint"], dict) and "id" in r["testPoint"]:
            r["pointId"] = int(r["testPoint"]["id"])
        elif "pointId" in r and r["pointId"] is not None:
            try:
                r["pointId"] = int(r["pointId"])
            except Exception:
                pass
    return results
# ------------- Orchestration -------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    plan_id = resolve_plan_id_by_name(TEST_PLAN_NAME)
    suites = list_suites(plan_id)
    by_id = {s["id"]: s for s in suites}
    top_level = [s for s in suites if s.get("parentId") is None]
    suite_path = build_suite_path_lookup(suites)
    # Build a backfill map of latest outcomes by pointId using runs/results
    latest_by_point: Dict[int, Dict[str, Any]] = {}
    try:
        runs = list_runs_for_plan(plan_id)
        # To keep it fast, look at most recent ~50 runs
        for run in runs[:50]:
            rid = run["id"]
            for res in list_results_for_run(rid):
                pid = res.get("pointId")
                if pid is None:
                    continue
                ts = res.get("completedDate") or res.get("startedDate") or run.get("lastUpdatedDate")
                # keep the latest by timestamp
                prev = latest_by_point.get(pid)
                if prev is None or (ts or "") > (prev.get("ts") or ""):
                    latest_by_point[pid] = {"outcome": res.get("outcome"), "ts": ts}
        print(f"[OK] Backfill map prepared for {len(latest_by_point)} point(s) from recent runs")
    except SystemExit as e:
        # If runs/results APIs are blocked, continue without backfill
        print(f"[WARN] Could not build backfill from runs/results: {e}")
    except Exception as e:
        print(f"[WARN] Backfill error: {e}")

    print("[OK] Top-level suites:", ", ".join(s["name"] for s in top_level))

    def top_ancestor(sid: str) -> str:
        cur = by_id[sid]
        while cur.get("parentId") is not None:
            cur = by_id[cur["parentId"]]
        return cur["id"]

    # For each top-level suite, aggregate UNIQUE test cases
    # Structure: {topId: {testCaseId: {"name":..., "outcome":..., "paths": set()}}}
    agg: Dict[str, Dict[int, Dict[str, Any]]] = {s["id"]: {} for s in top_level}

    for s in suites:
        sid = s["id"]
        pts = get_points_for_suite(plan_id, sid)
        if not pts:
            continue
        tid = top_ancestor(sid)
        tname = by_id[tid]["name"]
        path_str = suite_path.get(sid, s["name"])

        for p in pts:
            tc = p.get("testCase") or {}
            tcid = tc.get("id")
            tcname = tc.get("name")
            outcome = (p.get("resolvedOutcome") or p.get("outcome") or "NeverRun")

            if not tcid:
                continue
            bucket = agg[tid].setdefault(int(tcid), {"name": tcname, "outcome": None, "paths": set()})
            bucket["name"] = bucket["name"] or tcname
            bucket["outcome"] = worse(bucket["outcome"], outcome)
            bucket["paths"].add(path_str)

    # Build exactly one CSV per top-level suite
    for top in top_level:
        tid = top["id"]
        tname = top["name"]
        rows = []
        for tcid, info in agg[tid].items():
            rows.append({
                "TopSuiteId": tid,
                "TopSuiteName": tname,
                "TestCaseId": tcid,
                "TestCaseName": info["name"],
                "Outcome": (info["outcome"] if info["outcome"] not in (None, "", "None") else "NeverRun"),
                "Paths": "; ".join(sorted(info["paths"])),
                "NumPaths": len(info["paths"]),
            })
        df = pd.DataFrame(rows, columns=[
            "TopSuiteId","TopSuiteName","TestCaseId","TestCaseName","Outcome","NumPaths","Paths"
        ])
        safe = slugify(tname)
        out_path = os.path.join(OUTPUT_DIR, f"{safe}_testcases.csv")
        df.to_csv(out_path, index=False)
        print(f"[CSV] {tname} -> {out_path} ({len(df)} unique test case rows)")

    # Optional combined
    combined = []
    for top in top_level:
        tid = top["id"]
        tname = top["name"]
        # reconstruct per-top CSV rows from agg
        for tcid, info in agg[tid].items():
            combined.append({
                "TopSuiteName": tname,
                "TestCaseId": tcid,
                "TestCaseName": info["name"],
                "Outcome": (info["outcome"] if info["outcome"] not in (None, "", "None") else "NeverRun"),
                "NumPaths": len(info["paths"]),
                "Paths": "; ".join(sorted(info["paths"])),
            })
    if combined:
        all_df = pd.DataFrame(combined)
        all_out = os.path.join(OUTPUT_DIR, "all_top_level_testcases.csv")
        all_df.to_csv(all_out, index=False)
        print(f"[CSV] Combined -> {all_out} ({len(all_df)} rows)")

if __name__ == "__main__":
    main()
