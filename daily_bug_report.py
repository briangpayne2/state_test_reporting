import os
import numpy as np
import requests
import base64
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
from dotenv import dotenv_values
from zoneinfo import ZoneInfo
import textwrap 
import sys

# Load environment variables
config = dotenv_values(".env")

organization = config.get("ADO_ORG")
project = config.get("ADO_PROJECT")
pat = config.get("ADO_PAT")
area_path = config.get("AREA_PATH")
iteration_path = config.get("ITERATION_PATH")
start_date = datetime.fromisoformat(config.get("START_DATE"))
end_date = datetime.fromisoformat(config.get("END_DATE"))

# WIQL query
wiql_query = {
    "query": f"""
    SELECT
        [System.Id],
        [System.WorkItemType],
        [System.Title],
        [System.AssignedTo],
        [System.State],
        [System.Tags],
        [Microsoft.VSTS.Common.Severity],
        [Microsoft.VSTS.Common.ClosedDate],
        [System.CreatedDate]
    FROM workitems
    WHERE
        [System.TeamProject] = '{project}'
        AND (
            [System.WorkItemType] = 'Bug'
            AND [System.AreaPath] = '{area_path}'
            AND [System.IterationPath] = '{iteration_path}'
            AND (
                [System.CreatedDate] >= '{start_date.isoformat()}'
                AND [System.CreatedDate] <= '{end_date.isoformat()}'
            )
        )
    """
}

# Encode PAT for Azure DevOps auth
auth = base64.b64encode(f":{pat}".encode()).decode()
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {auth}"
}

# Query ADO
wiql_url = f"https://dev.azure.com/{organization}/{project}/_apis/wit/wiql?api-version=6.0"
response = requests.post(wiql_url, headers=headers, json=wiql_query)
print("URL ->", repr(wiql_url))
print("WIQL->", wiql_query["query"])
print("RESP->", response.status_code, response.text[:500])
response.raise_for_status()
work_item_ids = [item["id"] for item in response.json().get("workItems", [])]


# Build a DataFrame from the work item IDs
if work_item_ids:
    # Build URL for batch request
    ids_str = ",".join(map(str, work_item_ids))
    items_url = f"https://dev.azure.com/{organization}/{project}/_apis/wit/workitemsbatch?api-version=6.0"

    # Define the fields you want to retrieve (matching your WIQL SELECT)
    payload = {
        "ids": work_item_ids,
        "fields": [
            "System.Id",
            "System.WorkItemType",
            "System.Title",
            "System.AssignedTo",
            "System.State",
            "System.Tags",
            "Microsoft.VSTS.Common.Severity",   # Added severity
            "Microsoft.VSTS.Common.ClosedDate",
            "System.CreatedDate"
        ]
    }

    resp = requests.post(items_url, headers=headers, json=payload)
    resp.raise_for_status()

    work_items = resp.json().get("value", [])

    # Convert to DataFrame
    df = pd.DataFrame([
        {field: item["fields"].get(field) for field in payload["fields"]}
        for item in work_items
    ])

    print(df)
else:
    print("No work items found.")


# --- Status summary charts (donut + bar) ---
import matplotlib.pyplot as plt
from datetime import datetime
try:
    from zoneinfo import ZoneInfo   # Py3.9+
    tz = ZoneInfo("America/New_York")
except Exception:
    tz = None

# Guard: empty DF
if df.empty:
    print("No data to chart.")
