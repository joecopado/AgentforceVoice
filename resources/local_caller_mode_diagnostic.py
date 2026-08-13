"""
Standalone local diagnostic: runs the exact same bridge code CRT Live
Testing uses (voice_agent_bridge.py, CALLER_MODE=1), but on this Mac
instead of the CRT VM -- bridge + a local cloudflared tunnel + a real
Twilio call, all launched from a single script, no CRT round-trip.

Built 2026-08-13 while chasing the CALLER_MODE deadlock (see
GRACE_HANGUP_SECONDS / SILENCE_PAD_SECONDS / _keepalive_loop in
voice_agent_bridge.py, and the twilio_voice_poc_gotchas + project
memory for the full story) -- this is what made it possible to iterate
on that bug in ~1 minute per attempt instead of a full CRT Live Testing
round-trip. Kept as a reusable asset per the user's request, not a
one-off scratch script.

Places the call to TWILIO_CALLER_NUMBER (your real cell) by default --
CALLER_MODE means you WON'T hear the pre-recorded caller lines
(they're injected straight into the Deepgram session, never routed
back to the phone); you'll hear the AGENT's spoken side only, which is
actually the more useful test since it proves whether the agent
understood the full injected line or just a fragment. Check
tests/local_diag_log.jsonl afterward for the exact transcript.

Usage:
    pip install -r requirements.txt python-dotenv   # one-time
    brew install cloudflared                        # one-time
    python3 resources/local_caller_mode_diagnostic.py

Requires .env in the repo root with TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
TWILIO_AGENT_NUMBER, TWILIO_CALLER_NUMBER, DEEPGRAM_API_KEY. Note: python's
`source .env` / `set -a` does NOT work on this repo's .env -- its lines
are `KEY= value` (space after `=`), which bash's source misparses as a
command. Always load it with python-dotenv (dotenv_values), never `source`.
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from dotenv import dotenv_values
from twilio.rest import Client

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMINAL_CALL_STATUSES = {"completed", "busy", "no-answer", "failed", "canceled"}


def _load_env():
    env_file = dotenv_values(os.path.join(REPO_ROOT, ".env"))
    env = os.environ.copy()
    env.update({k: v.strip() for k, v in env_file.items() if v is not None})
    return env


def _wait_for_tunnel_url(log_path, poll_interval=1, max_wait=30):
    import re
    pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    elapsed = 0
    while elapsed < max_wait:
        try:
            with open(log_path) as f:
                match = pattern.search(f.read())
        except FileNotFoundError:
            match = None
        if match:
            return match.group(0)
        time.sleep(poll_interval)
        elapsed += poll_interval
    raise RuntimeError(f"No tunnel URL appeared in {log_path} within {max_wait}s")


def _wait_for_bridge_ready(tunnel_url, poll_interval=2, max_wait=20):
    health_url = tunnel_url.rstrip("/") + "/health"
    elapsed = 0
    while elapsed < max_wait:
        try:
            with urllib.request.urlopen(health_url, timeout=poll_interval) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(poll_interval)
        elapsed += poll_interval
    raise RuntimeError(f"{health_url} never returned 200 within {max_wait}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default=None, help="Override destination number (default: TWILIO_CALLER_NUMBER)")
    parser.add_argument("--python", default=sys.executable, help="Interpreter to run the bridge with")
    args = parser.parse_args()

    env = _load_env()
    to_number = args.to or env["TWILIO_CALLER_NUMBER"]

    bridge_env = env.copy()
    bridge_env["CALLER_MODE"] = "1"
    bridge_env["LOG_FILENAME"] = "local_diag_log.jsonl"
    bridge_env["PYTHONUNBUFFERED"] = "1"

    log_path = os.path.join(REPO_ROOT, "tests", "local_diag_log.jsonl")
    if os.path.exists(log_path):
        os.remove(log_path)

    print("Starting bridge...")
    bridge = subprocess.Popen(
        [args.python, "-u", os.path.join(REPO_ROOT, "resources", "voice_agent_bridge.py")],
        cwd=REPO_ROOT,
        env=bridge_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    print("Starting cloudflared tunnel...")
    tunnel_log = "/tmp/local_caller_mode_diag_tunnel.log"
    tunnel = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:5000"],
        stdout=open(tunnel_log, "w"),
        stderr=subprocess.STDOUT,
    )

    call_sid = None
    try:
        tunnel_url = _wait_for_tunnel_url(tunnel_log)
        print(f"Tunnel URL: {tunnel_url}")
        _wait_for_bridge_ready(tunnel_url)
        print("Bridge confirmed reachable end-to-end.")

        client = Client(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"])
        voice_url = tunnel_url + "/voice"
        call = client.calls.create(to=to_number, from_=env["TWILIO_AGENT_NUMBER"], url=voice_url)
        call_sid = call.sid
        print(f"Call placed to {to_number}. SID: {call_sid}")
        print("Answer your phone -- you'll hear the AGENT's side only "
              "(CALLER_MODE injects the script straight into Deepgram, "
              "not back to the phone).")

        elapsed = 0
        while elapsed < 180:
            status = client.calls(call_sid).fetch().status
            if status in TERMINAL_CALL_STATUSES:
                print(f"Call ended: {status}")
                break
            time.sleep(5)
            elapsed += 5
        else:
            print("Timed out waiting for call to end.")
    finally:
        print("Cleaning up...")
        bridge.terminate()
        tunnel.terminate()
        if call_sid:
            try:
                client = Client(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"])
                c = client.calls(call_sid).fetch()
                if c.status not in TERMINAL_CALL_STATUSES:
                    client.calls(call_sid).update(status="completed")
                    print(f"Safety net: ended still-active call {call_sid}")
            except Exception as e:
                print(f"Safety net cleanup failed (likely already ended): {e}")

        if os.path.exists(log_path):
            print(f"\n=== Transcript ({log_path}) ===")
            with open(log_path) as f:
                print(f.read())


if __name__ == "__main__":
    main()
