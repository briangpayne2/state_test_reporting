#!/usr/bin/env python3
import base64
from urllib.parse import quote
from typing import Dict, Any, List, Optional
import requests
from dotenv import dotenv_values
import pandas as pd

# ---- .env ----
cfg = dotenv_values(".env")
ADO_ORG         = (cfg.get("ADO_ORG") or "").strip()
ADO_PROJECT     = (cfg.get("ADO_PROJECT") or "").strip()
ADO_PAT         = (cfg.get("ADO_PAT") or "").strip()
TEST_PLAN_NAME  = (cfg.get("TEST_PLAN_NAME") or "").strip()
START_DATE      = (cfg.get("START_DATE") or "").strip()  # optional
END_DATE        = (cfg.get("END_DATE") or "").strip()    # optional

if not (ADO_ORG and ADO_PROJECT and ADO_PAT and TEST_PLAN_NAME):
    raise SystemExit("Missing ADO_ORG, ADO_PROJECT, ADO_PAT, or TEST_PLAN_NAME in .env")

# ---- API bases ----
BASE = (ADO_ORG if ADO_ORG.startswith(("http://","https://"))
        else f"https://dev.azure.com/{ADO_ORG}").rstrip("/")
PROJECT_PATH = quote(ADO_PROJECT, safe="")
TESTPLAN_API_VER = "7.1-preview.1"
VER_POINTS  = ["7.1-preview.2", "7.1-preview.1", "7.0", "6.0"]
VER_RUNS    = ["7.1-preview.7", "7.1-preview.1", "7.0", "6.0"]
VER_RESULTS = ["7.1-preview.6", "7.1-preview.1", "7.0", "6.0"]

def H():  # headers
    tok = base64.b64encode(f":{ADO_PAT}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "Accept": "application/json"}

def urlp(suffix: str) -> str:
    return f"{BASE}/{PROJECT_PATH}{suffix if suffix.startswith('/') else '/'+suffix}"

def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = requests.get(url, headers=H(), params=params or {})
    print(f"GET {r.url}")
    if r.status_code >= 400:
        raise SystemExit(f"{r.status_code} {r.text}")
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

# ---------- Plans & suites ----------
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

# ---------- Points / runs / results ----------
def get_points_for_suite(plan_id: str, suite_id: str) -> List[Dict[str, Any]]:
    pts = get_json_paginated_fallback(
        urlp("/_apis/test/points"), VER_POINTS,
        params={"planId": plan_id, "suiteId": suite_id}, value_key="value"
    )
    for p in pts:
        if "id" in p: p["id"] = int(p["id"])
    return pts

def list_runs_for_plan(plan_id: str, start: str, end: str) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"planId": plan_id}
    if start: params["minLastUpdatedDate"] = start
    if end:   params["maxLastUpdatedDate"] = end
    runs = get_json_paginated_fallback(urlp("/_apis/test/runs"), VER_RUNS, params=params)
    for r in runs: r["id"] = int(r["id"])
    print(f"[OK] {len(runs)} run(s) for plan {plan_id}")
    return runs

def list_results_for_run(run_id: int) -> List[Dict[str, Any]]:
    results = get_json_paginated_fallback(urlp(f"/_apis/test/Runs/{run_id}/results"),
                                          VER_RESULTS, params={})
    for r in results:
        if "id" in r: r["id"] = int(r["id"])
        if "testPoint" in r and isinstance(r["testPoint"], dict) and "id" in r["testPoint"]:
            r["pointId"] = int(r["testPoint"]["id"])
        elif "pointId" in r and r["pointId"] is not None:
            r["pointId"] = int(r["pointId"])
    return results

# ---------- Orchestration ----------
def main():
    plan_id = resolve_plan_id_by_name(TEST_PLAN_NAME)
    suites = list_suites(plan_id)

    # Build parent map & identify top-level suites (the 4 folders you showed)
    by_id = {s["id"]: s for s in suites}
    top_level = [s for s in suites if s.get("parentId") is None]
    print("[OK] Top-level suites:", ", ".join(s["name"] for s in top_level))

    # For every suite, compute its top-level ancestor
    def top_ancestor(sid: str) -> str:
        cur = by_id[sid]
        while cur.get("parentId") is not None:
            cur = by_id[cur["parentId"]]
        return cur["id"]

    # Collect point -> top-level suite mapping (aggregate descendants up)
    top_points: Dict[str, List[int]] = {s["id"]: [] for s in top_level}
    point_to_top: Dict[int, str] = {}
    for s in suites:
        sid = s["id"]
        pts = get_points_for_suite(plan_id, sid)
        pids = [p["id"] for p in pts if "id" in p]
        if not pids: continue
        tid = top_ancestor(sid)
        top_points[tid].extend(pids)
        for pid in pids: point_to_top[pid] = tid
        print(f"  - Suite '{s['name']}' (ID={sid}) contributes {len(pids)} points to top '{by_id[tid]['name']}'")

    # Fetch runs for the plan once
    runs = list_runs_for_plan(plan_id, START_DATE, END_DATE)

    # Gather results per top-level suite
    results_by_top: Dict[str, List[Dict[str, Any]]] = {s["id"]: [] for s in top_level}
    for run in runs:
        rid = run["id"]
        for res in list_results_for_run(rid):
            pid = res.get("pointId")
            if pid is None: continue
            tid = point_to_top.get(pid)
            if not tid:     continue
            res["_planId"] = int(plan_id)
            res["_topSuiteId"] = tid
            res["_runId"] = rid
            res["_runName"] = run.get("name")
            res["_automated"] = run.get("isAutomated")
            results_by_top[tid].append(res)

    # Build 1 DataFrame per top-level suite
    wanted = [
        "_planId", "_topSuiteId", "_runId", "_runName",
        "id", "outcome", "state",
        "testCase", "testCaseTitle",
        "testPoint", "pointId",
        "startedDate", "completedDate",
        "durationInMs", "_automated",
        "owner", "area", "configuration", "priority"
    ]
    name_by_id = {s["id"]: s["name"] for s in top_level}
    dfs: Dict[str, pd.DataFrame] = {}

    for tid, rows in results_by_top.items():
        df = pd.DataFrame(rows)
        if "testCase" in df.columns:
            df["testCaseId"] = df["testCase"].apply(lambda x: (x or {}).get("id") if isinstance(x, dict) else None)
            df["testCaseName"] = df["testCase"].apply(lambda x: (x or {}).get("name") if isinstance(x, dict) else None)
        if "configuration" in df.columns:
            df["configurationName"] = df["configuration"].apply(lambda x: (x or {}).get("name") if isinstance(x, dict) else None)
        if "owner" in df.columns:
            df["ownerName"] = df["owner"].apply(lambda x: (x or {}).get("displayName") if isinstance(x, dict) else None)
        cols = [c for c in wanted + ["testCaseId","testCaseName","configurationName","ownerName"] if c in df.columns]
        if cols: df = df[cols]
        dfs[tid] = df
        print(f"[DF] {name_by_id[tid]}: {len(df)} rows")
        # Optional save:
        safe = name_by_id[tid].replace("/", "_").replace("\\", "_")
        df.to_csv(f"results_{safe}.csv", index=False)

    print("\n=== SUMMARY ===")
    for tid, df in dfs.items():
        print(f"{name_by_id[tid]} → {len(df)} rows")

    # If you need them by name:
    dataframes_by_suite_name = {name_by_id[k]: v for k, v in dfs.items()}

if __name__ == "__main__":
    main()