else:
    # Count by state
    state_col = "System.State"
    counts = (
        df[state_col]
        .dropna()
        .astype(str)
        .value_counts()
    )

    total = int(counts.sum())
    pct = (counts / total * 100.0).round(1)

    # Optional: put common states first if present
    preferred_order = ["Closed", "Resolved", "Active", "New", "Deferred", "Duplicate", "Rejected"]
    ordered_index = [s for s in preferred_order if s in counts.index] + \
                    [s for s in counts.index if s not in preferred_order]
    counts = counts.reindex(ordered_index)
    pct = pct.reindex(ordered_index)

    # Timestamp (EST)
    now = datetime.now(tz) if tz else datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Figure
    fig = plt.figure(figsize=(12, 6.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 1.3])
    ax1 = fig.add_subplot(gs[0, 0])  # donut
    ax2 = fig.add_subplot(gs[0, 1])  # bar

    #Create a fixed color mapping based on status order
    color_map = plt.get_cmap('tab20')  # or 'tab10', 'Set2', etc.
    status_colors = {status: color_map(i / len(counts)) for i, status in enumerate(counts.index)}

    # Get color list in correct order
    colors = [status_colors[status] for status in counts.index]

    # --- Donut chart ---
    wedges, texts, autotexts = ax1.pie(
        counts.values,
        labels=None,  # we'll add labels manually
        autopct=lambda v: f"{v:.1f}%",
        startangle=90,
        wedgeprops=dict(width=0.35, edgecolor="white"),
        colors=colors  # <<<<<< SAME COLORS HERE
    )

    # Center total
    ax1.text(0, 0, f"{total}", ha="center", va="center", fontsize=22, weight="bold")
    ax1.set_title("Bug Distribution by Status", pad=16, fontsize=12)

    # Radial labels (status names) near wedges
    for w, name in zip(wedges, counts.index):
        ang = (w.theta2 + w.theta1) / 2.0
        x = 1.1 * np.cos(np.deg2rad(ang))
        y = 1.1 * np.sin(np.deg2rad(ang))
        ax1.text(x, y, name, ha="center", va="center", fontsize=9)

    # --- Bar chart ---
    bars = ax2.bar(counts.index, counts.values, color=colors) 
    ax2.set_title("Status Count Bar Chart", pad=10, fontsize=12)
    ax2.set_ylabel("Number of Bugs")
    ax2.set_xlabel("Status")
    ax2.set_ylim(0, max(counts.values) * 1.20 if total else 1)

    # Annotate each bar with "N (PCT%)"
    for rect, n, p in zip(bars, counts.values, pct.values):
        ax2.text(
            rect.get_x() + rect.get_width()/2.0,
            rect.get_height() + (max(counts.values)*0.03 if total else 0.5),
            f"{int(n)} ({p:.1f}%)",
            ha="center", va="bottom", fontsize=10, weight="bold"
        )
    # Slant x labels a bit
    for tick in ax2.get_xticklabels():
        tick.set_rotation(30)
        tick.set_ha("right")

    # --- Titles / subtitle / footer ---
    fig.suptitle(f"Daily Status Snapshot as of {today_str}", fontsize=16, y=0.98)
    # Show your Area/Iteration under the title (they already exist above in your script)
    subtitle = f"Area Path: {area_path}   |   Iteration Path: {iteration_path}"
    fig.text(0.5, 0.93, subtitle, ha="center", fontsize=10)

    footer = now.strftime("Generated %Y-%m-%d at %I:%M %p %Z") if tz else \
             now.strftime("Generated %Y-%m-%d at %I:%M %p")
    fig.text(0.99, 0.02, footer, ha="right", fontsize=9)

    plt.tight_layout(rect=[0, 0.03, 1, 0.92])

    # Save
    out_path = "charts/status_summary.jpg"
    plt.savefig(out_path, dpi=180)
    plt.close(fig)
    print(f"Saved chart -> {out_path}")


# --- Severity summary charts (donut + bar) ---
import matplotlib.pyplot as plt
import numpy as np
import re
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
except Exception:
    tz = None

sev_col = "Microsoft.VSTS.Common.Severity"

if df.empty or sev_col not in df.columns:
    print("No data/column to chart for severity.")
else:
    # Normalize + count
    sev_series = df[sev_col].fillna("Unspecified").astype(str)

    # Sort by the leading number if present (e.g., "2 - Low", "3 - Moderate"...)
    def sev_sort_key(label: str) -> int:
        m = re.match(r"\s*(\d+)", label)
        return int(m.group(1)) if m else 999

    counts = (
        sev_series.value_counts()
        .sort_index(key=lambda idx: [sev_sort_key(s) for s in idx])
    )
    total = int(counts.sum())
    pct = (counts / total * 100.0).round(1)

    # Shared color scheme for both charts
    cmap = plt.get_cmap("tab20")
    color_map = {name: cmap(i / max(1, len(counts))) for i, name in enumerate(counts.index)}
    colors = [color_map[name] for name in counts.index]

    # Timestamp + titles
    now = datetime.now(tz) if tz else datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    fig = plt.figure(figsize=(12, 6.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 1.3])
    ax1 = fig.add_subplot(gs[0, 0])  # donut
    ax2 = fig.add_subplot(gs[0, 1])  # bar

    # --- Donut chart ---
    wedges, _, _ = ax1.pie(
        counts.values,
        labels=None,
        autopct=lambda v: f"{v:.1f}%",
        startangle=90,
        wedgeprops=dict(width=0.35, edgecolor="white"),
        colors=colors,
    )
    # Center total
    ax1.text(0, 0, f"{total}", ha="center", va="center", fontsize=22, weight="bold")
    ax1.set_title("Bug Distribution by Severity", pad=16, fontsize=12)

    # Status labels around ring
    for w, name in zip(wedges, counts.index):
        ang = (w.theta2 + w.theta1) / 2.0
        x = 1.1 * np.cos(np.deg2rad(ang))
        y = 1.1 * np.sin(np.deg2rad(ang))
        ax1.text(x, y, name, ha="center", va="center", fontsize=9)

    # --- Bar chart ---
    bars = ax2.bar(counts.index, counts.values, color=colors)
    ax2.set_title("Severity Count Bar Chart", pad=10, fontsize=12)
    ax2.set_ylabel("Number of Bugs")
    ax2.set_xlabel("Severity Level")
    ax2.set_ylim(0, max(counts.values) * 1.20 if total else 1)

    for rect, n, p in zip(bars, counts.values, pct.values):
        ax2.text(
            rect.get_x() + rect.get_width() / 2.0,
            rect.get_height() + (max(counts.values) * 0.03 if total else 0.5),
            f"{int(n)} ({p:.1f}%)",
            ha="center",
            va="bottom",
            fontsize=10,
            weight="bold",
        )

    for tick in ax2.get_xticklabels():
        tick.set_rotation(30)
        tick.set_ha("right")

    # Page title / subtitle / footer
    fig.suptitle(f"Daily Severity Snapshot as of {today_str}", fontsize=16, y=0.98)
    fig.text(0.5, 0.93, f"Area Path: {area_path}   |   Iteration Path: {iteration_path}",
             ha="center", fontsize=10)
    footer = now.strftime("Generated %Y-%m-%d at %I:%M %p %Z") if tz else \
             now.strftime("Generated %Y-%m-%d at %I:%M %p")
    fig.text(0.99, 0.02, footer, ha="right", fontsize=9)

    plt.tight_layout(rect=[0, 0.03, 1, 0.92])
    out_path = "charts/severity_summary.jpg"
    plt.savefig(out_path, dpi=180)
    plt.close(fig)
    print(f"Saved chart -> {out_path}")

# --- Severity 4 & 5 bug table (fixed size, wrapped, locked row heights) ---
import matplotlib.pyplot as plt
import pandas as pd
import re, textwrap
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
except Exception:
    tz = None

sev_field = "Microsoft.VSTS.Common.Severity"
cols_needed = ["System.Id", sev_field, "System.Title", "System.State"]

# Match your reference image size exactly
WIDTH_PX, HEIGHT_PX, DPI = 1058, 645, 100
FIG_W_IN, FIG_H_IN = WIDTH_PX / DPI, HEIGHT_PX / DPI

def _sev_num(val):
    if pd.isna(val): return None
    m = re.match(r"\s*(\d+)", str(val))
    return int(m.group(1)) if m else None

def wrap_cell(s, width=44, max_lines=2):
    lines = textwrap.wrap(str(s or ""), width=width, break_long_words=False)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if not lines[-1].endswith("…"):
            lines[-1] += "…"
    return "\n".join(lines)

if df.empty or not set(cols_needed).issubset(df.columns):
    print("No data/columns to build Severity 4 & 5 table.")
