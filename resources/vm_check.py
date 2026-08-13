"""
Diagnostic-only. Confirms the CRT AWS VM's OS, Python, network reachability,
and binary/write access before the voice-POC harness gets built out for it.
Stdlib only -- must run before requirements.txt is installed.

Robot Framework imports this file as a Library (see tests/Agentvoice.robot),
which turns every public top-level function into a keyword -- so only
run_vm_check() is public; everything else is prefixed with _ to keep it out
of the keyword namespace.
"""
import importlib.util
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

ENV_VARS_TO_CHECK = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_CALLER_NUMBER",
    "TWILIO_AGENT_NUMBER",
    "DEEPGRAM_API_KEY",
)

# import name -> pip package name, for the packages the real harness needs
PACKAGES_TO_CHECK = {
    "flask": "flask",
    "flask_sock": "flask-sock",
    "twilio": "twilio",
    "deepgram": "deepgram-sdk",
    "dotenv": "python-dotenv",
}

BUNDLED_CLOUDFLARED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "cloudflared")


def _check_network(url, timeout=8):
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return "OK"
    except urllib.error.HTTPError as e:
        # Got a real HTTP response -- DNS/TLS/routing all worked, the path
        # just doesn't accept a plain GET. That's reachability, not a failure.
        return f"OK (HTTP {e.code}, network path confirmed)"
    except Exception as e:
        return f"FAILED ({e.__class__.__name__}: {e})"


def _check_write_and_exec(path):
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


def run_vm_check():
    """Robot Framework keyword. Runs the full VM diagnostic, prints it
    (so it lands in the RF log) and returns it as a string too (so a test
    case can capture it into a variable and assert on it)."""
    lines = []

    def emit(line=""):
        lines.append(line)
        print(line)

    emit("=== VM / environment ===")
    emit(f"platform.system():  {platform.system()}")
    emit(f"platform.release(): {platform.release()}")
    emit(f"platform.machine(): {platform.machine()}")
    emit(f"python_version:     {platform.python_version()}")
    emit(f"sys.executable:     {sys.executable}")
    emit(f"cwd:                {os.getcwd()}")

    emit("\n=== Project structure (cwd contents) ===")
    for entry in sorted(os.listdir(os.getcwd())):
        emit(f"  {entry}")

    emit("\n=== Write + exec permission in cwd ===")
    can_write, can_chmod = _check_write_and_exec(os.getcwd())
    emit(f"can write temp file: {can_write}")
    emit(f"can chmod +x it:     {can_chmod}")

    emit("\n=== Pre-existing binaries on PATH ===")
    for tool in ("ffmpeg", "cloudflared"):
        found = shutil.which(tool)
        emit(f"{tool}: {found or 'not found'}")

    emit("\n=== Bundled cloudflared (resources/bin/cloudflared) ===")
    if os.path.isfile(BUNDLED_CLOUDFLARED):
        emit(f"present at: {BUNDLED_CLOUDFLARED}")
        emit(f"executable: {os.access(BUNDLED_CLOUDFLARED, os.X_OK)}")
    else:
        emit(f"not found at: {BUNDLED_CLOUDFLARED}")

    emit("\n=== requirements.txt package availability (checked, not imported) ===")
    for import_name, pip_name in PACKAGES_TO_CHECK.items():
        found = importlib.util.find_spec(import_name) is not None
        emit(f"{pip_name} ({import_name}): {'installed' if found else 'NOT installed'}")

    emit("\n=== Outbound HTTPS reachability ===")
    for url in HOSTS_TO_CHECK:
        emit(f"{url}: {_check_network(url)}")

    emit("\n=== Env var presence check (names only, never prints values) ===")
    for var in ENV_VARS_TO_CHECK:
        emit(f"{var}: {'set' if os.environ.get(var) else 'not set'}")

    emit("\nDone.")
    return "\n".join(lines)


if __name__ == "__main__":
    run_vm_check()
