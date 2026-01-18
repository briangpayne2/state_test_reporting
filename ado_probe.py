
#!/usr/bin/env python3
import os, base64, requests
from urllib.parse import quote
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)

ORG = os.environ["ADO_ORG"]
PROJECT = os.environ["ADO_PROJECT"]
PAT = os.environ["ADO_PAT"]
PROJECT_ID = os.environ.get("PROJECT_ID","")  # optional if you know it
BASE = f"https://dev.azure.com/{ORG}".rstrip("/")
ENC = quote(PROJECT, safe="")

def h_basic_header():
    tok = base64.b64encode(f":{PAT}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "Accept":"application/json"}

def style_requests_auth():
    return requests.auth.HTTPBasicAuth("", PAT)

def ping(desc, url, params=None, headers=None, auth=None):
    print(f"\n=== {desc} ===")
    r = requests.get(url, params=params, headers=headers, auth=auth)
    print("GET", r.url)
    print("→", r.status_code)
    print(r.text[:200], "..." if len(r.text)>200 else "")
    return r.status_code

# 0: projects (control)
ping("projects control", f"{BASE}/_apis/projects", {"api-version":"7.1-preview.4"}, headers=h_basic_header())

# 1: testplan list via path + header
ping("testplan list (path+header)", f"{BASE}/{ENC}/_apis/testplan/plans", {"api-version":"6.0-preview.1"}, headers=h_basic_header())

# 2: testplan list via path + requests.auth
ping("testplan list (path+requests.auth)", f"{BASE}/{ENC}/_apis/testplan/plans", {"api-version":"6.0-preview.1"}, auth=style_requests_auth())

# 3: testplan via query project id + header (7.1)
if PROJECT_ID:
    ping("testplan list (query+header, 7.1)", f"{BASE}/_apis/testplan/plans", {"project":PROJECT_ID,"api-version":"7.1-preview.1"}, headers=h_basic_header())

# 4: legacy test plans list
ping("legacy test plans (path+header)", f"{BASE}/{ENC}/_apis/test/plans", {"api-version":"7.1-preview.1"}, headers=h_basic_header())
