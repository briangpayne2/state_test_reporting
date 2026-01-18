import os
import sys
from dotenv import dotenv_values
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from io import BytesIO
import base64
from datetime import datetime
from zoneinfo import ZoneInfo
EST = ZoneInfo("America/New_York")

# Load .env
env_path = ".env"
config = dotenv_values(env_path)

# Print diagnostics
# NOTE (security): avoid printing secrets like ADO_PAT in real logs.
# Data QA angle: configuration-driven filters make the report reproducible across teams/sprints.
print("Loaded .env values:")
for k in config:
    print(f"  {k}: {config[k]}")

# Required keys
required_keys = ["ADO_ORG", "ADO_PROJECT", "ADO_PAT", "AREA_PATH", "ITERATION_PATH", "START_DATE", "END_DATE"]
missing = [key for key in required_keys if config.get(key) in [None, ""]]
if missing:
    print(f"\n ERROR: Missing required .env values: {', '.join(missing)}")
    exit(1)

# Assign variables
organization = config["ADO_ORG"]
project = config["ADO_PROJECT"]
pat = config["ADO_PAT"]
area_path = config["AREA_PATH"]
iteration_path = config["ITERATION_PATH"]
start_date = datetime.fromisoformat(config["START_DATE"])
end_date = datetime.fromisoformat(config["END_DATE"])

# ----------------------------
# WIQL (ADO "SQL" for work items)
# ----------------------------
# WIQL = Work Item Query Language. It's Azure DevOps' SQL-like query language for work items.
# Conceptually:
#   SELECT <fields>
#   FROM workitems
#   WHERE <filters>
# We use WIQL to return a lightweight list of work item IDs, then pull full details in batches.

# Step 1: Run WIQL to get matching work item IDs only (fast and lightweight).
# Step 2: Use WorkItemsBatch to pull full field details in batches (API limits).
wiql_query = {
    "query": f"""
    -- Projection: choose the fields we need (similar to SQL SELECT columns)
    SELECT
        [System.Id],
        [System.WorkItemType],
        [System.Title],
        [System.AssignedTo],
        [System.State],
        [System.Tags],
        [Microsoft.VSTS.Common.ClosedDate],
        [System.CreatedDate]
    FROM workitems
    WHERE
        -- Scope to one Team Project (tenant-like filter)
        [System.TeamProject] = '{project}'
        AND (
            -- Only bugs within the requested AreaPath + IterationPath
            [System.WorkItemType] = 'Bug'
            AND [System.AreaPath] = '{area_path}'
            AND [System.IterationPath] = '{iteration_path}'
            AND (
                -- Time window filter (CreatedDate within START_DATE..END_DATE)
                [System.CreatedDate] >= '{start_date.isoformat()}'
                AND [System.CreatedDate] <= '{end_date.isoformat()}'
            )
        )
    """
}

# PAT setup
auth_header = base64.b64encode(f":{pat}".encode()).decode()
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {auth_header}"
}

# WIQL URL
wiql_url = f"https://dev.azure.com/{organization}/{project}/_apis/wit/wiql?api-version=6.0"
print(f"\nWIQL URL: {wiql_url}")

# Send WIQL query
response = requests.post(wiql_url, headers=headers, json=wiql_query)
if response.status_code != 200:
    print(f"\n ADO request failed: {response.status_code}")
    print("Response:", response.text)
    exit(1)

work_item_ids = [item["id"] for item in response.json().get("workItems", [])]
print(f"\n Retrieved {len(work_item_ids)} work item IDs")

# Hydrate work item details
# WIQL returns only matching IDs. We then call the WorkItemsBatch endpoint to fetch fields
# for many work items at once (similar to fetching rows by primary key in batches).
# Batching reduces API calls and helps stay within payload/limit constraints.
def fetch_work_items(ids):
    url = f"https://dev.azure.com/{organization}/_apis/wit/workitemsbatch?api-version=6.0"
    body = {
        "ids": ids,
        "fields": [
            "System.Id", "System.WorkItemType", "System.Title", "System.AssignedTo",
            "System.State", "System.Tags", "Microsoft.VSTS.Common.ClosedDate", "System.CreatedDate"
        ]
    }
    return requests.post(url, headers=headers, json=body).json()

data = []
# Pull work items in chunks to avoid overly large request bodies
for i in range(0, len(work_item_ids), 200):
    batch = work_item_ids[i:i+200]
    result = fetch_work_items(batch)
    for item in result.get("value", []):
        f = item["fields"]
        data.append({
        "Id": f.get("System.Id"),
        "Title": f.get("System.Title", ""),
        "CreatedDate": f.get("System.CreatedDate"),
        "ClosedDate": f.get("Microsoft.VSTS.Common.ClosedDate"),
        "Tags": f.get("System.Tags", "")  
    })

