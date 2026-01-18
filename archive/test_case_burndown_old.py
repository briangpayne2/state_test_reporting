
#!/usr/bin/env python3
import os, base64
from typing import Dict, Any, List, Optional
from pathlib import Path
from urllib.parse import quote
from datetime import datetime
import requests
import pandas as pd

# ---- Load .env ----
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
TEST_POINTS_API_VERSION = "7.1-preview.2"
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

# ---- Test Plans API ----
def list_plans() -> List[Dict[str, Any]]:
    return get_json(api_url("/_apis/testplan/plans"), {"api-version": TESTPLAN_API_VERSION}).get("value", [])

def list_suites(plan_id: str) -> List[Dict[str, Any]]:
    data = get_json(api_url(f"/_apis/testplan/Plans/{plan_id}/suites"), {"api-version": TESTPLAN_API_VERSION})
    suites = data.get("value", data.get("suites", [])) or []
    for s in suites:
        s["id"] = str(s.get("id"))
        pid = (s.get("parentSuite") or {}).get("id")
        s["parentId"] = str(pid) if pid is not None else None
    return suites

def compute_paths(suites: List[Dict[str, Any]]) -> None:
    by_id = {s["id"]: s for s in suites}
    def nm(x): return (x.get("name") or "").strip()
    for s in suites:
        parts = [nm(s)]
        cur = s
        while True:
            pid = cur.get("parentId")
            if not pid or pid not in by_id:
                break
            cur = by_id[pid]
            parts.append(nm(cur))
        s["_path"] = "/".join(reversed([p for p in parts if p]))

