"""
Places real outbound Twilio calls. Imported as a Robot Framework Library
(see tests/Agentvoice.robot) -- only public top-level functions become
keywords, so helpers are _-prefixed.
"""
import os

from twilio.rest import Client

VERIFICATION_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response><Say>Hello, this is a test agent.</Say></Response>"
)

REQUIRED_ENV_VARS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_AGENT_NUMBER",
    "TWILIO_CALLER_NUMBER",
)


def _client():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise AssertionError(f"Missing required env var(s): {', '.join(missing)}")
    return Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])


def place_verification_call():
    """Robot Framework keyword. Places a real outbound call from
    TWILIO_AGENT_NUMBER to TWILIO_CALLER_NUMBER (your cell), reading an
    inline TwiML script aloud, to prove the Twilio calling pipeline works
    end-to-end. Returns the Call SID."""
    client = _client()
    call = client.calls.create(
        to=os.environ["TWILIO_CALLER_NUMBER"],
        from_=os.environ["TWILIO_AGENT_NUMBER"],
        twiml=VERIFICATION_TWIML,
    )
    print(f"Placed call. SID: {call.sid}  initial status: {call.status}")
    return call.sid
