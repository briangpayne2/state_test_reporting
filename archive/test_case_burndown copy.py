import os
import requests
import pandas as pd
from dotenv import dotenv_values
from urllib.parse import quote
from dateutil.parser import parse

# Load environment variables
env = dotenv_values(".env")
area_path = env["AREA_PATH"]
iteration_path = env["ITERATION_PATH"]
org = env["ADO_ORG"]
project = env["ADO_PROJECT"]
pat_token = env["ADO_PAT"]
plan_id = env["TEST_PLAN_ID"]
suite_id = env["TEST_SUITE_ID"]
suite_name = env["TARGET_SUITE_NAME"]
start_date = env["START_DATE"]
end_date = env["END_DATE"]
name_filter = env["NAME_FILTER"]
name_filter2 = env["NAME_FILTER_2"]
name_filter3 = env["NAME_FILTER_3"]
name_filter4 = env["NAME_FILTER_4"]
name_filter5 = env["NAME_FILTER_5"]
name_filter6 = env["NAME_FILTER_6"]
test_suite_plan = env["TEST_SUITE_PLAN"]


# Construct org and project URLs
org_url = f"https://dev.azure.com/{org}"
encoded_project = quote(project)

# Correct endpoint using testplan API area
url = f"{org_url}/{encoded_project}/_apis/testplan/plans/{plan_id}?api-version=6.0-preview.1"

auth = requests.auth.HTTPBasicAuth("", pat_token)
headers = {"Content-Type": "application/json"}

# Call the API
print(f"Fetching test plan...\nURL: {url}")
response = requests.get(url, headers=headers, auth=auth)

# Show result
print("Status:", response.status_code)
if response.ok:
    data = response.json()
    print(" Test Plan Found:")
    print("  ID:", data.get("id"))
    print("  Name:", data.get("name"))
    print("  State:", data.get("state"))
else:
    print(" Error:", response.text[:500])


############################
# # Step 1: Fetch all suites
# suites_url = f"{org_url}/{encoded_project}/_apis/testplan/Plans/{plan_id}/suites?api-version=6.0"
# suites_resp = requests.get(suites_url, headers=headers, auth=auth)
# descendant_suite_ids = []

# if suites_resp.ok:
#     all_suites = suites_resp.json().get("value", [])

#     # Recursively collect suite IDs under suite_id (e.g. 6619)
#     def collect_descendants(parent_id):
#         children = [s for s in all_suites if s.get("parent", {}).get("id") == parent_id]
#         for child in children:
#             descendant_suite_ids.append(child["id"])
#             collect_descendants(child["id"])

#     collect_descendants(int(suite_id))
#     print(f"Found {len(descendant_suite_ids)} child suites under Suite ID {suite_id}")
# else:
#     print("Failed to fetch suite list.")

# # Step 2: Fetch test cases in each descendant suite
# suite_cases = []
# for sid in descendant_suite_ids:
#     tc_url = f"{org_url}/{encoded_project}/_apis/testplan/Plans/{plan_id}/Suites/{sid}/TestCase?api-version=7.1-preview.3"
#     tc_resp = requests.get(tc_url, headers=headers, auth=auth)
#     if tc_resp.ok:
#         suite_cases.extend(tc_resp.json().get("value", []))

# print(f"Total test cases found across child suites: {len(suite_cases)}")
# suite_case_ids = [tc["testCase"]["id"] for tc in suite_cases if "testCase" in tc]

# # Step 3: Fetch results only for those test cases
# results = []
# runs_url = f"{org_url}/{encoded_project}/_apis/test/runs?planId={plan_id}&$top=200&api-version=7.1-preview.2"
# runs_resp = requests.get(runs_url, headers=headers, auth=auth)

# if runs_resp.ok:
#     for run in runs_resp.json().get("value", []):
#         run_id = run["id"]
#         results_url = f"{org_url}/{encoded_project}/_apis/test/Runs/{run_id}/results?api-version=7.1-preview.6"
#         results_resp = requests.get(results_url, headers=headers, auth=auth)
#         if results_resp.ok:
#             for result in results_resp.json().get("value", []):
#                 case_id = result.get("testCase", {}).get("id")
#                 if case_id in suite_case_ids:
#                     results.append({
#                         "TestCaseID": case_id,
#                         "Title": result.get("testCaseTitle"),
#                         "Outcome": result.get("outcome"),
#                         "CompletedDate": result.get("completedDate"),
#                         "State": result.get("state")
#                     })

# # Step 4: Deduplicate to latest test result per test case
# results_df = pd.DataFrame(results)
# results_df["CompletedDate"] = pd.to_datetime(results_df["CompletedDate"], errors='coerce')
# latest_results_df = (
#     results_df.sort_values("CompletedDate", ascending=False)
#               .drop_duplicates(subset="TestCaseID", keep="first")
#               .reset_index(drop=True)
# )