else:
    tdf = df[cols_needed].copy()
    tdf["SeverityNum"] = tdf[sev_field].map(_sev_num)
    tdf = tdf[tdf["SeverityNum"].isin([4, 5])]

    if tdf.empty:
        print("No Severity 4 or 5 bugs.")
    else:
        # Labels and formatting
        sev_label = {4: "4 - High", 5: "5 - Critical"}
        tdf["SeverityDisplay"] = tdf["SeverityNum"].map(sev_label)
        tdf["System.Id"] = tdf["System.Id"].astype(int)
        tdf["TitleWrapped"] = tdf["System.Title"].apply(lambda s: wrap_cell(s, 44, 2))
        tdf = tdf.sort_values(["SeverityNum", "System.Id"], ascending=[False, True])

        rows = tdf.apply(
            lambda r: [r["System.Id"], r["SeverityDisplay"], r["TitleWrapped"], r["System.State"]],
            axis=1
        ).tolist()
        col_labels = ["Id", "Severity", "Title", "State"]

        # Figure (fixed pixels)
        fig = plt.figure(figsize=(FIG_W_IN, FIG_H_IN), dpi=DPI)
        ax = fig.add_subplot(111)
        ax.axis("off")

        # Titles
        now = datetime.now(tz) if tz else datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        fig.suptitle(f"Severity 4 & 5 Bug Status as of {today_str}", fontsize=14, y=0.95)
        fig.text(0.5, 0.90, f"Area Path: {area_path}   |   Iteration Path: {iteration_path}",
                 ha="center", fontsize=10)

        # Fixed table bbox (percent of figure): tuned to match your sample proportions
        tbl_bbox = [0.08, 0.15, 0.84, 0.68]  # [x, y, w, h]
        # Fixed column widths (must sum ≈ 1.0)
        col_widths = [0.12, 0.16, 0.52, 0.20]

        # Base font size: slightly smaller when many rows
        nrows = len(rows)
        fs = 9 if nrows > 18 else 10

        tbl = ax.table(
            cellText=rows,
            colLabels=col_labels,
            colWidths=col_widths,
            colLoc="center",
            cellLoc="left",
            loc="center",
            edges="closed",
            bbox=tbl_bbox,
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(fs)
        tbl.scale(1.0, 1.02)  # minimal scaling so cells don't balloon

        # ---- lock row heights AFTER first draw ----
        fig.canvas.draw()

        header_h = 0.06 * tbl_bbox[3]                      # 6% of table height
        data_h = (tbl_bbox[3] - header_h) / max(nrows, 1)  # equal data row heights

        # Style header + set heights and alignment
        ncols = len(col_labels)
        for c in range(ncols):
            cell = tbl[(0, c)]
            cell.set_text_props(weight="bold", ha="center")
            cell.set_height(header_h)

        for r in range(1, nrows + 1):
            for c in range(ncols):
                cell = tbl[(r, c)]
                cell.set_height(data_h)
                # center narrow columns; Title stays left
                if c in (0, 1, 3):
                    cell._loc = 'center'
                else:
                    cell._loc = 'left'

        # Zebra stripes for readability
        for r in range(1, nrows + 1):
            if r % 2 == 0:
                for c in range(ncols):
                    tbl[(r, c)].set_facecolor("#f7f7f7")

        # Footer
        footer = now.strftime("Generated %Y-%m-%d at %I:%M %p %Z") if tz else \
                 now.strftime("Generated %Y-%m-%d at %I:%M %p")
        fig.text(0.99, 0.03, footer, ha="right", fontsize=8)

        out_path = "charts/severity_4_5_bug_table.jpg"
        # Keep exact pixel size — no tight/bbox
        plt.savefig(out_path, dpi=DPI)
        plt.close(fig)
        print(f"Saved table -> {out_path} ({WIDTH_PX}x{HEIGHT_PX}px, rows={nrows})")

# # === Generate formatted Severity 4 & 5 bug table as a separate JPG ===

# # Get work item details in batches
# def fetch_work_items(ids):
#     url = f"https://dev.azure.com/{organization}/_apis/wit/workitemsbatch?api-version=6.0"
#     body = {
#         "ids": ids,
#         "fields": [
#             "System.Id", "System.WorkItemType", "System.Title", "System.AssignedTo",
#             "System.State", "System.Tags", "Microsoft.VSTS.Common.ClosedDate",
#             "System.CreatedDate", "Microsoft.VSTS.Common.Severity"
#         ]
#     }
#     r = requests.post(url, headers=headers, json=body)
#     r.raise_for_status()
#     return r.json().get("value", [])

# # Retrieve and parse items
# items = []
# for i in range(0, len(work_item_ids), 200):
#     batch = work_item_ids[i:i+200]
#     items += fetch_work_items(batch)

# data = []
# for item in items:
#     f = item["fields"]
#     data.append({
#         "Id": f.get("System.Id"),
#         "Title": f.get("System.Title"),
#         "AssignedTo": f.get("System.AssignedTo", {}).get("displayName") if isinstance(f.get("System.AssignedTo"), dict) else None,
#         "State": f.get("System.State"),
#         "Tags": f.get("System.Tags"),
#         "CreatedDate": f.get("System.CreatedDate"),
#         "ClosedDate": f.get("Microsoft.VSTS.Common.ClosedDate"),
#         "Severity": f.get("Microsoft.VSTS.Common.Severity", "Unspecified")
#     })

# # --- 1) Pull IDs from WIQL result ---
# work_items = data.get("workItems", data) if isinstance(data, dict) else data
# ids = [w["id"] for w in work_items if "id" in w]

# if not ids:
#     print("No bugs matched the filters; nothing to report.")
#     sys.exit(0)

# # --- 2) Fetch fields for those IDs via workitemsbatch ---
# detail_url = f"https://dev.azure.com/{organization}/_apis/wit/workitemsbatch?api-version=7.0"
# detail_body = {
#     "ids": ids,
#     "fields": [
#         "System.Id",
#         "System.WorkItemType",
#         "System.Title",
#         "System.AssignedTo",
#         "System.State",
#         "System.Tags",
#         "System.CreatedDate",
#         "Microsoft.VSTS.Common.ClosedDate",
#     ],
# }
# detail_resp = requests.post(detail_url, headers=headers, json=detail_body, auth=auth)
# detail_resp.raise_for_status()
# items = detail_resp.json().get("value", [])

# # --- 3) Flatten to rows ---
# rows = []
# for it in items:
#     f = it.get("fields", {})
#     assigned = f.get("System.AssignedTo")
#     if isinstance(assigned, dict):
#         assigned = assigned.get("displayName") or assigned.get("uniqueName")

#     rows.append({
#         "Id": f.get("System.Id"),
#         "WorkItemType": f.get("System.WorkItemType"),
#         "Title": f.get("System.Title"),
#         "AssignedTo": assigned,
#         "State": f.get("System.State"),
#         "Tags": f.get("System.Tags"),
#         "CreatedDate": f.get("System.CreatedDate"),
#         "ClosedDate": f.get("Microsoft.VSTS.Common.ClosedDate"),
#     })

# df = pd.DataFrame(rows)

# # Guard in case batch returns nothing (shouldn’t, but be safe)
# if df.empty:
#     print("Got IDs but no fields back; report would be empty.")
#     sys.exit(0)

# # Parse dates (columns now exist)
# df["CreatedDate"] = pd.to_datetime(df["CreatedDate"], errors="coerce", utc=True)
# df["ClosedDate"]  = pd.to_datetime(df["ClosedDate"],  errors="coerce", utc=True)

# total_bugs = len(df)

# # Filter for bugs active as of end_date
# # Patch logic for snapshot bug inclusion
# import pytz
# as_of_date = pd.to_datetime(end_date)
# if as_of_date.tzinfo is None:
#     as_of_date = as_of_date.tz_localize(pytz.UTC)

# # Include all bugs created on or before the snapshot date
# snapshot_bugs = df[df["CreatedDate"] <= as_of_date]
# active_bugs = snapshot_bugs[
#     (snapshot_bugs["ClosedDate"].isna()) | (snapshot_bugs["ClosedDate"] > as_of_date)
# ]

# # Normalize severity column (force lowercase, strip whitespace)
# snapshot_bugs.loc[:, "SeverityClean"] = snapshot_bugs["Severity"].astype(str).str.lower().str.strip()

# # Count bugs by state and severity for pie charts
# state_counts = snapshot_bugs["State"].value_counts()
# # Extract numeric severity level before counting
# df['Severity'] = df['Severity'].astype(str).str.extract(r'(\d)').astype(int)
# severity_counts = df['Severity'].value_counts().sort_index()

# print(f"Total bugs in snapshot: {total_bugs}")
# # Create chart folder if missing
# os.makedirs("charts", exist_ok=True)
# #################### Severity Summary Chart ####################

# # === SEVERITY SUMMARY CHART ===

# # Count bugs by severity
# severity_counts = snapshot_bugs["Severity"].value_counts().sort_index()
# severity_labels = [
#     f"{k} - {'None' if k == 1 else 'Low' if k == 2 else 'Moderate' if k == 3 else 'High' if k == 4 else ''}"
#     for k in severity_counts.index
# ]
# severity_values = severity_counts.values.tolist()
# total_severity = sum(severity_values)

# # Color mapping for severity levels based on Table 8
# severity_colors = {
#     5: "#d62728",  # Critical - Red
#     4: "#ff7f0e",  # High - Orange
#     3: "#ffdd57",  # Moderate - Yellow
#     2: "#2ca02c",  # Low - Green
#     1: "#d3d3d3",  # None - Gray
# }

# # Fix color mapping (convert label index to integer)
# bar_colors = [severity_colors.get(int(str(s).split()[0]), "#cccccc") for s in severity_counts.index]

# # Create and size figure
# fig, axes = plt.subplots(1, 2, figsize=(14, 7))
# axes[0].set_position([0.06, 0.2, 0.4, 0.6])
# axes[1].set_position([0.55, 0.2, 0.4, 0.6])

# # Donut chart
# wedges, texts, autotexts = axes[0].pie(
#     severity_values,
#     labels=severity_labels,
#     autopct='%1.1f%%',
#     startangle=90,
#     wedgeprops=dict(width=0.4),
#     colors=bar_colors
# )
# centre_circle = plt.Circle((0, 0), 0.7, fc='white')
# axes[0].add_artist(centre_circle)
# axes[0].text(0, 0, str(total_severity), fontsize=14, fontweight='bold', ha='center', va='center')
# axes[0].set_title("Bug Distribution by Severity")

# # Bar chart
# axes[1].bar(severity_labels, severity_values, color=bar_colors, edgecolor='black')
# axes[1].set_title("Severity Count Bar Chart")
# axes[1].set_xlabel("Severity Level")
# axes[1].set_ylabel("Number of Bugs")
# axes[1].set_xticks(range(len(severity_labels)))
# axes[1].set_xticklabels(severity_labels, rotation=45, ha='right')

# # Count + % above each bar
# for i, (label, count) in enumerate(zip(severity_labels, severity_values)):
#     pct = (count / total_severity) * 100 if total_severity else 0
#     axes[1].text(i, count + 2, f"{count} ({pct:.1f}%)", ha='center', va='bottom', fontsize=9, fontweight='bold')

# # Title, subtitle, timestamp
# fig.suptitle(f"Daily Severity Snapshot as of {end_date.strftime('%Y-%m-%d')}", fontsize=14, x=0.6)
# fig.text(0.6, 0.92, f"Area Path: {area_path}   |   Iteration Path: {iteration_path}", fontsize=10, ha='center')

# from zoneinfo import ZoneInfo
# timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d at %I:%M %p %Z")
# fig.text(0.99, 0.01, f"Generated {timestamp}", fontsize=9, ha='right')

# # Save to file
# plt.savefig("charts/severity_summary.jpg", bbox_inches="tight", dpi=100)
# plt.close()
# print("Severity summary chart saved to charts/severity_summary.jpg")

# ############## BUG SUMMARY CHART ###
# # === STATUS SUMMARY CHART (Perfectly aligned with severity chart) ===

# # Count bugs by state
# status_counts = snapshot_bugs["State"].value_counts().sort_index()
# status_labels = status_counts.index.tolist()
# status_values = status_counts.values.tolist()
# total_status = sum(status_values)

# # Color mapping for consistent palette
# status_colors = {
#     "Closed": "#1f77b4",
#     "Deferred": "#ff7f0e",
#     "Duplicate": "#9467bd",
#     "Rejected": "#d62728",
#     "Active": "#2ca02c",
#     "New": "#e377c2"
# }
# bar_colors = [status_colors.get(s, "#cccccc") for s in status_labels]

# # Set up figure and matching layout
# fig, axes = plt.subplots(1, 2, figsize=(14, 7))  # Slightly larger
# fig.set_dpi(100)  # Optional but keeps dimensions consistent

# # Position the subplots to exactly match severity layout
# axes[0].set_position([0.06, 0.2, 0.4, 0.6])
# axes[1].set_position([0.55, 0.2, 0.4, 0.6])

# # Donut chart
# wedges, texts, autotexts = axes[0].pie(
#     status_values,
#     labels=status_labels,
#     autopct='%1.1f%%',
#     startangle=90,
#     wedgeprops=dict(width=0.4),
#     colors=bar_colors
# )
# centre_circle = plt.Circle((0, 0), 0.7, fc='white')
# axes[0].add_artist(centre_circle)
# axes[0].text(0, 0, str(total_status), fontsize=14, fontweight='bold', ha='center', va='center')
# axes[0].set_title("Bug Distribution by Status")

# # Bar chart
# axes[1].bar(status_labels, status_values, color=bar_colors, edgecolor='black')
# axes[1].set_title("Status Count Bar Chart")
# axes[1].set_xlabel("Status")
# axes[1].set_ylabel("Number of Bugs")
# axes[1].set_xticks(range(len(status_labels)))
# axes[1].set_xticklabels(status_labels, rotation=45, ha='right')

# # Annotate counts and % above each bar
# for i, (label, count) in enumerate(zip(status_labels, status_values)):
#     pct = (count / total_status) * 100 if total_status else 0
#     axes[1].text(i, count + 2, f"{count} ({pct:.1f}%)", ha='center', va='bottom', fontsize=9, fontweight='bold')

# # Shared title, subtitle, timestamp
# # Title – shift right using x=0.6 or higher
# fig.suptitle(
#     f"Daily Status Snapshot as of {end_date.strftime('%Y-%m-%d')}",
#     fontsize=14,
#     x=0.6  # Adjust this value to shift right (default is 0.5)
# )

# # Subtitle – shift right using x=0.6
# fig.text(
#     0.6, 0.92,  # x = horizontal position
#     f"Area Path: {area_path}   |   Iteration Path: {iteration_path}",
#     fontsize=10,
#     ha='center'
# )

# from zoneinfo import ZoneInfo
# timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d at %I:%M %p %Z")
# fig.text(0.99, 0.01, f"Generated {timestamp}", fontsize=9, ha='right')

# # Save
# plt.savefig("charts/status_summary.jpg", bbox_inches="tight", dpi=100)
# plt.close()
# print(" Status summary chart saved to charts/status_summary.jpg")

# #####################################################
# # === Generate formatted Severity 4 & 5 bug table as a separate JPG ===
# import matplotlib.pyplot as plt
# import matplotlib.table as tbl

# # Clean and extract numeric severity for filtering
# df["SeverityNum"] = df["Severity"].astype(str).str.extract(r"(\d)").astype(int)

# # Filter for severity 4 and 5 bugs
# severe_bugs = df[df["SeverityNum"].isin([4, 5])][["Id", "Severity", "Title", "State"]].sort_values(by="Id")
# severe_bugs["Id"] = severe_bugs["Id"].astype(int).astype(str)
# # Create the figure
# fig, ax = plt.subplots(figsize=(12, 6))

# # Add title and subtitles
# fig.text(0.6, 1.05, 'Severity 4 & 5 Bug Status as of ' + end_date.strftime('%Y-%m-%d'), fontsize=14, ha='center', va='top', weight='bold')
# fig.text(0.6, 0.97, f'Area Path: {area_path}   |   Iteration Path: {iteration_path}', fontsize=10, ha='center')

# # Add timestamp at bottom-right
# from zoneinfo import ZoneInfo  # Python 3.9+

# timestamp = datetime.now(ZoneInfo("America/New_York")).strftime('%Y-%m-%d at %I:%M %p %Z')
# fig.text(0.99, 0.01, f'Generated {timestamp}', fontsize=8, ha='right')

# ax.axis("off")

# # Limit all cell text to 100 characters
# for col in severe_bugs.select_dtypes(include='object'):
#     severe_bugs[col] = severe_bugs[col].str.slice(0, 70)

# # Draw table
# # table = ax.table(
# #     cellText=severe_bugs.values,
# #     colLabels=severe_bugs.columns,
# #     cellLoc='left',
# #     loc='center',
# #     bbox=[0.06, 0.15, 1.0, 0.8],  # (left, bottom, width, height) tweak this
# #     edges='horizontal'
# # )
# if not severe_bugs.empty:
#     table = ax.table(
#         cellText=severe_bugs.values.tolist(),
#         colLabels=severe_bugs.columns,
#         loc="center",
#         cellLoc='left',
#         bbox=[0.15, 0.1, 0.85, 0.8]  # (left, bottom, width, height)
#     )
#     table.auto_set_font_size(False)
#     table.set_fontsize(8)
#     table.scale(1, 1.5)
#     ax.axis('off')  # hide axes around the table
#     # Set column widths for ID, Severity, Title, State
#     col_widths = [0.07, 0.12, 0.65, 0.13]
#     for i, width in enumerate(col_widths):
#         for key, cell in table.get_celld().items():
#             if key[1] == i:
#                 cell.set_width(width)
#     # Save as image
#     plt.savefig("charts/severity_4_5_bug_table.jpg", format='jpg', bbox_inches="tight")
#     plt.close()
#     print("Saved clean table to charts/severity_4_5_bug_table_final.jpg")
# else:
#     print("No severe bugs found — skipping table rendering.")
#     ax.text(0.5, 0.5, "No severe bugs to display", ha='center', va='center', fontsize=10)
#     ax.axis('off')

