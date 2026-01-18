import os
import requests
from dotenv import load_dotenv

load_dotenv()
pat = os.getenv("ADO_PAT")
org = os.getenv("ADO_ORG", "flwins")
api_version = "6.0"

url = f"https://dev.azure.com/{org}/_apis/projects?api-version={api_version}"

response = requests.get(url, auth=("", pat), allow_redirects=False)

print(f"Status Code: {response.status_code}")
print(f"Redirect Location: {response.headers.get('Location')}")
print(f"Response Text: {response.text[:500]}")