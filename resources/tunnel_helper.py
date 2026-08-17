"""
Text-processing + tunnel-readiness polling RF Library -- no long-lived
credentials, safe to import directly.
"""
import re
import time
import urllib.error
import urllib.request

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


def wait_for_bridge_ready(tunnel_url, poll_interval_seconds=2, max_wait_seconds=45, request_timeout_seconds=10):
    """Robot Framework keyword. Polls tunnel_url + "/health" (a plain GET
    route on the bridge itself) until it actually returns 200, or
    max_wait_seconds elapses. wait_for_tunnel_url only confirms cloudflared
    printed its own URL -- confirmed live 2026-08-13 that this is NOT the
    same as the full chain (Cloudflare edge -> tunnel -> local Flask
    process) being ready end-to-end: an automated call was placed right
    after the tunnel URL appeared, and Twilio's Monitor alerts logged
    error 11200 ("Got HTTP 502 response") fetching /voice at the exact
    call timestamp, causing Twilio to decline the call almost instantly
    (SIP 603, ~75ms post-dial delay -- confirmed via the Twilio console).
    Call this right before Set Number Voice Url, so a call is only placed
    once the bridge has proven itself reachable through the real public
    URL, not just assumed ready after a fixed Sleep. Raises AssertionError
    on timeout so a genuinely broken chain fails fast and loud instead of
    producing another instant-decline call.

    request_timeout_seconds is deliberately SEPARATE from poll_interval_seconds
    (confirmed live 2026-08-17: this used to reuse poll_interval_seconds --
    2s -- as EACH individual request's own timeout, so on a CRT VM run where
    the tunnel itself was fully healthy (4 registered HA connections, all
    connectivity prechecks passing per cloudflared's own log) the health
    check still failed identically at both a 20s and a 45s max_wait_seconds
    -- because if a single round trip through Cloudflare's edge back to the
    origin genuinely takes longer than 2s on some network path, EVERY
    attempt fails the same way no matter how many times it's retried or how
    long the overall window is. A longer overall wait only helps if an
    individual attempt is actually given enough time to succeed.)

    Per-attempt diagnostics are folded directly into the raised
    AssertionError's own message on timeout, NOT emitted via print() --
    confirmed live 2026-08-17 that plain print() output from a Python
    library keyword does not surface anywhere in CRT's Live Testing view
    (only Log To Console / file-then-Log-File-If-Exists does). Embedding
    the history directly in the exception message means it's guaranteed
    visible in the FAIL line itself regardless of that, or of whether a
    [Teardown]/inline log-dump step ever runs at all."""
    poll_interval_seconds = int(poll_interval_seconds)
    max_wait_seconds = int(max_wait_seconds)
    request_timeout_seconds = int(request_timeout_seconds)
    health_url = tunnel_url.rstrip("/") + "/health"
    elapsed = 0
    attempts = []
    while True:
        try:
            with urllib.request.urlopen(health_url, timeout=request_timeout_seconds) as resp:
                if resp.status == 200:
                    return True
                attempts.append(f"[{elapsed}s] HTTP {resp.status}")
        except (urllib.error.URLError, OSError) as e:
            attempts.append(f"[{elapsed}s] {e.__class__.__name__}: {e}")
        if elapsed >= max_wait_seconds:
            history = "\n".join(attempts[-10:])
            raise AssertionError(
                f"{health_url} never returned 200 within {max_wait_seconds}s -- "
                "the tunnel/bridge chain isn't actually reachable end-to-end "
                "yet, placing a call now would likely get an instant Twilio "
                f"decline (502 fetching /voice).\nPer-attempt history:\n{history}"
            )
        time.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds
