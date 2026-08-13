"""
Diagnostic-only. Confirms the CRT AWS VM's OS, Python, network reachability,
and binary/write access before the voice-POC harness gets built out for it.
Stdlib only -- must run before requirements.txt is installed.
"""
import os
import platform
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

HOSTS_TO_CHECK = [
    "https://api.twilio.com",
    "https://api.deepgram.com",
    "https://www.cloudflare.com",
]


def check_network(url, timeout=8):
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return "OK"
    except urllib.error.HTTPError as e:
        # Got a real HTTP response -- DNS/TLS/routing all worked, the path
        # just doesn't accept a plain GET. That's reachability, not a failure.
        return f"OK (HTTP {e.code}, network path confirmed)"
    except Exception as e:
        return f"FAILED ({e.__class__.__name__}: {e})"


def check_write_and_exec(path):
    try:
        fd, tmp_path = tempfile.mkstemp(dir=path)
        os.close(fd)
        can_write = True
        os.chmod(tmp_path, 0o755)
        can_chmod_exec = True
        os.remove(tmp_path)
        return can_write, can_chmod_exec
    except Exception as e:
        return False, f"FAILED ({e.__class__.__name__}: {e})"


def main():
    print("=== VM / environment ===")
    print(f"platform.system():  {platform.system()}")
    print(f"platform.release(): {platform.release()}")
    print(f"platform.machine(): {platform.machine()}")
    print(f"python_version:     {platform.python_version()}")
    print(f"sys.executable:     {sys.executable}")
    print(f"cwd:                {os.getcwd()}")

    print("\n=== Project structure (cwd contents) ===")
    for entry in sorted(os.listdir(os.getcwd())):
        print(f"  {entry}")

    print("\n=== Write + exec permission in cwd ===")
    can_write, can_chmod = check_write_and_exec(os.getcwd())
    print(f"can write temp file: {can_write}")
    print(f"can chmod +x it:     {can_chmod}")

    print("\n=== Pre-existing binaries (informational; we'll bundle our own regardless) ===")
    for tool in ("ffmpeg", "cloudflared"):
        found = shutil.which(tool)
        print(f"{tool}: {found or 'not found'}")

    print("\n=== Outbound HTTPS reachability ===")
    for url in HOSTS_TO_CHECK:
        print(f"{url}: {check_network(url)}")

    print("\n=== Env var presence check (names only, never prints values) ===")
    for var in (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_CALLER_NUMBER",
        "TWILIO_AGENT_NUMBER",
        "DEEPGRAM_API_KEY",
    ):
        print(f"{var}: {'set' if os.environ.get(var) else 'not set'}")

    print("\nDone. Paste this full output back for review.")


if __name__ == "__main__":
    main()
