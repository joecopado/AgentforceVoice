"""
Thin client for CRT's PACE platform REST API (read/write a test job's
files) -- see reference_pace_api memory. Auth: X-Authorization header,
the raw token (no "Bearer" prefix) from PACE_API_KEY env var, falling
back to ~/.config/copado_pace/api_key's contents if unset.

IMPORTANT: the upload endpoint's "replace" operation is a FULL FILE
OVERWRITE, not a scoped/line-level patch -- confirmed live 2026-08-17 the
hard way (a schema-discovery probe sent a placeholder value against a
real job and overwrote its real test file; see
feedback_destructive_api_probing memory). Callers of upload_file() must
always pass the COMPLETE intended file content, never a partial diff.
"""
import os

import requests

BASE_URL = "https://api.robotic.copado.com/pace/v4"


def _api_key():
    key = os.environ.get("PACE_API_KEY")
    if key:
        return key.strip()
    with open(os.path.expanduser("~/.config/copado_pace/api_key")) as f:
        return f.read().strip()


def _headers():
    return {"X-Authorization": _api_key(), "Content-Type": "application/json"}


def download_file(project_id, job_id, path):
    resp = requests.post(
        f"{BASE_URL}/projects/{project_id}/jobs/{job_id}/files/download",
        json={"files": [path]}, headers=_headers(), timeout=15,
    )
    resp.raise_for_status()
    files = resp.json()["files"]
    match = next((f for f in files if f["path"] == path), None)
    if match is None:
        raise ValueError(f"{path} not found in PACE download response")
    return match["value"]


def upload_file(project_id, job_id, path, new_content,
                 author_name="Voice Agent", author_email="voice-agent@copado.com"):
    """Full-file overwrite -- new_content must be the COMPLETE file text,
    not a diff or fragment."""
    resp = requests.post(
        f"{BASE_URL}/projects/{project_id}/jobs/{job_id}/files/upload",
        json={
            "author": {"name": author_name, "email": author_email},
            "operations": [{"path": path, "op": "replace", "value": new_content}],
        },
        headers=_headers(), timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
