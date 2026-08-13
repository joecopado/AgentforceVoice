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
from twilio.rest import Client

VERIFICATION_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response><Say>Hello, this is a test agent.</Say></Response>"
)


def place_verification_call(account_sid, auth_token, agent_number, caller_number):
    """Robot Framework keyword. Places a real outbound call from
    agent_number to caller_number (your cell), reading an inline TwiML
    script aloud, to prove the Twilio calling pipeline works end-to-end.
    Returns the Call SID.

    Call with the vault-backed RF variables, e.g.:
    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}
    ...    ${TWILIO_AGENT_NUMBER}    ${TWILIO_CALLER_NUMBER}
    """
    client = Client(account_sid, auth_token)
    call = client.calls.create(to=caller_number, from_=agent_number, twiml=VERIFICATION_TWIML)
    print(f"Placed call. SID: {call.sid}  initial status: {call.status}")
    return call.sid
