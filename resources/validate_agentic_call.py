"""
Post-call validation helper for AgentvoiceAgentic.robot -- confirms the
CRT job file (tests/salesforceTests.robot) genuinely has the Suite Setup
fix applied, by re-reading it via the PACE API rather than trusting the
agent's own claim in the transcript.

The Salesforce-side checks (a new Case was created, closed correctly,
with notes) are done directly in the .robot file via QForce's own
QueryRecords keyword -- no Python needed there. This script only covers
the PACE/CRT-job side, which has no equivalent native keyword.

Called via RF's Run Process (synchronous, NOT Start Process); exits
non-zero with a message on stderr when the fix isn't found, so
`Should Be Equal As Integers    ${result.rc}    0` alone gates the step.

Needs PACE_API_KEY in its environment (see pace_client.py).

Usage: validate_agentic_call.py [--project-id ID] [--job-id ID] [--path PATH]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentic_functions  # noqa: E402
import pace_client  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=agentic_functions.PACE_PROJECT_ID)
    parser.add_argument("--job-id", default=agentic_functions.PACE_JOB_ID)
    parser.add_argument("--path", default=agentic_functions.TARGET_FILE)
    args = parser.parse_args()

    content = pace_client.download_file(args.project_id, args.job_id, args.path)
    if not re.search(r"(?m)^\s*Suite Setup\b", content):
        print(f"{args.path} still has no Suite Setup line", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
