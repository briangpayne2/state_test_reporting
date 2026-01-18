import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()  # Loads from .env by default

ADO_ORG = os.getenv("ADO_ORG")
ADO_PROJECT = os.getenv("ADO_PROJECT")

#URLs
def base_url(): return f"https://dev.azure.com/{ADO_ORG}/_apis/projects?api-version=6.0"
def wiql_url(): return f"https://dev.azure.com/{ADO_ORG}/{ADO_PROJECT}/_apis/wit/wiql?api-version=6.0"