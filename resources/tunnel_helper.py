"""
Text-processing + tunnel-readiness polling RF Library -- no long-lived
credentials, safe to import directly.
"""
import re
import time

TUNNEL_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")


def extract_tunnel_url(process_output_text):
    """Robot Framework keyword. Regexes cloudflared's randomly-assigned
    quick-tunnel URL (a *.trycloudflare.com address, different every run)
    out of its captured stdout/stderr text. Raises AssertionError if none
    is found."""
    match = TUNNEL_URL_PATTERN.search(process_output_text)
    if not match:
        raise AssertionError(
            "No *.trycloudflare.com URL found in cloudflared's output."
        )
    return match.group(0)


def wait_for_tunnel_url(log_path, poll_interval_seconds=3, max_wait_seconds=30):
    """Robot Framework keyword. Polls a cloudflared log file until its
    quick-tunnel URL appears or max_wait_seconds elapses. Cloudflare's
    free quick-tunnel service explicitly has "no uptime guarantee" (its
    own banner text) -- confirmed live 2026-08-13 that it can occasionally
    take longer than a single fixed Sleep to come up (or not come up at
    all), so this replaces a blind Sleep-then-read-once with the same
    poll-until-ready approach already used for call completion. Raises
    AssertionError if the URL never appears within the timeout."""
    poll_interval_seconds = int(poll_interval_seconds)
    max_wait_seconds = int(max_wait_seconds)
    elapsed = 0
    while True:
        try:
            with open(log_path) as f:
                contents = f.read()
        except FileNotFoundError:
            contents = ""
        match = TUNNEL_URL_PATTERN.search(contents)
        if match:
            print(f"[{elapsed}s] tunnel URL found: {match.group(0)}")
            return match.group(0)
        print(f"[{elapsed}s] tunnel URL not yet available")
        if elapsed >= max_wait_seconds:
            raise AssertionError(
                f"No *.trycloudflare.com URL appeared in {log_path} within "
                f"{max_wait_seconds}s -- likely a real cloudflared/network "
                f"issue, not just slow startup. Last content:\n{contents}"
            )
        time.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds
