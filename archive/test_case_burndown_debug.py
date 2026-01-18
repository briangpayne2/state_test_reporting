
#!/usr/bin/env python3
"""
test_case_burndown_debug.py
- Wide, verbose run collection to diagnose why filtered result is 0.
- Pulls runs in BOTH modes (created / updated) and WITH/WITHOUT date filters.
- Dumps raw runs to CSV and prints summaries by state and date.
- Does NOT join results to points/folders; this is for debugging run availability.
"""
import os, base64, csv
from typing import Dict, Any, List, Optional
from pathlib import Path
from urllib.parse import quote
from datetime import datetime
import requests
import pandas as pd

# ---- Load .env beside this file ----
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)
except Exception:
    pass

def first_env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v not in (None, ""):
            return v
    return default

# ---- Config ----
ADO_ORG     = first_env("ADO_ORG", "ORGANIZATION", "ORG_NAME")
ADO_PROJECT = first_env("ADO_PROJECT", "PROJECT")
ADO_PAT     = first_env("ADO_PAT", "AZURE_DEVOPS_PAT")

TESTPLAN_API_VERSION    = "6.0-preview.1"
TEST_RUNS_API_VERSION   = "6.0"

if not (ADO_ORG and ADO_PROJECT and ADO_PAT):
    raise SystemExit("Missing ADO_ORG, ADO_PROJECT, or ADO_PAT in .env")

BASE = (ADO_ORG if ADO_ORG.startswith(("http://","https://")) else f"https://dev.azure.com/{ADO_ORG}").rstrip("/")
PROJECT_PATH = quote(ADO_PROJECT, safe="")

def headers_basic() -> Dict[str, str]:
    tok = base64.b64encode(f":{ADO_PAT}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "Accept": "application/json"}

def api_url(suffix: str) -> str:
    s = suffix if suffix.startswith("/") else "/" + suffix
    return f"{BASE}/{PROJECT_PATH}{s}"

def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = requests.get(url, params=params, headers=headers_basic())
    print(f"GET {r.url}")
    if r.status_code >= 400:
        raise SystemExit(f"HTTP {r.status_code} for GET {r.url}\n{r.text}")
    return r.json()

def list_plans() -> List[Dict[str, Any]]:
    return get_json(api_url("/_apis/testplan/plans"), {"api-version": TESTPLAN_API_VERSION}).get("value", [])

def resolve_plan_id() -> str:
    TEST_PLAN_NAME = first_env("TEST_PLAN_NAME")
    TEST_PLAN_ID   = first_env("TEST_PLAN_ID")
    if TEST_PLAN_NAME:
        for p in list_plans():
            if (p.get("name","").strip().lower() == TEST_PLAN_NAME.strip().lower()):
                return str(p.get("id"))
        if TEST_PLAN_ID:
            print(f"[i] Falling back to TEST_PLAN_ID={TEST_PLAN_ID}")
            return str(TEST_PLAN_ID)
        raise SystemExit(f"Could not find plan named '{TEST_PLAN_NAME}'.")
    if TEST_PLAN_ID:
        return str(TEST_PLAN_ID)
    raise SystemExit("Provide TEST_PLAN_NAME or TEST_PLAN_ID in .env")

def fetch_runs(date_mode: Optional[str]=None, start: Optional[str]=None, end: Optional[str]=None, top: int=100) -> List[Dict[str, Any]]:
    """If date_mode is None, no date filters are applied (returns recent runs)."""
    url = api_url("/_apis/test/runs")
    params: Dict[str, Any] = {"api-version": TEST_RUNS_API_VERSION, "includeRunDetails": "true", "$top": str(min(top,100))}
    if date_mode in {"created","updated"} and start and end:
        if date_mode == "created":
            params["minCreatedDate"] = start
            params["maxCreatedDate"] = end
        else:
            params["minLastUpdatedDate"] = start
            params["maxLastUpdatedDate"] = end
        print(f"[i] RUNS mode={date_mode} with dates {start}..{end}")
    else:
        print("[i] RUNS with NO date filters (recent runs)")
    out: List[Dict[str, Any]] = []
    while True:
        r = requests.get(url, params=params, headers=headers_basic())
        print(f"GET {r.url}")
        if r.status_code >= 400:
            raise SystemExit(f"HTTP {r.status_code} for GET {r.url}\n{r.text}")
        j = r.json()
        out.extend(j.get("value", []))
        token = r.headers.get("x-ms-continuationtoken")
        if not token:
            break
        params["continuationToken"] = token
    return out

def summarize_runs(runs: List[Dict[str, Any]], label: str) -> None:
    print(f"\n===== Summary: {label} =====")
    print(f"Total runs: {len(runs)}")
    # Count by state
    from collections import Counter
    states = Counter([(r.get('state') or '').strip().lower() for r in runs])
    print("States:", dict(states))
    # Show top 15 newest by createdDate
    def to_dt(s):
        s = (s or "").rstrip("Z")
        try:
            return datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception:
            return datetime.min
    newest = sorted(runs, key=lambda r: to_dt(r.get("createdDate") or r.get("startedDate")), reverse=True)[:15]
    for r in newest:
        print(f"  id={r.get('id')}  state={r.get('state')}  created={r.get('createdDate')}  updated={r.get('lastUpdatedDate')}  name={r.get('name')}  planId={(r.get('plan') or {}).get('id')}")

def write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    if not rows:
        pd.DataFrame().to_csv(path, index=False)
        print(f"[OK] Wrote empty CSV: {path}")
        return
    cols = sorted({k for r in rows for k in r.keys()})
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    print(f"[OK] Wrote {len(rows)} rows -> {path}")

def main() -> None:
    print(f"[i] BASE={BASE}")
    print(f"[i] PROJECT_PATH={PROJECT_PATH}")
    plan_id = resolve_plan_id()
    print(f"[OK] Using plan_id={plan_id}")

    START_DATE = first_env("START_DATE")
    END_DATE   = first_env("END_DATE")

    # Fetch four sets: created(with dates), updated(with dates), created(no dates), updated(no dates)
    created_d = fetch_runs("created", START_DATE, END_DATE, top=100) if START_DATE and END_DATE else []
    updated_d = fetch_runs("updated", START_DATE, END_DATE, top=100) if START_DATE and END_DATE else []
    created_n = fetch_runs("created", None, None, top=100)
    updated_n = fetch_runs("updated", None, None, top=100)

    # Summaries BEFORE plan/state filtering
    summarize_runs(created_d, "created with dates")
    summarize_runs(updated_d, "updated with dates")
    summarize_runs(created_n, "created NO dates")
    summarize_runs(updated_n, "updated NO dates")

    # Always filter by plan id (this matches how your main script works)
    def plan_filter(rs): return [r for r in rs if str((r.get("plan") or {}).get("id")) == str(plan_id)]
    created_d_pf = plan_filter(created_d)
    updated_d_pf = plan_filter(updated_d)
    created_n_pf = plan_filter(created_n)
    updated_n_pf = plan_filter(updated_n)
    print(f"\nAfter plan filter (id={plan_id}): created_d={len(created_d_pf)}  updated_d={len(updated_d_pf)}  created_n={len(created_n_pf)}  updated_n={len(updated_n_pf)}")

    # Dump CSVs
    outdir = Path(__file__).parent
    write_csv(created_d, outdir / "runs_created_dates_raw.csv")
    write_csv(updated_d, outdir / "runs_updated_dates_raw.csv")
    write_csv(created_n, outdir / "runs_created_nodates_raw.csv")
    write_csv(updated_n, outdir / "runs_updated_nodates_raw.csv")
    write_csv(created_d_pf, outdir / "runs_created_dates_planfiltered.csv")
    write_csv(updated_d_pf, outdir / "runs_updated_dates_planfiltered.csv")
    write_csv(created_n_pf, outdir / "runs_created_nodates_planfiltered.csv")
    write_csv(updated_n_pf, outdir / "runs_updated_nodates_planfiltered.csv")

if __name__ == "__main__":
    main()
