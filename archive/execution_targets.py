import pandas as pd
import requests
from dotenv import dotenv_values
from urllib.parse import quote
import os

env = dotenv_values(".env")  # fallback source

def get_env(key):
    return os.getenv(key, env.get(key))
# Load environment variables
#env = dotenv_values(".env")
org = get_env("ADO_ORG")
project = get_env("ADO_PROJECT")
pat_token = get_env("ADO_PAT")
plan_name = get_env("TEST_PLAN_NAME")
plan_id = get_env("TEST_PLAN_ID")
suite_name = get_env("TEST_SUITE_NAME")
parent_suite_id = get_env("TEST_SUITE_ID")

org_url = f"https://dev.azure.com/{org}"
encoded_project = quote(project)
auth = requests.auth.HTTPBasicAuth("", pat_token)
headers = {"Content-Type": "application/json"}

def get_child_suites_by_filter(plan_id, parent_suite_id):
    url = f"{org_url}/{encoded_project}/_apis/test/plans/{plan_id}/suites?api-version=6.0"
    print("🔍 DEBUG ENV VALUES")
    print(f"org_url: {org_url!r}")
    print(f"encoded_project: {encoded_project!r}")
    print(f"plan_id: {plan_id!r}")
    print(f"parent_suite_id: {parent_suite_id!r}")
    print(f"url: {url}")

    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    suites = response.json().get("value", [])
    return [s for s in suites if str(s.get("parentSuite", {}).get("id")) == str(parent_suite_id)]

def get_all_test_runs(plan_id):
    url = f"{org_url}/{encoded_project}/_apis/test/runs?planId={plan_id}&includeRunDetails=true&api-version=6.0"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    return response.json()["value"]

def get_test_results_for_run(run_id):
    url = f"{org_url}/{encoded_project}/_apis/test/runs/{run_id}/results?api-version=6.0"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    return response.json()["value"]

if __name__ == "__main__":
    child_suites = get_child_suites_by_filter(plan_id, parent_suite_id)
    df = pd.DataFrame([{"id": suite["id"], "name": suite["name"]} for suite in child_suites])
    print(df)

#### Gather the test cases inside each child suite #####
#### and place them into a dataframe #####

def get_test_cases(plan_id, suite_id):
    url = f"{org_url}/{encoded_project}/_apis/testplan/Plans/{plan_id}/suites/{suite_id}/testcases?api-version=6.0-preview.2"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    return response.json()["value"]

def get_test_cases_from_points(plan_id, suite_id):
    url = f"{org_url}/{encoded_project}/_apis/test/plans/{plan_id}/suites/{suite_id}/points?api-version=7.1-preview.2"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    return response.json()["value"]

def get_all_descendant_suite_ids(plan_id, parent_suite_id):
    url = f"{org_url}/{encoded_project}/_apis/test/plans/{plan_id}/suites?api-version=6.0"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    all_suites = response.json()["value"]
    return [s["id"] for s in all_suites if str(s.get("parentSuite", {}).get("id")) == str(parent_suite_id)]

def list_all_test_plans():
    url = f"{org_url}/{encoded_project}/_apis/testplan/plans?api-version=6.0"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    plans = response.json()["value"]
    for p in plans:
        print(f"ID: {p['id']}  |  Name: {p['name']}")

list_all_test_plans()

if __name__ == "__main__":
    child_suite_ids = get_all_descendant_suite_ids(plan_id, parent_suite_id)
    target_suite_ids = set(child_suite_ids + [int(parent_suite_id)])

    # Collect all test cases
test_cases_data = []

for suite in child_suites:
    suite_id = suite["id"]
    suite_name = suite["name"]
    try:
        points = get_test_cases_from_points(plan_id, suite_id)
        for pt in points:
            test_case = pt["testCase"]
            test_cases_data.append({
                "suite_id": suite_id,
                "suite_name": suite_name,
                "test_case_id": test_case["id"],
                "test_case_name": test_case.get("name", ""),  # fallback if no title
                "test_case_url": test_case["url"]
            })
    except requests.HTTPError as e:
        print(f"Failed to get test points for suite {suite_id}: {e}")

df = pd.DataFrame(test_cases_data)

def get_work_item_titles(ids):
    ids_str = ",".join(ids)
    url = f"https://dev.azure.com/{org}/_apis/wit/workitems?ids={ids_str}&fields=System.Title&api-version=6.0"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    items = response.json()["value"]
    return {str(item["id"]): item["fields"]["System.Title"] for item in items}

# Extract unique IDs
unique_ids = list({str(row["test_case_id"]) for row in test_cases_data})
titles_map = get_work_item_titles(unique_ids)

