"""
Local diagnostic for AGENTIC_MODE, same pattern as
local_caller_mode_diagnostic.py (bridge + a cloudflared tunnel + a real
Twilio call, all from this Mac, no CRT round-trip) -- but also runs
CALLER_MODE with a new scripted caller (resources/caller_audio_agentic/)
describing the "no browser was detected" CRT test issue, mints a
Salesforce access token from the already-authenticated `sf` CLI org to
pass into the bridge subprocess as SF_ACCESS_TOKEN/SF_INSTANCE_URL (see
sf_client.py's docstring for why the bridge itself doesn't shell out to
`sf` directly), and uses a NAMED Cloudflare Tunnel with a fixed hostname
(NAMED_TUNNEL_HOSTNAME below) instead of a throwaway quick tunnel -- see
that constant's comment for why: quick tunnels mint a brand-new random
subdomain every run, which occasionally isn't resolvable yet within our
readiness-polling window (confirmed live 2026-08-17 on two independent
networks). A stable, already-propagated hostname doesn't have that
problem after its one-time setup.

Usage:
    python3 resources/local_agentic_diagnostic.py [--to NUMBER] [--sf-org ALIAS]

Requires the same .env as local_caller_mode_diagnostic.py, a Salesforce
org already authenticated via `sf org login` under the alias passed via
--sf-org (default: jwt-jgarzaaf-copado-com-), and `cloudflared tunnel
login` already run against the copadojgcrt.us zone (credentials live in
~/.cloudflared/).

Shares the named tunnel's one fixed hostname + local port 5000 with
every other script/test that also uses it (Agentvoice.robot,
AgentvoiceAgentic.robot, local_caller_mode_diagnostic.py) -- don't run
this while any of those are also running.
"""
import argparse
import json
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
DEFAULT_SF_ORG_ALIAS = "jwt-jgarzaaf-copado-com-"
# Named Cloudflare Tunnel (not a throwaway quick tunnel) -- fixed hostname,
# set up 2026-08-17 specifically to avoid the fresh-random-subdomain DNS
# propagation flakiness quick tunnels hit (confirmed live: two independent
# networks both failed "Wait For Bridge Ready" on a brand-new
# *.trycloudflare.com hostname the same night). `cloudflared tunnel login`
# + `cloudflared tunnel create agentforce-voice-poc` + `cloudflared tunnel
# route dns agentforce-voice-poc voice-bridge.copadojgcrt.us` already run;
# credentials live in ~/.cloudflared/.
NAMED_TUNNEL_NAME = "agentforce-voice-poc"
NAMED_TUNNEL_HOSTNAME = "https://voice-bridge.copadojgcrt.us"


def _load_env():
    env_file = dotenv_values(os.path.join(REPO_ROOT, ".env"))
    env = os.environ.copy()
    env.update({k: v.strip() for k, v in env_file.items() if v is not None})
    return env


def _mint_sf_token(org_alias):
    """Shells out to the `sf` CLI once, locally, to get a fresh access
    token + instance URL for the bridge subprocess's env -- the CLI's own
    OAuth refresh handles token expiry here; the CRT-VM equivalent
    (no `sf` CLI available there) is a separate, not-yet-solved problem
    for the CRT-automation phase."""
    result = subprocess.run(
        ["sf", "org", "display", "-o", org_alias, "--json"],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)["result"]
    return data["accessToken"], data["instanceUrl"]