df = pd.DataFrame(data)

if df.empty:
    print("No bugs found for the given date range and filters.")
    sys.exit(0)

# Normalize timestamps
# ADO returns ISO 8601 strings. We parse them as UTC to avoid timezone drift in comparisons.
# Later we convert boundaries to EST for "business day" reporting.
df["CreatedDate"] = pd.to_datetime(df["CreatedDate"], format='mixed', errors='coerce', utc=True)
df["ClosedDate"] = pd.to_datetime(df["ClosedDate"], format='mixed', errors='coerce', utc=True)

# Tag categories (simple classification)
# Data QA angle: categorizing work items lets you segment quality trends (e.g., exploratory vs system defects).
df["Exploratory"] = df["Tags"].fillna("").str.lower().str.contains("exploratory")
df["TestCase"] = df["Tags"].fillna("").str.lower().str.contains("test case update")
df["PEGA"] = df["Tags"].fillna("").str.lower().str.contains("pega")

print("Exploratory count:", df["Exploratory"].sum())
print("TestCase count:", df["TestCase"].sum())

# Optional: show matches
print(df[df["Exploratory"]])
print(df[df["TestCase"]])
print(df[df["PEGA"]])

# ---- Burndown (EST plotting, UTC filtering) ----
import matplotlib.dates as mdates
EST = ZoneInfo("America/New_York")

# 1) Build local (EST) day index
start_local = pd.to_datetime(start_date).tz_localize(EST).normalize()
end_local   = pd.to_datetime(end_date).tz_localize(EST).normalize()
date_index_local = pd.date_range(start_local, end_local, freq="D", tz=EST)

# 2) Accumulate counts; plot with pure date objects (no time, no tz)
burndown_all, burndown_exploratory, burndown_nonexploratory, burndown_testcase, burndown_pega = [], [], [], [], []

# Burndown rule (deterministic):
# A bug is "open" on a given day boundary if:
#   CreatedDate <= boundary AND (ClosedDate is null OR ClosedDate > boundary)
# This is the same idea as point-in-time reconciliation in data QA.

for dt_local in date_index_local:
    boundary_utc = dt_local.tz_convert("UTC")   # compare in UTC (df is UTC)
    d_plot = dt_local.date()                    # plot as naive date (EST calendar day)

    open_all = df[(df["CreatedDate"] <= boundary_utc) &
                  ((df["ClosedDate"].isna()) | (df["ClosedDate"] > boundary_utc))]
    open_exploratory    = open_all[open_all["Exploratory"]]
    open_nonexploratory = open_all[~open_all["Exploratory"] & ~open_all["TestCase"]]
    open_testcase       = open_all[open_all["TestCase"]]
    open_pega           = open_all[open_all["PEGA"]]

    burndown_all.append({"Date": d_plot, "OpenBugs": len(open_all)})
    burndown_exploratory.append({"Date": d_plot, "OpenBugs": len(open_exploratory)})
    burndown_nonexploratory.append({"Date": d_plot, "OpenBugs": len(open_nonexploratory)})
    burndown_testcase.append({"Date": d_plot, "OpenBugs": len(open_testcase)})
    burndown_pega.append({"Date": d_plot, "OpenBugs": len(open_pega)})

# 3) DataFrames for plotting (Date column is datetime.date -> daily ticks)
df_all  = pd.DataFrame(burndown_all)
df_ex   = pd.DataFrame(burndown_exploratory)
df_non  = pd.DataFrame(burndown_nonexploratory)
df_test = pd.DataFrame(burndown_testcase)
df_pega = pd.DataFrame(burndown_pega)

# ensure this column always exists
if "ClosedBugs" not in df_all.columns:
    df_all["ClosedBugs"] = 0
df_all["ClosedBugs"] = df_all["ClosedBugs"].fillna(0).astype(int)

# --- Derive deltas from the plotted series (guaranteed to match the chart) ---
# last date shown on x-axis
final_plot_date = df_all["Date"].iloc[-1]

# open bugs: last vs previous point
open_now  = int(df_all.loc[df_all["Date"] == final_plot_date, "OpenBugs"].iloc[0])
open_prev = int(df_all["OpenBugs"].iloc[-2]) if len(df_all) > 1 else open_now
delta_open = open_now - open_prev
# --- Derive deltas from the plotted series (guaranteed to match the chart) ---
# last date shown on x-axis
final_plot_date = df_all["Date"].iloc[-1]

# open bugs: last vs previous point
open_now = int(df_all.loc[df_all["Date"] == final_plot_date, "OpenBugs"].iloc[0])
open_prev = int(df_all["OpenBugs"].iloc[-2]) if len(df_all) > 1 else open_now
delta_open = open_now - open_prev

