import os
import requests
from dotenv import load_dotenv
import url_config

load_dotenv()

ADO_PAT = os.getenv("ADO_PAT")
ORG = os.getenv("ORG")  # should be just "flwins"
PROJECT = os.getenv("PROJECT")  # should be "FL WINS"

headers = {
    "Content-Type": "application/json"
}

def work_item_ids(payload: dict, personal_access_token: str) -> list:
    response = requests.post(
        url=url_config.wiql_url(),
        auth=("", personal_access_token),  # Correct PAT usage
        headers={"Content-Type": "application/json"},
        json=payload
    )

    print(f"Status Code: {response.status_code}")
    print(f"Response Text: {response.text[:500]}")  # Optional: for debugging

    try:
        data = response.json()
        return [item["id"] for item in data.get("workItems", [])]
    except Exception as e:
        print("Failed to parse JSON response.")
        raise e