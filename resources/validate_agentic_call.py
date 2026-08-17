"""
CLI validation helper for AgentvoiceAgentic.robot -- called via RF's Run
Process (synchronous, NOT Start Process) before and after a call to
validate the agent's real side effects: a new Salesforce Case was
created with the right status/notes, and the CRT job file actually has
the fix applied. Prints a single JSON line to stdout for the caller to
parse (JSONLibrary's Convert String To Json is already available via
common.robot); exits non-zero (with a human-readable message on stderr)
when a check fails, so `Should Be Equal As Integers    ${result.rc}    0`
alone is enough to gate a test step, independent of parsing the JSON.

Needs SF_ACCESS_TOKEN / SF_INSTANCE_URL (for latest-case/check-case) or
PACE_API_KEY (for check-job-fix) in its environment -- same variables
the bridge itself uses, see sf_client.py / pace_client.py.

Usage:
    validate_agentic_call.py latest-case
    validate_agentic_call.py check-case --case-id 500... --expected-status Closed
    validate_agentic_call.py check-job-fix [--project-id ID] [--job-id ID] [--path PATH]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentic_functions  # noqa: E402
import pace_client  # noqa: E402
import sf_client  # noqa: E402


def cmd_latest_case(args):
    case = sf_client.find_latest_case()
    print(json.dumps(case or {}))
    if case is None:
        print("No Case records exist at all in this org", file=sys.stderr)
        sys.exit(1)


def cmd_check_case(args):
    case = sf_client.get_case(args.case_id)
    status_ok = case.get("Status") == args.expected_status
    has_notes = bool((case.get("Description") or "").strip())
    ok = status_ok and has_notes
    print(json.dumps({"ok": ok, "status": case.get("Status"), "description": case.get("Description")}))
    if not ok:
        print(
            f"Case {args.case_id} failed validation -- "
            f"status={case.get('Status')!r} (expected {args.expected_status!r}), "
            f"has_notes={has_notes}",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_check_job_fix(args):
    content = pace_client.download_file(args.project_id, args.job_id, args.path)
    has_fix = bool(re.search(r"(?m)^\s*Suite Setup\b", content))
    print(json.dumps({"has_fix": has_fix}))
    if not has_fix:
        print(f"{args.path} still has no Suite Setup line", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("latest-case").set_defaults(func=cmd_latest_case)

    p = sub.add_parser("check-case")
    p.add_argument("--case-id", required=True)
    p.add_argument("--expected-status", default="Closed")
    p.set_defaults(func=cmd_check_case)

    p = sub.add_parser("check-job-fix")
    p.add_argument("--project-id", default=agentic_functions.PACE_PROJECT_ID)
    p.add_argument("--job-id", default=agentic_functions.PACE_JOB_ID)
    p.add_argument("--path", default=agentic_functions.TARGET_FILE)
    p.set_defaults(func=cmd_check_job_fix)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