def _dig_resolve(hostname, dns_server="1.1.1.1"):
    """Resolves via a direct DNS query (dig), bypassing the local system
    resolver (getaddrinfo/mDNSResponder) entirely. Confirmed live
    2026-08-17: on this Mac, `dig` resolved a brand-new hostname
    correctly and instantly while `curl`/`urllib`/`socket.getaddrinfo`
    (all of which go through the OS resolver) failed outright with
    "Could not resolve host" for the same name at the same time -- a
    local resolver-cache quirk, not a real DNS/propagation problem
    (confirmed further: connecting directly to the dig-resolved IP with
    --resolve, preserving the correct Host/SNI, returned a clean 200).
    Returns the first A record, or None if dig itself finds nothing."""
    try:
        result = subprocess.run(
            ["dig", "+short", hostname, f"@{dns_server}", "-4"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line.endswith("."):  # skip any CNAME target lines
                return line
    except Exception:
        pass
    return None


def _curl_health_check(health_url, resolved_ip, timeout):
    hostname = health_url.split("/")[2].split(":")[0]
    cmd = ["curl", "-sf", "--max-time", str(timeout), "-o", "/dev/null", "-w", "%{http_code}"]
    if resolved_ip:
        cmd += ["--resolve", f"{hostname}:443:{resolved_ip}"]
    cmd.append(health_url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        return result.stdout.strip() == "200"
    except Exception:
        return False


def _wait_for_bridge_ready(tunnel_url, poll_interval=2, max_wait=45):
    health_url = tunnel_url.rstrip("/") + "/health"
    hostname = health_url.split("/")[2].split(":")[0]
    elapsed = 0
    while elapsed < max_wait:
        try:
            with urllib.request.urlopen(health_url, timeout=poll_interval) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            # Normal resolver failed -- try resolving around it directly
            # via dig before giving up this attempt (see _dig_resolve).
            resolved_ip = _dig_resolve(hostname)
            if resolved_ip and _curl_health_check(health_url, resolved_ip, poll_interval):
                print(f"  (resolved {hostname} via dig -> {resolved_ip}, bypassing a stuck local resolver)")
                return
        time.sleep(poll_interval)
        elapsed += poll_interval
    raise RuntimeError(f"{health_url} never returned 200 within {max_wait}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default=None,
                         help="Override destination number (default: TWILIO_CALLER_NUMBER, your cell)")
    parser.add_argument("--sf-org", default=DEFAULT_SF_ORG_ALIAS, help="sf CLI org alias to mint a token from")
    parser.add_argument("--python", default=sys.executable, help="Interpreter to run the bridge with")
    args = parser.parse_args()

    env = _load_env()
    to_number = args.to or env["TWILIO_CALLER_NUMBER"]

    print(f"Minting Salesforce token from org alias '{args.sf_org}'...")
    sf_access_token, sf_instance_url = _mint_sf_token(args.sf_org)
    print(f"Got token for instance: {sf_instance_url}")

    bridge_env = env.copy()
    bridge_env["CALLER_MODE"] = "1"
    bridge_env["AGENTIC_MODE"] = "1"
    bridge_env["LOG_FILENAME"] = "local_agentic_diag_log.jsonl"
    bridge_env["SF_ACCESS_TOKEN"] = sf_access_token
    bridge_env["SF_INSTANCE_URL"] = sf_instance_url
    bridge_env["PYTHONUNBUFFERED"] = "1"

    log_path = os.path.join(REPO_ROOT, "tests", "local_agentic_diag_log.jsonl")
    if os.path.exists(log_path):
        os.remove(log_path)

    print("Starting bridge (AGENTIC_MODE + CALLER_MODE)...")
    bridge = subprocess.Popen(
        [args.python, "-u", os.path.join(REPO_ROOT, "resources", "voice_agent_bridge.py")],
        cwd=REPO_ROOT,
        env=bridge_env,
        stdout=None,  # inherit -- want AGENTIC_MODE's print()s visible live for this diagnostic
        stderr=None,
    )
    time.sleep(3)

    print(f"Starting named cloudflared tunnel ({NAMED_TUNNEL_NAME})...")
    tunnel_log = "/tmp/local_agentic_diag_tunnel.log"
    tunnel = subprocess.Popen(
        ["cloudflared", "tunnel", "run", "--url", "http://localhost:5000", NAMED_TUNNEL_NAME],
        stdout=open(tunnel_log, "w"),
        stderr=subprocess.STDOUT,
    )

    call_sid = None
    try:
        tunnel_url = NAMED_TUNNEL_HOSTNAME
        print(f"Tunnel URL (fixed): {tunnel_url}")
        _wait_for_bridge_ready(tunnel_url)
        print("Bridge confirmed reachable end-to-end.")

        client = Client(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"])
        voice_url = tunnel_url + "/voice"
        call = client.calls.create(to=to_number, from_=env["TWILIO_AGENT_NUMBER"], url=voice_url)
        call_sid = call.sid
        print(f"Call placed to {to_number}. SID: {call_sid}")
        print("Answer your phone -- you'll hear the AGENT's side only "
              "(CALLER_MODE injects the script straight into Deepgram, not back to the phone).")

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