# # Step 5: Merge in suite titles
# suite_titles_df = pd.DataFrame([
#     {"TestCaseID": tc["testCase"]["id"], "TitleFromSuite": tc["testCase"]["name"]}
#     for tc in suite_cases if "testCase" in tc
# ])

# latest_results_df["TestCaseID"] = latest_results_df["TestCaseID"].astype(str)
# suite_titles_df["TestCaseID"] = suite_titles_df["TestCaseID"].astype(str)

# joined_df = latest_results_df.merge(suite_titles_df, on="TestCaseID", how="left")
# joined_df["Title"] = joined_df["TitleFromSuite"].combine_first(joined_df["Title"])
# joined_df.drop(columns=["TitleFromSuite"], inplace=True)

# print("Final joined results with test case titles from suite hierarchy:")
# print(joined_df)


# ######################################
# Load name filters from environment
filters = [
    name_filter,
    name_filter2,
    #name_filter3,
    #name_filter4,
    #name_filter5,
    #name_filter6,
]

# Step 1: Fetch all suites in flat format
suites_url = f"{org_url}/{encoded_project}/_apis/testplan/Plans/{plan_id}/suites?api-version=6.0"
suites_resp = requests.get(suites_url, headers=headers, auth=auth)

all_points = []

if suites_resp.ok:
    all_suites = suites_resp.json().get("value", [])

    # Step 2: Match suites if any filter matches the name (case-insensitive)
    target_suites = [
        s for s in all_suites
        if any(f.lower() in s.get("name", "").lower() for f in filters if f)
    ]
    print(f"Found {len(target_suites)} suites matching any of: {filters}")

    # Step 3: Pull test points from each matched suite
    for suite in target_suites:
        sid = suite["id"]
        points_url = f"{org_url}/{encoded_project}/_apis/test/Plans/{plan_id}/Suites/{sid}/Points?api-version=7.1-preview.2"
        response = requests.get(points_url, headers=headers, auth=auth)

        if response.ok:
            for pt in response.json().get("value", []):
                test_point_id = pt.get("id")
                title = pt.get("testCase", {}).get("name", "")
                outcome = pt.get("outcome", "")
                last_result = pt.get("lastTestResult", {})
                passed_date = closed_date = None
                if last_result:
                    if last_result.get("outcome") == "Passed":
                        passed_date = last_result.get("completedDate")
                    if last_result.get("state") == "Completed":
                        closed_date = last_result.get("completedDate")
                
                test_case_id = pt.get("testCase", {}).get("id", "")

                all_points.append({
                    "TestPointID": test_point_id,
                    "TestCaseID": test_case_id,
                    "Title": title,
                    "Outcome": outcome,
                    "PassedDate": passed_date,
                    "ClosedDate": closed_date
                })

print("Collecting test result dates...")

runs_url = f"{org_url}/{encoded_project}/_apis/test/runs?planId={plan_id}&$top=200&api-version=7.1-preview.2"
runs_resp = requests.get(runs_url, headers=headers, auth=auth)

if runs_resp.ok:
    runs = runs_resp.json().get("value", [])
    for run in runs:
        run_id = run["id"]
        results_url = f"{org_url}/{encoded_project}/_apis/test/Runs/{run_id}/results?api-version=7.1-preview.6"
        results_resp = requests.get(results_url, headers=headers, auth=auth)

        if results_resp.ok:
            results = results_resp.json().get("value", [])
            for result in results:
                result_case_id = result.get("testCase", {}).get("id")
                outcome = result.get("outcome")
                completed = result.get("completedDate")

                print(f"Result Case ID: {result_case_id}, Completed: {completed}")

                for entry in all_points:
                    if str(result_case_id) == str(entry["TestCaseID"]):
                        print(f"Matched TestCaseID {result_case_id} to entry {entry['Title']}")
                        if outcome == "Passed":
                            entry["PassedDate"] = completed
                        if result.get("state") == "Completed":
                            entry["ClosedDate"] = completed

# Step: Enrich test points with PassedDate / ClosedDate from Results API
runs_url = f"{org_url}/{encoded_project}/_apis/test/runs?planId={plan_id}&$top=50&api-version=7.1-preview.2"
runs_resp = requests.get(runs_url, headers=headers, auth=auth)

