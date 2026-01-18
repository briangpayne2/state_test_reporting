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
def base_url():
    return "https://dev.azure.com/flwins/FL%20WINS"

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
import requests
import url_config
import base64
import os

# Get the PAT from the .env or environment variable
if not pat_token:
    raise ValueError("AZURE_PAT not found in environment variables.")

# Azure DevOps uses Basic Auth with the PAT as the password
headers = {
    "Content-Type": "application/json",
    "Authorization": "Basic " + base64.b64encode(f":{pat_token}".encode()).decode()
}
# Fetch test suites in the test plan
suite_url = f"{base_url()}/_apis/testplan/Plans/{plan_id}/suites?api-version=6.0"
suites_response = requests.get(suite_url, headers=headers)

# Debug output
print(f"Suite fetch status: {suites_response.status_code}")
print("Response text preview:")
print(suites_response.text[:300])  # print first 300 chars to avoid huge logs

# Safely try to parse JSON
try:
    suites = suites_response.json().get("value", [])
except Exception as e:
    print("❌ Failed to parse JSON for suites_response:", e)
    suites = []

test_plans = []
for suite in suites:
    suite_id = suite["id"]
    
    # Fetch test runs for each suite
    runs_url = f"{url_config.base_url()}/_apis/test/runs?planId={plan_id}&includeRunDetails=true&$top=1000&api-version=6.0"
    runs_response = requests.get(runs_url, headers=headers)
    runs = runs_response.json().get("value", [])

    # For each run, get its test results
    for run in runs:
        run_id = run["id"]
        results_url = f"{base_url}/_apis/test/Runs/{run_id}/results?api-version=6.0"
        results_response = requests.get(results_url, headers=headers)
        run["results"] = results_response.json().get("value", [])

    test_plans.append({
        "suites": [
            {
                "id": suite_id,
                "runs": runs
            }
        ]
    })

# You can now use `test_plans` below

# === Rewritten: Fetch and filter test runs by name, iteration, and date ===
import pandas as pd
from datetime import datetime

# Step 1: Flatten all test runs
filtered_runs = []
for plan in test_plans:
    for suite in plan['suites']:
        for run in suite.get('runs', []):
            run_date = datetime.strptime(run['completedDate'], '%Y-%m-%dT%H:%M:%S.%fZ')
            name_match = any(substr.lower() in run['name'].lower() for substr in filters)
            in_date_range = start_date <= run_date <= end_date
            
            if name_match and in_date_range:
                for result in run.get('results', []):
                    filtered_runs.append({
                        'Run ID': run['id'],
                        'Test Case': result.get('testCaseTitle', ''),
                        'Outcome': result.get('outcome', 'Unknown'),
                        'Date': run_date.date()
                    })

# Step 2: Create DataFrame and print
df = pd.DataFrame(filtered_runs)
print("Filtered Test Runs:")
print(df)
