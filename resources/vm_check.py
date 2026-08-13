"""
Diagnostic-only. Confirms the CRT AWS VM's OS, Python, network reachability,
and binary/write access before the voice-POC harness gets built out for it.
Stdlib only -- must run before requirements.txt is installed.

Robot Framework imports this file as a Library (see tests/Agentvoice.robot),
which turns every public top-level function into a keyword -- so only
run_vm_check() is public; everything else is prefixed with _ to keep it out
of the keyword namespace.
"""
import base64
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


def get_working_directory():
    """Robot Framework keyword. Returns os.getcwd() -- use this instead of
    RF's built-in ${CURDIR} variable in this CRT execution context.
    Confirmed live 2026-08-13: ${CURDIR} resolves with a literal "None"
    path segment baked in (e.g. .../tests/None/tunnel_err.log, a
    FileNotFoundError on Get File), while prepare_cloudflared()'s
    os.getcwd()-based path in the very same run came back clean
    (.../tests/cloudflared). Root cause not fully diagnosed (likely CRT
    running a generated temp .robot file that throws off what RF
    considers "the current suite's directory"), but os.getcwd() inside a
    real Python keyword is confirmed reliable -- prefer it over ${CURDIR}
    for any new path-building in this project.
    """
    return os.getcwd()


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


def _get_credential(name):
    """CRT vault secrets land as Robot Framework variables (${NAME}), not
    OS environment variables, when this file is imported directly as an RF
    Library rather than run as a subprocess -- confirmed live 2026-08-13
    (call_harness.py's os.environ-based lookup failed despite the vault
    values being set). Checks RF's own variable scope first, falls back to
    os.environ for standalone `python vm_check.py` CLI use."""
    try:
        from robot.libraries.BuiltIn import BuiltIn

        value = BuiltIn().get_variable_value("${%s}" % name)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get(name)


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


def _fix_if_base64_mangled(raw_bytes, signature=b"\x7fELF"):
    """CRT's resource-import base64-encodes binary resource files without
    decoding them back out on the VM side (confirmed live 2026-08-13 against
    resources/bin/cloudflared -- its first bytes on the VM decode to a real
    ELF header). Detects that specific mangling and reverses it. Generalized
    beyond just ELF binaries (e.g. WAV's b"RIFF" header) so any future
    binary resource -- audio clips included -- can reuse this instead of
    rediscovering the bug live. Returns (usable_bytes, was_base64: bool)."""
    if raw_bytes[: len(signature)] == signature:
        return raw_bytes, False
    try:
        decoded = base64.b64decode(raw_bytes, validate=False)
    except Exception:
        return raw_bytes, False
    if decoded[: len(signature)] == signature:
        return decoded, True
    return raw_bytes, False


def prepare_binary_resource(bundled_path, signature, dest_filename, executable=False):
    """Fixes CRT's base64 mangling for any binary resource (not just
    cloudflared) and writes a usable copy to a writable path (cwd).
    signature is the expected magic-bytes prefix of a real, unmangled file
    (e.g. b"\\x7fELF" for an ELF binary, b"RIFF" for a WAV file). Returns
    the usable path. Raises AssertionError if a file matching signature
    can't be produced either way."""
    with open(bundled_path, "rb") as f:
        raw = f.read()

    fixed_bytes, was_base64 = _fix_if_base64_mangled(raw, signature)
    if fixed_bytes[: len(signature)] != signature:
        raise AssertionError(
            f"{bundled_path} doesn't match expected signature {signature!r} "
            f"even after attempting a base64-mangling fix -- first 16 bytes: "
            f"{fixed_bytes[:16]!r}"
        )

    usable_path = os.path.join(os.getcwd(), dest_filename)
    if was_base64:
        with open(usable_path, "wb") as f:
            f.write(fixed_bytes)
    else:
        shutil.copyfile(bundled_path, usable_path)
    if executable:
        os.chmod(usable_path, 0o755)
    return usable_path


def prepare_cloudflared():
    """Robot Framework keyword. Ensures a real, executable cloudflared binary
    exists at a writable path (cwd), decoding CRT's base64-mangled copy from
    resources/bin/ if needed. Returns the usable path. Raises AssertionError
    if a valid ELF binary can't be produced either way."""
    return prepare_binary_resource(BUNDLED_CLOUDFLARED, b"\x7fELF", "cloudflared", executable=True)


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

    resources_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(resources_dir, "bin")

    emit(f"\n=== resources/ contents (as seen from vm_check.py's own location: {resources_dir}) ===")
    if os.path.isdir(resources_dir):
        for entry in sorted(os.listdir(resources_dir)):
            emit(f"  {entry}")
    else:
        emit(f"resources dir not found: {resources_dir}")

    emit(f"\n=== resources/bin/ contents ({bin_dir}) ===")
    if os.path.isdir(bin_dir):
        for entry in sorted(os.listdir(bin_dir)):
            full = os.path.join(bin_dir, entry)
            size = os.path.getsize(full) if os.path.isfile(full) else "-"
            emit(f"  {entry}  size={size}  executable={os.access(full, os.X_OK)}")
    else:
        emit(f"resources/bin dir not found: {bin_dir}")

    emit("\n=== Bundled cloudflared (resources/bin/cloudflared, exact expected path) ===")
    if os.path.isfile(BUNDLED_CLOUDFLARED):
        size = os.path.getsize(BUNDLED_CLOUDFLARED)
        emit(f"present at: {BUNDLED_CLOUDFLARED}")
        emit(f"size: {size} (expected 39798028 -- the byte count of what was actually committed)")
        emit(f"executable: {os.access(BUNDLED_CLOUDFLARED, os.X_OK)}")
        with open(BUNDLED_CLOUDFLARED, "rb") as f:
            header = f.read(16)
        is_elf = header[:4] == b"\x7fELF"
        emit(f"first 16 bytes (hex): {header.hex()}")
        emit(f"valid ELF header (7f 45 4c 46 = real Linux executable): {is_elf}")
        if not is_elf:
            emit(f"first 16 bytes (as ascii, if printable): {header.decode('ascii', errors='replace')!r}")
    else:
        emit(f"not found at: {BUNDLED_CLOUDFLARED}")

    emit("\n=== prepare_cloudflared() -- attempt to fix the base64 mangling ===")
    try:
        usable_path = prepare_cloudflared()
        with open(usable_path, "rb") as f:
            fixed_header = f.read(16)
        emit(f"usable binary written to: {usable_path}")
        emit(f"size: {os.path.getsize(usable_path)}")
        emit(f"executable: {os.access(usable_path, os.X_OK)}")
        is_now_elf = fixed_header[:4] == b"\x7fELF"
        emit(f"valid ELF header now: {is_now_elf}")
    except Exception as e:
        emit(f"FAILED: {e.__class__.__name__}: {e}")

    emit("\n=== requirements.txt package availability (checked, not imported) ===")
    for import_name, pip_name in PACKAGES_TO_CHECK.items():
        found = importlib.util.find_spec(import_name) is not None
        emit(f"{pip_name} ({import_name}): {'installed' if found else 'NOT installed'}")

    emit("\n=== Outbound HTTPS reachability ===")
    for url in HOSTS_TO_CHECK:
        emit(f"{url}: {_check_network(url)}")

    emit("\n=== Credential presence check (names only, never prints values; checks RF variables, falls back to os.environ) ===")
    for var in ENV_VARS_TO_CHECK:
        emit(f"{var}: {'set' if _get_credential(var) else 'not set'}")

    emit("\nDone.")
    return "\n".join(lines)


if __name__ == "__main__":
    run_vm_check()