# closed bugs: last vs previous point
mask = df_all["Date"].eq(final_plot_date)
closed_now = int(df_all.loc[mask, "ClosedBugs"].iloc[0]) if mask.any() else 0
closed_prev = int(df_all["ClosedBugs"].iloc[-2]) if len(df_all) > 1 else closed_now
delta_closed = closed_now - closed_prev

print(f"\nTotal Open Bugs as of {final_plot_date}: {open_now} (Δ {delta_open})")
print(f"Total Closed Bugs as of {final_plot_date}: {closed_now} (Δ {delta_closed})")


# 4) Figure
plt.figure(figsize=(12, 7))
plt.plot(df_all["Date"],  df_all["OpenBugs"],  label="Total Open Bugs",           marker="o")
plt.plot(df_ex["Date"],   df_ex["OpenBugs"],   label="Exploratory Bugs",          marker="x")
plt.plot(df_test["Date"], df_test["OpenBugs"], label="Test Case Design Bugs",     marker="^")
plt.plot(df_non["Date"],  df_non["OpenBugs"],  label="System Bugs From Test Case",marker="s")
plt.plot(df_pega["Date"],  df_non["OpenBugs"],  label="PEGA Bugs",marker="+")

# Force daily ticks/labels (no hours)
ax = plt.gca()
ax.xaxis.set_major_locator(mdates.DayLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

# Title/subtitle in EST
formatted_date = end_local.strftime("%Y-%m-%d %I:%M %p %Z")
plt.title(f"Total Bug Chart as of {formatted_date}", fontsize=16, y=1.10)
plt.suptitle(f"Area Path: {area_path} | Iteration Path: {iteration_path}", fontsize=10, y=0.83)
plt.xlabel("Date"); plt.ylabel("Open Bugs")
plt.xticks(rotation=45); plt.grid(True); plt.legend()

# Footer timestamp in EST
timestamp = datetime.now(EST).strftime("Generated on %Y-%m-%d at %I:%M %p %Z")
plt.figtext(0.99, 0.01, timestamp, horizontalalignment='right', fontsize=8)

# ---- Totals/deltas as of final day (use UTC for filtering, EST for display) ----
final_local    = end_local
previous_local = (final_local - pd.Timedelta(days=1)).normalize()
final_boundary_utc    = (final_local + pd.Timedelta(days=1)).tz_convert("UTC")
previous_boundary_utc = (previous_local + pd.Timedelta(days=1)).tz_convert("UTC")

open_now  = df[(df["CreatedDate"] <  final_boundary_utc) &
               (df["ClosedDate"].isna() | (df["ClosedDate"] >= final_boundary_utc))]
open_prev = df[(df["CreatedDate"] <  previous_boundary_utc) &
               (df["ClosedDate"].isna() | (df["ClosedDate"] >= previous_boundary_utc))]

closed_now  = df[(df["ClosedDate"].notna()) & (df["ClosedDate"] < final_boundary_utc)]
closed_prev = df[(df["ClosedDate"].notna()) & (df["ClosedDate"] < previous_boundary_utc)]


delta_open_str   = f"{'+' if delta_open   >= 0 else ''}{delta_open}"
delta_closed_str = f"{'+' if delta_closed >= 0 else ''}{delta_closed}"

plt.figtext(0.02, 0.035, f"Total Closed Bugs as of {final_local.date()}: {len(closed_now)} (Δ {delta_closed_str})", fontsize=9, ha="left")
plt.figtext(0.02, 0.010, f"Total Open Bugs as of {final_local.date()}: {len(open_now)} (Δ {delta_open_str})",   fontsize=9, ha="left")

# 5) Endpoint annotations (match x-axis date type)
final_plot_date = final_local.date()
def annotate_end_value(df, label, offset_x=5, offset_y=0, color="black"):
    if not df.empty:
        plt.annotate(
            f"{df['OpenBugs'].iloc[-1]}{label}",
            (df["Date"].iloc[-1], df["OpenBugs"].iloc[-1]),
            xytext=(offset_x, offset_y),  # closer to the point
            textcoords="offset points",
            va="center",
            color=color
        )

annotate_end_value(df_all, "", offset_x=5, color="blue")
annotate_end_value(df_ex, "", offset_x=5, color="orange")
annotate_end_value(df_test, "", offset_x=5, color="green")
annotate_end_value(df_non, "", offset_x=5, color="red")
annotate_end_value(df_pega, "", offset_x=5, color="purple")

plt.tight_layout(rect=[0, 0.03, 1, 0.95])
output_file = "total_bug_burndown.png"
plt.savefig("charts/" + output_file)
print(f"\n Burndown chart saved as: {output_file}")