def children_map_for(suites: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    mp: Dict[str, List[Dict[str, Any]]] = {}
    for s in suites:
        pid = s.get("parentId")
        if pid:
            mp.setdefault(pid, []).append(s)
    return mp

# ---- Legacy Test API ----
def list_test_runs(date_mode: str, start: str, end: str, top: int = 100) -> List[Dict[str, Any]]:
    """date_mode: 'created' or 'updated'"""
    runs: List[Dict[str, Any]] = []
    url = api_url("/_apis/test/runs")
    assert f"/{PROJECT_PATH}/_apis/test/runs" in url, f"Bad runs URL: {url}"
    params: Dict[str, Any] = {
        "api-version": TEST_RUNS_API_VERSION,
        "includeRunDetails": "true",
        "$top": str(min(top, 100)),
    }
    if date_mode == "created":
        params["minCreatedDate"] = start
        params["maxCreatedDate"] = end
    else:
        params["minLastUpdatedDate"] = start
        params["maxLastUpdatedDate"] = end

    print(f"[i] RUNS_BASE_URL={url} mode={date_mode}")
    while True:
        r = requests.get(url, params=params, headers=headers_basic())
        print(f"GET {r.url}")
        if r.status_code >= 400:
            raise SystemExit(f"HTTP {r.status_code} for GET {r.url}\n{r.text}")
        j = r.json()
        runs.extend(j.get("value", []))
        token = r.headers.get("x-ms-continuationtoken")
        if not token:
            break
        params["continuationToken"] = token
    return runs

def list_run_results(run_id: str, top: int = 1000) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    url = api_url(f"/_apis/test/runs/{run_id}/results")
    params: Dict[str, Any] = {"api-version": TEST_RUNS_API_VERSION, "$top": str(top)}
    while True:
        r = requests.get(url, params=params, headers=headers_basic())
        print(f"GET {r.url}")
        if r.status_code >= 400:
            raise SystemExit(f"HTTP {r.status_code} for GET {r.url}\n{r.text}")
        j = r.json()
        results.extend(j.get("value", []))
        token = r.headers.get("x-ms-continuationtoken")
        if not token:
            break
        params["continuationToken"] = token
    return results

def list_points(plan_id: str, suite_id: str, top: int = 1000) -> List[Dict[str, Any]]:
    pts: List[Dict[str, Any]] = []
    url = api_url("/_apis/test/points")
    params: Dict[str, Any] = {"api-version": TEST_POINTS_API_VERSION, "planId": plan_id, "suiteId": suite_id, "$top": str(top)}
    while True:
        r = requests.get(url, params=params, headers=headers_basic())
        print(f"GET {r.url}")
        if r.status_code >= 400:
            raise SystemExit(f"HTTP {r.status_code} for GET {r.url}\n{r.text}")
        j = r.json()
        pts.extend(j.get("value", []))
        token = r.headers.get("x-ms-continuationtoken")
        if not token:
            break
        params["continuationToken"] = token
    return pts

def iso_parse(s: str) -> datetime:
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

# ---- Main ----
def main() -> None:
    TEST_PLAN_NAME = first_env("TEST_PLAN_NAME")
    TEST_PLAN_ID   = first_env("TEST_PLAN_ID")
    plan_id: Optional[str] = None

    if TEST_PLAN_NAME:
        for p in list_plans():
            if (p.get("name","").strip().lower() == TEST_PLAN_NAME.strip().lower()):
                plan_id = str(p.get("id")); break
        if not plan_id and TEST_PLAN_ID:
            print(f"[i] Falling back to TEST_PLAN_ID={TEST_PLAN_ID}")
            plan_id = str(TEST_PLAN_ID)
        elif not plan_id:
            raise SystemExit(f"Could not find a test plan named '{TEST_PLAN_NAME}' in project '{ADO_PROJECT}'.")
    else:
        if TEST_PLAN_ID:
            plan_id = str(TEST_PLAN_ID)
        else:
            raise SystemExit("Provide TEST_PLAN_NAME or TEST_PLAN_ID in .env")

    plan = get_json(api_url(f"/_apis/testplan/plans/{plan_id}"), {"api-version": TESTPLAN_API_VERSION})
    print(f"[OK] Plan: {plan.get('name')} (id={plan.get('id')})")
    print(f"[i] BASE={BASE}")
    print(f"[i] PROJECT_PATH={PROJECT_PATH}")

    suites = list_suites(plan_id)
    compute_paths(suites)
    print(f"[OK] Suites under plan: {len(suites)} found")
    if suites[:5]:
        print("Sample suites:", ", ".join(s.get("name") for s in suites[:5]))

    TEST_SUITE_ID   = first_env("TEST_SUITE_ID")
    TEST_SUITE_NAME = first_env("TEST_SUITE_NAME")
    TEST_FOLDER_ID   = first_env("TEST_FOLDER_ID", "TEST_SUBSUITE_ID")
    TEST_FOLDER_NAME = first_env("TEST_FOLDER_NAME", "TEST_SUBSUITE_NAME")
    TEST_FOLDER_PATH = first_env("TEST_FOLDER_PATH", "TEST_SUBSUITE_PATH")

    by_id = {s["id"]: s for s in suites}
    suite_id: Optional[str] = None
    found_suite: Optional[Dict[str, Any]] = None
    if TEST_SUITE_ID and TEST_SUITE_ID in by_id:
        suite_id = TEST_SUITE_ID; found_suite = by_id[suite_id]
    elif TEST_SUITE_NAME:
        cands = [s for s in suites if (s.get("name","").strip().lower() == TEST_SUITE_NAME.strip().lower())]
        if cands:
            cands.sort(key=lambda x: len(x.get("_path","")))
            suite_id = cands[0]["id"]; found_suite = cands[0]
    if not suite_id:
        raise SystemExit("Set TEST_SUITE_ID or TEST_SUITE_NAME to select a suite.")
    print(f"[OK] Target suite: id={suite_id} name='{found_suite.get('name')}' path='{found_suite.get('_path','')}'")

    children = children_map_for(suites)
    folder_id: Optional[str] = None
    found_folder: Optional[Dict[str, Any]] = None
    if TEST_FOLDER_ID and TEST_FOLDER_ID in by_id:
        folder_id = TEST_FOLDER_ID; found_folder = by_id[folder_id]
    elif TEST_FOLDER_PATH:
        parts = [p.strip().lower() for p in TEST_FOLDER_PATH.split("/") if p.strip()]
        cursor = suite_id; node = found_suite; ok = True
        for part in parts:
            nxt = None
            for k in children.get(cursor, []):
                if (k.get("name","").strip().lower() == part):
                    nxt = k; break
            if not nxt: ok = False; break
            cursor = nxt["id"]; node = nxt
        if ok:
            folder_id = cursor; found_folder = node
    elif TEST_FOLDER_NAME:
        for k in children.get(suite_id, []):
            if (k.get("name","").strip().lower() == TEST_FOLDER_NAME.strip().lower()):
                folder_id = k["id"]; found_folder = k; break

    if folder_id:
        print(f"[OK] Target folder/sub-suite: id={folder_id} name='{found_folder.get('name')}' path='{found_folder.get('_path','')}'")
    else:
        print("[i] No folder chosen; using the suite's direct children.")

    base_parent = folder_id or suite_id
    child_folders = children.get(base_parent, [])
    if not child_folders:
        node = (found_folder if folder_id else found_suite)
        child_folders = [node]
        print("[i] No child folders found; scanning the selected node itself for points.")
    print(f"[OK] Target suites to scan for points: {len(child_folders)}")

    point_to_folder: Dict[str, str] = {}
    total_points = 0
    for child in child_folders:
        cid = child["id"]
        cname = child.get("name")
        pts = list_points(plan_id, cid)
        total_points += len(pts)
        for p in pts:
            pid_val = str(p.get("id") or p.get("pointId"))
            if pid_val and pid_val != "None":
                point_to_folder[pid_val] = cname
    print(f"[OK] Collected {len(point_to_folder)} point mappings from {total_points} points.")

    START_DATE = first_env("START_DATE")
    END_DATE   = first_env("END_DATE")
    if not START_DATE or not END_DATE:
        raise SystemExit("Please set START_DATE and END_DATE in .env (UTC ISO8601).")
    if iso_parse(START_DATE) > iso_parse(END_DATE):
        raise SystemExit(f"START_DATE {START_DATE} is after END_DATE {END_DATE}.")

    RUN_DATE_MODE = (first_env("RUN_DATE_MODE", default="created") or "created").strip().lower()
    if RUN_DATE_MODE not in {"created","updated"}:
        RUN_DATE_MODE = "created"

    # Pull runs by chosen date mode; if none, retry the other mode automatically
    runs = list_test_runs(RUN_DATE_MODE, START_DATE, END_DATE, top=100)
    if not runs:
        alt = "updated" if RUN_DATE_MODE == "created" else "created"
        print(f"[i] No runs with mode={RUN_DATE_MODE}. Retrying with mode={alt}...")
        runs = list_test_runs(alt, START_DATE, END_DATE, top=100)
        RUN_DATE_MODE = alt

    print(f"[OK] Raw runs fetched (mode={RUN_DATE_MODE}): {len(runs)}")

    # Optional filters
    require_name = (first_env("REQUIRE_PLAN_IN_NAME", default="false") or "false").strip().lower() in ("1","true","yes")
    state_list = (first_env("RUN_STATES", default="Completed,InProgress,Aborted") or "").split(",")
    state_list = [s.strip().lower() for s in state_list if s.strip()]

    # Filter: plan (always)
    runs = [r for r in runs if str((r.get("plan") or {}).get("id")) == str(plan_id)]
    print(f"[OK] Runs after plan filter: {len(runs)}")

    # Filter: state (if any listed)
    if state_list:
        runs = [r for r in runs if (r.get("state") or "").strip().lower() in state_list]
    print(f"[OK] Runs after state filter {state_list}: {len(runs)}")

    # Filter: name contains plan name (optional)
    if require_name:
        plan_name = (plan.get("name") or "").strip().lower()
        if plan_name:
            runs = [r for r in runs if plan_name in (r.get("name","").strip().lower())]
        print(f"[OK] Runs after name-contains filter: {len(runs)}")

    print(f"[OK] Retrieved {len(runs)} runs in {START_DATE}..{END_DATE} for plan {plan_id}.")

    # ---- Compile results into a DataFrame ----
    rows: List[Dict[str, Any]] = []
    for run in runs:
        run_id = str(run.get("id"))
        run_name = run.get("name")
        started = run.get("createdDate") or run.get("startedDate")
        completed = run.get("completedDate")
        for res in list_run_results(run_id):
            ptid = str(res.get("pointId"))
            folder = point_to_folder.get(ptid)
            if not folder:
                continue
            rows.append({
                "folder": folder,
                "run_id": run_id,
                "run_name": run_name,
                "started": started,
                "completed": completed,
                "outcome": res.get("outcome"),
                "testCaseId": (res.get("testCase", {}) or {}).get("id"),
                "testCaseTitle": res.get("testCaseTitle") or (res.get("testCase", {}) or {}).get("name"),
                "configurationName": (res.get("configuration") or {}).get("name"),
                "owner": (run.get("owner") or {}).get("displayName"),
            })

    df = pd.DataFrame.from_records(rows)
    out_csv = Path(__file__).with_name("plan_runs_by_folder.csv")
    df.to_csv(out_csv, index=False)
    print(f"[OK] Compiled {len(df)} results across {len(runs)} runs from target suites.")
    print(f"[OK] Saved DataFrame to {out_csv}")

if __name__ == "__main__":
    main()
