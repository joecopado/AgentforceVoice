"""
Deepgram Voice Agent function-calling registry for AGENTIC_MODE (see
voice_agent_bridge.py). Two functions the LLM can invoke mid-call, both
executed client-side (i.e. by this bridge, not by Deepgram itself) --
per Deepgram's real schema (confirmed 2026-08-17 from the Python SDK's
generated types, think_settings_v1functions_item.py, not a doc summary):
a function item is only {name, description, parameters, endpoint} --
there is no "client_side" boolean field. A function runs client-side
simply when "endpoint" is omitted; including a bogus "client_side" key
made Deepgram reject the whole Settings message outright
(UNPARSABLE_CLIENT_MESSAGE, confirmed live -- the call connected with
zero audio because of this):

- diagnose_and_fix_test_job: patches the real, known bug in the demo CRT
  job (tests/salesforceTests.robot missing a Suite Setup / OpenBrowser
  line) via the PACE API. The actual fix logic is deterministic Python,
  not LLM-generated text -- same philosophy as CALLER_MODE's bounded
  keyword branching (see project memory): the LLM decides *when* to call
  this and relays the result, it doesn't decide *what* the fix is.
- update_case: updates the Salesforce Case opened for this call (see
  identify_caller_and_open_case in voice_agent_bridge.py) with a status
  and/or notes.

Each handler takes (params, state) -- state is the same per-call dict
media_stream() builds in voice_agent_bridge.py (holds case_id, contact,
etc.) -- and returns a JSON-serializable dict, which the bridge sends
back as a FunctionCallResponse's "output".
"""
import os
import re

import pace_client
import sf_client

PACE_PROJECT_ID = os.environ.get("PACE_PROJECT_ID", "104385")
PACE_JOB_ID = os.environ.get("PACE_JOB_ID", "197407")
TARGET_FILE = "tests/salesforceTests.robot"


def _patch_missing_suite_setup(content):
    """Returns (new_content, changed). Idempotent: if a Suite Setup line
    already exists, does nothing -- confirmed against the real file
    2026-08-17 that *** Settings *** has Resource + Suite Teardown but no
    Suite Setup at all, which is exactly the reported 'no browser was
    detected' Live Testing error."""
    if re.search(r"(?m)^\s*Suite Setup\b", content):
        return content, False
    lines = content.splitlines(keepends=True)
    insert_at = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Resource"):
            insert_at = i + 1
            break
    if insert_at is None:
        for i, line in enumerate(lines):
            if line.strip() == "*** Settings ***":
                insert_at = i + 1
                break
    if insert_at is None:
        raise ValueError("Could not find *** Settings *** section to patch")
    lines.insert(insert_at, "Suite Setup                   Setup Browser\n")
    return "".join(lines), True


def handle_diagnose_and_fix_test_job(params, state):
    content = pace_client.download_file(PACE_PROJECT_ID, PACE_JOB_ID, TARGET_FILE)
    new_content, changed = _patch_missing_suite_setup(content)
    if not changed:
        return {"changed": False, "summary": "No missing Suite Setup found -- the file already has one."}
    pace_client.upload_file(PACE_PROJECT_ID, PACE_JOB_ID, TARGET_FILE, new_content)
    state["fix_applied"] = True
    return {
        "changed": True,
        "summary": "Added a Suite Setup step (Setup Browser) to the Settings section of "
                    "tests/salesforceTests.robot, which was missing and causing the "
                    "'no browser was detected' Live Testing error.",
    }


def handle_update_case(params, state):
    case_id = state.get("case_id")
    if not case_id:
        return {"error": "No case is open for this call yet."}
    sf_client.update_case(case_id, status=params.get("status"), description=params.get("notes"))
    if params.get("status"):
        state["last_case_status"] = params["status"]
    return {"success": True}


FUNCTION_MAP = {
    "diagnose_and_fix_test_job": handle_diagnose_and_fix_test_job,
    "update_case": handle_update_case,
}

FUNCTION_DEFINITIONS = [
    {
        "name": "diagnose_and_fix_test_job",
        "description": (
            "Reads the caller's failing CRT test job file, checks for a missing Suite Setup "
            "(browser-launch) configuration, and fixes it if found. Call this when the caller "
            "describes a test that fails to start Live Testing, especially errors mentioning "
            "'no browser was detected' or an Open Browser keyword."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_case",
        "description": (
            "Updates the support case open for this call with a new status and/or notes. Call "
            "this whenever there's a meaningful update to log (e.g. after diagnosing or fixing "
            "the issue), and always once more right before ending the call to record the final "
            "outcome."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["New", "In Progress", "Escalated", "Closed"],
                    "description": "New status for the case.",
                },
                "notes": {
                    "type": "string",
                    "description": "Notes describing what was found or done, set as the case description.",
                },
            },
            "required": [],
        },
    },
]
