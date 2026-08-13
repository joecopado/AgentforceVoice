"""
Pure text-processing RF Library -- no credentials, safe to import directly.
"""
import re

TUNNEL_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")


def extract_tunnel_url(process_output_text):
    """Robot Framework keyword. Regexes cloudflared's randomly-assigned
    quick-tunnel URL (a *.trycloudflare.com address, different every run)
    out of its captured stdout/stderr text. Raises AssertionError if none
    is found, since a Sleep-then-read race (tunnel not up yet) is the most
    likely cause and should fail loudly rather than pass an empty URL on."""
    match = TUNNEL_URL_PATTERN.search(process_output_text)
    if not match:
        raise AssertionError(
            "No *.trycloudflare.com URL found in cloudflared's output -- "
            "tunnel may not be up yet (try a longer Sleep before reading)."
        )
    return match.group(0)
