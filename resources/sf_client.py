"""
Salesforce REST API client for the voice_agent_bridge subprocess. Uses a
plain access token + instance URL (SF_ACCESS_TOKEN / SF_INSTANCE_URL env
vars) via `requests`, not the `sf` CLI -- the bridge runs as a subprocess
that may eventually execute on a CRT Live Testing VM with no Salesforce
CLI installed (the VM only has what's in requirements.txt + bundled
resources, see crt_voice_poc_vm_gotchas memory). Locally,
local_agentic_diagnostic.py mints these by shelling out to
`sf org display --json` once at launch; the CRT-side equivalent (a vault
credential, refreshed per run) is deferred to the CRT-automation phase.
"""
import os

import requests

API_VERSION = "v61.0"


def _base():
    instance_url = os.environ["SF_INSTANCE_URL"].rstrip("/")
    token = os.environ["SF_ACCESS_TOKEN"]
    return instance_url, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def find_contact_by_phone(phone):
    """Matches on the last 10 digits so formatting differences (spaces,
    dashes, +1 prefix) between Twilio's E.164 caller ID and however the
    Contact's Phone field is formatted in Salesforce don't cause a miss.
    Returns the first matching {Id, Name, Phone} dict, or None."""
    instance_url, headers = _base()
    digits = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if not digits:
        return None
    query = f"SELECT Id, Name, Phone FROM Contact WHERE Phone LIKE '%{digits}%' LIMIT 1"
    resp = requests.get(
        f"{instance_url}/services/data/{API_VERSION}/query",
        params={"q": query}, headers=headers, timeout=20,
    )
    resp.raise_for_status()
    records = resp.json().get("records", [])
    return records[0] if records else None


def create_case(subject, description, contact_id=None, status="New", origin="Phone"):
    instance_url, headers = _base()
    body = {"Subject": subject, "Description": description, "Status": status, "Origin": origin}
    if contact_id:
        body["ContactId"] = contact_id
    resp = requests.post(
        f"{instance_url}/services/data/{API_VERSION}/sobjects/Case",
        json=body, headers=headers, timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def update_case(case_id, status=None, description=None):
    body = {}
    if status:
        body["Status"] = status
    if description is not None:
        body["Description"] = description
    if not body:
        return
    instance_url, headers = _base()
    resp = requests.patch(
        f"{instance_url}/services/data/{API_VERSION}/sobjects/Case/{case_id}",
        json=body, headers=headers, timeout=20,
    )
    resp.raise_for_status()


def get_case(case_id):
    instance_url, headers = _base()
    resp = requests.get(
        f"{instance_url}/services/data/{API_VERSION}/sobjects/Case/{case_id}",
        headers=headers, timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def find_latest_case():
    """Used for pre/post-call validation (see validate_agentic_call.py) --
    capture this before a call as a baseline, then again after, and
    confirm the Id changed rather than trusting call timing/transcript
    content alone. Returns {Id, CaseNumber, Status, Description,
    CreatedDate} for the most recently created Case, or None if the org
    has no Case records at all."""
    instance_url, headers = _base()
    query = "SELECT Id, CaseNumber, Status, Description, CreatedDate FROM Case ORDER BY CreatedDate DESC LIMIT 1"
    resp = requests.get(
        f"{instance_url}/services/data/{API_VERSION}/query",
        params={"q": query}, headers=headers, timeout=20,
    )
    resp.raise_for_status()
    records = resp.json().get("records", [])
    return records[0] if records else None