# Add titles to DataFrame
df["test_case_title"] = df["test_case_id"].astype(str).map(titles_map)

print(df)

##### Generate Burndown Chart #####

from datetime import datetime, timedelta
import matplotlib.pyplot as plt

# Parse env dates
start_date = datetime.strptime(get_env("START_DATE"), "%Y-%m-%d")
end_date = datetime.strptime(get_env("END_DATE"), "%Y-%m-%d")

# Build time series of execution dates
execution_dates = []

for suite in child_suites:
    suite_id = suite["id"]
    try:
        
        url = f"{org_url}/{encoded_project}/_apis/test/plans/{plan_id}/suites/{suite_id}/points?api-version=7.1-preview.2"
        response = requests.get(url, headers=headers, auth=auth)
        response.raise_for_status()
        points = response.json()["value"]

        for pt in points:
            exec_time = pt.get("lastResultDetails", {}).get("dateCompleted")
            if exec_time:
                exec_date = datetime.strptime(exec_time[:10], "%Y-%m-%d")
                if start_date <= exec_date <= end_date:
                    execution_dates.append(exec_date)

    except requests.HTTPError as e:
        print(f"Failed to fetch points for suite {suite_id}: {e}")

# Count executions per day
date_range = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
counts = {d.date(): 0 for d in date_range}
for d in execution_dates:
    counts[d.date()] += 1

from collections import defaultdict

execution_dates = []
retest_dates = []

# Track executions by testCase ID
execution_history = defaultdict(list)

test_runs = get_all_test_runs(plan_id)
for run in test_runs:
    run_id = run["id"]
    print(f"Fetching results for run {run_id}... ({run['name']})")
    try:
        results = get_test_results_for_run(run_id)
        for result in results:
            # Only include results from the selected test suite
            suite_id = result.get("suite", {}).get("id")
            if suite_id not in target_suite_ids:
                continue

            tc_id = result["testCase"]["id"]
            outcome = result.get("outcome", "Unknown")
            date_str = result.get("startedDate") or result.get("completedDate")
            if date_str:
                exec_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
                if start_date <= exec_date <= end_date:
                    execution_history[tc_id].append((exec_date, outcome))

    except requests.HTTPError as e:
        print(f"Error loading results for run {run_id}: {e}")

# Split out re-tests
daily_executions = defaultdict(int)
daily_retests = defaultdict(int)

for test_case_id, runs in execution_history.items():
    # Ensure chronological order
    runs.sort()
    last_outcome = None
    failure_date = None

    for date, outcome in runs:
        run_day = date.date()
        daily_executions[run_day] += 1

        if outcome == "Failed":
            failure_date = run_day
            last_outcome = "Failed"

        elif outcome == "Passed":
            # Register re-test only if the last result was a failure
            if last_outcome == "Failed":
                daily_retests[run_day] += 1
                failure_date = None  # Reset after re-test
            last_outcome = "Passed"

        else:
            last_outcome = outcome  # Track other transitions too

# Prepare full date range
date_range = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
dates = [d.date() for d in date_range]
executions = [daily_executions[d] for d in dates]
retests = [daily_retests[d] for d in dates]

# Plot
test_suite_name = get_env("TEST_SUITE_NAME")
plt.figure(figsize=(10, 5))
plt.plot(dates, executions, marker='o', label="Total Executed")
plt.plot(dates, retests, marker='x', label="Re-tested After Bug")
plt.title("Test Case Execution Chart")
plt.suptitle(f"Test Plan: {plan_name} | Test Suite: {test_suite_name}", fontsize=10, y=0.96)
plt.xlabel("Date")
plt.ylabel("# of Test Cases")
plt.legend()
plt.grid(True)
plt.xticks(rotation=45)
plt.tight_layout()
# plt.show()

import numpy as np

# Prepare date-to-index mapping for regression
x_vals = np.arange(len(dates))  # day indices
y_vals = np.array(executions)

# Fit a simple linear model: y = mx + b
coeffs = np.polyfit(x_vals, y_vals, 1)
trend_fn = np.poly1d(coeffs)

# Project next 5 days
projection_days = 5
future_x = np.arange(len(dates), len(dates) + projection_days)
future_dates = [dates[-1] + timedelta(days=i + 1) for i in range(projection_days)]
future_y = trend_fn(future_x)

# Plot trendline
plt.plot(future_dates, future_y, linestyle="--", color="gray", label="Projected Executed")

# Extend x-axis to fit projection
dates += future_dates
executions += [None] * projection_days  # Keep shape aligned for ticks

plt.savefig("charts/" + test_suite_name + "_execution.jpg", format='jpg', bbox_inches="tight")