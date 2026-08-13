"""
Places real outbound Twilio calls. Imported as a Robot Framework Library
(see tests/Agentvoice.robot) -- only public top-level functions become
keywords, so helpers are _-prefixed.

Credentials are passed in as arguments, not read from os.environ: CRT's
vault variables land as Robot Framework variables (${TWILIO_ACCOUNT_SID}
etc.), not OS environment variables, when a .py file is imported directly
as an RF Library rather than run as a subprocess -- confirmed live
2026-08-13 (a Missing required env var(s) failure despite the vault
values being set). Matches the existing convention in common.robot's
Login keyword (JwtAuthenticate takes ${CPQclient_id} etc. as arguments).
"""
import time

from twilio.rest import Client

TERMINAL_CALL_STATUSES = {"completed", "busy", "no-answer", "failed", "canceled"}


def place_verification_call(account_sid, auth_token, agent_number, caller_number, twiml_url):
    """Robot Framework keyword. Places a real outbound call from
    agent_number to caller_number (your cell), instructed by the TwiML at
    twiml_url, to prove the Twilio calling pipeline works end-to-end.
    Returns the Call SID.

    twiml_url must be a hosted TwiML URL (e.g. a TwiML Bin's URL) -- trial
    accounts reject an inline twiml= parameter on call creation (HTTP 400
    "Invalid or disallowed parameters", confirmed live 2026-08-13); only
    url= pointing at a hosted webhook is allowed.

    Call with the vault-backed RF variables, e.g.:
    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}
    ...    ${TWILIO_AGENT_NUMBER}    ${TWILIO_CALLER_NUMBER}    ${TWILIO_AGENT_TWIML_URL}
    """
    client = Client(account_sid, auth_token)
    call = client.calls.create(to=caller_number, from_=agent_number, url=twiml_url)
    print(f"Placed call. SID: {call.sid}  initial status: {call.status}")
    return call.sid


def place_call_to_configured_number(account_sid, auth_token, to_number, from_number, hold_seconds=150):
    """Robot Framework keyword. Places a call to a Twilio-owned number
    whose own voice_url is already configured (via set_number_voice_url)
    to run the real bridge -- using a minimal, passive inline TwiML for
    the outbound leg itself (just a Pause), NOT the same bridge URL.

    Confirmed live 2026-08-13: passing the same bridge url= on BOTH the
    outbound call AND the destination's voice_url causes Twilio to fetch
    and run the full bridge TwiML independently on both legs -- two
    separate /media-stream connections, two separate Deepgram sessions,
    both racing to inject the same CALLER_MODE script from turn 0
    (confirmed via duplicated events in the transcript, duplicated
    /voice hits in the bridge's own access log, and identical latency
    values across the "duplicate" events -- not two genuine sessions,
    the same underlying call's audio reaching two redundant relay
    pipelines). Twilio bridges the two legs' real audio together at the
    platform level regardless, so only ONE leg needs to run the actual
    bridge -- the destination's own voice_url (already correct); this
    leg just needs to stay open and passive while that happens.
    """
    client = Client(account_sid, auth_token)
    passive_twiml = f'<Response><Pause length="{int(hold_seconds)}"/></Response>'
    call = client.calls.create(to=to_number, from_=from_number, twiml=passive_twiml)
    print(f"Placed call (passive outbound leg). SID: {call.sid}  initial status: {call.status}")
    return call.sid


def set_number_voice_url(account_sid, auth_token, phone_number, voice_url):
    """Robot Framework keyword. Configures a Twilio-owned number's own
    "A call comes in" webhook. REQUIRED for a Twilio-owned number to
    answer at all when it's the `to=` of an API-originated call --
    confirmed live 2026-08-13 that a call's own `url=`/`application_sid=`
    parameter does NOT make a Twilio-owned destination answer by itself;
    the destination number needs this configured independently, or the
    call fails instantly (status=failed, duration=0, no error surfaced
    anywhere). Every call that worked before this fix had an external
    (non-Twilio-owned) destination, which has no such config to be
    missing -- that's why this went undiscovered for so long. Must be
    called with a fresh URL each run for a number fronting a bridge
    behind a cloudflared quick tunnel, since that URL changes every time.
    """
    client = Client(account_sid, auth_token)
    matches = [n for n in client.incoming_phone_numbers.list() if n.phone_number == phone_number]
    if not matches:
        raise AssertionError(f"No Twilio-owned number found matching {phone_number}")
    updated = client.incoming_phone_numbers(matches[0].sid).update(voice_url=voice_url, voice_method="POST")
    print(f"Set voice_url for {phone_number} -> {updated.voice_url}")
    return updated.voice_url


