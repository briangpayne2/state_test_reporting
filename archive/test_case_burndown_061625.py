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
