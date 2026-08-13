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