def get_call_status(account_sid, auth_token, call_sid):
    """Robot Framework keyword. Fetches a Call resource's real, current
    status by SID -- to check a call's actual outcome (ringing, completed,
    no-answer, busy, failed) via the API instead of hunting for it in the
    Twilio web app's UI. Returns a summary string; also prints it so it
    lands in the RF log.

    Note: if called immediately after Place Verification Call, the call
    may still be queued/ringing rather than at its final outcome -- a
    real phone call takes time to actually complete. A short Sleep before
    checking gives a more meaningful result.
    """
    client = Client(account_sid, auth_token)
    call = client.calls(call_sid).fetch()
    fields = {
        "status": call.status,
        "direction": call.direction,
        "duration": call.duration,
        "start_time": call.start_time,
        "end_time": call.end_time,
        "price": call.price,
        "answered_by": call.answered_by,
        "to": call.to,
        "from": call._from,
    }
    summary = "\n".join(f"{k}: {v}" for k, v in fields.items())
    print(summary)
    return summary


def wait_for_call_completion(account_sid, auth_token, call_sid, poll_interval_seconds=5, max_wait_seconds=180):
    """Robot Framework keyword. Polls a call's status until it reaches a
    terminal state (completed/busy/no-answer/failed/canceled) or
    max_wait_seconds elapses, whichever first -- so the test proceeds as
    soon as a call actually ends instead of blindly sleeping for a fixed
    duration. Returns the final status. Prints each poll so progress is
    visible in the log. Essential (not just nicer) once nobody is manually
    hanging up the call, since there's no human left to bound the wait.
    """
    client = Client(account_sid, auth_token)
    poll_interval_seconds = int(poll_interval_seconds)
    max_wait_seconds = int(max_wait_seconds)
    elapsed = 0
    while True:
        call = client.calls(call_sid).fetch()
        print(f"[{elapsed}s] call status: {call.status}")
        if call.status in TERMINAL_CALL_STATUSES:
            return call.status
        if elapsed >= max_wait_seconds:
            print(f"Timed out after {max_wait_seconds}s waiting for call to end; last status: {call.status}")
            return call.status
        time.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds


def end_call_if_active(account_sid, auth_token, call_sid):
    """Robot Framework keyword. Best-effort safety net for test teardown --
    if call_sid is a real, still-active call, ends it via the Twilio API.
    Never raises (catches everything, prints instead) so it's safe to call
    unconditionally from a [Teardown], including when call_sid is
    ${EMPTY} (test failed before a call was ever placed) or already ended
    naturally. Added after a real incident 2026-08-13: a bug elsewhere
    left a call genuinely stuck in-progress after its test had already
    finished and torn down the local bridge/tunnel processes -- killing
    those processes does NOT hang up the actual Twilio call, since the
    call is a resource on Twilio's platform, not tied to local process
    lifecycle. This exists so that whatever else might someday cause a
    call to not end itself cleanly, teardown still cleans it up.
    """
    if not call_sid:
        return
    try:
        client = Client(account_sid, auth_token)
        call = client.calls(call_sid).fetch()
        if call.status not in TERMINAL_CALL_STATUSES:
            client.calls(call_sid).update(status="completed")
            print(f"Teardown safety net: {call_sid} was still {call.status}, ended it.")
        else:
            print(f"Teardown safety net: {call_sid} already {call.status}, nothing to do.")
    except Exception as e:
        print(f"Teardown safety net: couldn't check/end {call_sid}: {e.__class__.__name__}: {e}")


def request_caller_id_verification(account_sid, auth_token, phone_number):
    """Robot Framework keyword. Starts Twilio's Verified Caller ID flow via
    the API instead of the console UI -- Twilio places a call to
    phone_number and expects a spoken-back validation code to be entered
    on the keypad. Prints and returns the validation code so it's visible
    in the RF log before the verification call arrives.

    Call with: Request Caller Id Verification    ${TWILIO_ACCOUNT_SID}
    ...    ${TWILIO_AUTH_TOKEN}    ${TWILIO_CALLER_NUMBER}
    """
    client = Client(account_sid, auth_token)
    validation_request = client.validation_requests.create(
        friendly_name="Agentforce voice POC",
        phone_number=phone_number,
    )
    print(
        f"Verification call incoming to {phone_number}. "
        f"When it rings, enter this code on the keypad: {validation_request.validation_code}"
    )
    return validation_request.validation_code