if runs_resp.ok:
    runs = runs_resp.json().get("value", [])
    for run in runs:
        run_id = run["id"]
        results_url = f"{org_url}/{encoded_project}/_apis/test/Runs/{run_id}/results?api-version=7.1-preview.6"
        results_resp = requests.get(results_url, headers=headers, auth=auth)

        if results_resp.ok:
            results = results_resp.json().get("value", [])
            for result in results:
                print(f"Result Case ID: {result.get('testCase', {}).get('id')}, Completed: {result.get('completedDate')}")
                # title = result.get("automatedTestName") or result.get("testCaseTitle")
                outcome = result.get("outcome")
                completed = result.get("completedDate")
                # for entry in all_points:
                #     if title and title in entry["Title"]:
                result_case_id = result.get("testCase", {}).get("id")
                for entry in all_points:
                    if result_case_id == entry["TestCaseID"]:
                        print(f"Matched TestCaseID {result_case_id} to entry {entry['Title']}")
                        if outcome == "Passed":
                            entry["PassedDate"] = completed
                        if result.get("state") == "Completed":
                            entry["ClosedDate"] = completed
# Step: Capture dates directly from test results
captured_results = []

runs_url = f"{org_url}/{encoded_project}/_apis/test/runs?planId={plan_id}&$top=200&api-version=7.1-preview.2"
runs_resp = requests.get(runs_url, headers=headers, auth=auth)

if runs_resp.ok:
    for run in runs_resp.json().get("value", []):
        run_id = run["id"]
        results_url = f"{org_url}/{encoded_project}/_apis/test/Runs/{run_id}/results?api-version=7.1-preview.6"
        results_resp = requests.get(results_url, headers=headers, auth=auth)
        if results_resp.ok:
            for result in results_resp.json().get("value", []):
                captured_results.append({
                    "TestCaseID": result.get("testCase", {}).get("id"),
                    "Title": result.get("testCaseTitle"),
                    "Outcome": result.get("outcome"),
                    "CompletedDate": result.get("completedDate"),
                    "State": result.get("state"),
                })

# Step: Build results DataFrame
results_df = pd.DataFrame(captured_results)
# print("Test Results (Direct):")
# print(results_df)
# Drop invalid/missing TestCaseIDs
valid_results_df = results_df[results_df["TestCaseID"].notna()].copy()

# Convert to string for consistency
valid_results_df["TestCaseID"] = valid_results_df["TestCaseID"].astype(str)

# Deduplicate on the most recent result per TestCaseID
valid_results_df["CompletedDate"] = pd.to_datetime(valid_results_df["CompletedDate"], errors='coerce')
latest_results_df = (
    valid_results_df.sort_values("CompletedDate", ascending=False)
                    .drop_duplicates(subset="TestCaseID", keep="first")
                    .reset_index(drop=True)
)

# Optional: Preview
print(f" Unique test cases found: {latest_results_df['TestCaseID'].nunique()}")
print(latest_results_df)

################## PLOT BURNDOWN ##################

import matplotlib.pyplot as plt
import pandas as pd

# Read planned burndown from Excel
planned_df = pd.read_csv(test_suite_plan)
planned_df["Date"] = pd.to_datetime(
    planned_df["Date"], format='mixed', dayfirst=False, errors='coerce'
).dt.tz_localize("America/New_York")

# Ensure CompletedDate is datetime
latest_results_df["CompletedDate"] = pd.to_datetime(latest_results_df["CompletedDate"], errors='coerce')
latest_results_df["CompletedDate"] = pd.to_datetime(
    latest_results_df["CompletedDate"], errors='coerce'
).dt.tz_convert("America/New_York")

# Set start and end date
plot_start_date = pd.to_datetime(start_date).tz_localize("America/New_York")
plot_end_date = pd.to_datetime(end_date).tz_localize("America/New_York")
date_range = pd.date_range(start=plot_start_date, end=plot_end_date, freq="D")

# Total number of test cases
total_cases = latest_results_df["TestCaseID"].nunique()

# Actual burndown logic (only Passed outcomes)
total_cases = latest_results_df["TestCaseID"].nunique()
burndown = []
for date in date_range:
    passed = latest_results_df[
        (latest_results_df["CompletedDate"] <= date) &
        (latest_results_df["Outcome"] == "Passed")
    ]
    remaining = total_cases - passed["TestCaseID"].nunique()
    burndown.append(remaining)

# Plot both actual and planned burndown
plt.figure(figsize=(10, 6))
plt.plot(date_range, burndown, marker='o', linestyle='-', label='Actual Remaining')
plt.plot(planned_df["Date"], planned_df["PlannedRemaining"], marker='x', linestyle='--', label='Planned Remaining')
plt.title("Test Case Completion Burndown (Actual vs Planned)")
plt.xlabel("Date")
plt.ylabel("Remaining Test Cases")
plt.grid(True)
plt.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig("charts/test_case_burndown_with_plan.jpg", format="jpg", dpi=300)