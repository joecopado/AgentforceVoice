"""
Standalone Flask + flask-sock server -- NOT an RF Library, launched as a
subprocess (via RF's Process library, see tests/Agentvoice.robot), so it
reads credentials from a real OS environment normally. This is different
from vm_check.py/call_harness.py, which are imported directly as RF
Libraries and can't use os.environ for CRT-vault values -- see
crt_voice_poc_vm_gotchas memory for why.

Bridges a Twilio Media Stream (one call) to Deepgram's Voice Agent API,
per Deepgram's own Twilio integration reference
(developers.deepgram.com/docs/twilio-and-deepgram-voice-agent) and
Deepgram's managed-Anthropic config (developers.deepgram.com/docs/
voice-agent-llm-models) -- no separate Anthropic key needed, billed
through the Deepgram account.

CALLER_MODE (env var): when set, no human is on the call at all. Instead
of relaying Twilio's real inbound Media Stream audio to Deepgram, this
plays a fixed, pre-recorded caller script into the same Deepgram session
-- deterministic by design (see project memory: a fully LLM-driven
"caller bot" was considered and rejected as non-reproducible for a
regression test). Turn-taking uses Deepgram's own AgentAudioDone event,
already proven to fire reliably in the human-driven transcript.
"""
import audioop
import base64
import json
import os
import sys
import threading
import time
import wave

import websocket
from flask import Flask, request
from flask_sock import Sock
from twilio.rest import Client

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vm_check import prepare_binary_resource  # noqa: E402
import agentic_functions  # noqa: E402
import sf_client  # noqa: E402

DEEPGRAM_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"
PORT = int(os.environ.get("PORT", "5000"))
CALLER_MODE = bool(os.environ.get("CALLER_MODE", ""))
# See project_agentforce_voice_agentic memory. When set, the agent gets a
# different persona plus Deepgram function-calling (agentic_functions.py)
# wired to real Salesforce Case CRUD and a real CRT-job fix via the PACE
# API, instead of pure conversation. Independent of CALLER_MODE -- both
# can be on together (a scripted caller describing the support scenario,
# talking to an agent that can actually act on it).
AGENTIC_MODE = bool(os.environ.get("AGENTIC_MODE", ""))
LOG_FILENAME = os.environ.get("LOG_FILENAME", "conversation_log.jsonl")

AGENT_SYSTEM_PROMPT = """\
#Role
You are a quick support assistant for Copado Robotic Testing (CRT), speaking to callers over the phone. Your task is to answer a few basic questions about CRT clearly and helpfully.

#General Guidelines
-Be warm, friendly, and professional.
-Speak clearly and naturally in plain language.
-Keep most responses to 1-2 sentences and under 120 characters unless the caller asks for more detail (max: 300 characters).
-Do not use markdown formatting, like code blocks, quotes, bold, links, or italics.
-Use varied phrasing; avoid repetition.
-If unclear, ask for clarification.
-If asked about your well-being, respond briefly and kindly.

#Voice-Specific Instructions
-Speak in a conversational tone -- your responses will be spoken aloud.
-Pause after questions to allow for replies.
-Confirm what the caller said if uncertain.
-Never interrupt.

#Style
-Use active listening cues.
-Be warm and understanding, but concise.
-Use simple words unless the caller uses technical terms.

#Call Flow Objective
-Greet the caller and introduce yourself:
"Hi there! Thanks for calling Copado Robotic Testing support -- how can I help today?"
-Your primary goal is to answer basic questions about Copado Robotic Testing. This may include:
What it is: "Copado Robotic Testing is a no-code test automation platform built for enterprise apps like Salesforce."
Getting started: "You can record your first test right in the browser, or write steps in plain English -- most teams are running tests within a day."
Salesforce support: "It's purpose-built for Salesforce, understanding Lightning components out of the box -- no custom locators needed."
-If the request is unclear:
"Just to confirm, did you mean...?" or "Can you tell me a bit more?"
-If the request is out of scope (e.g. pricing negotiations, account-specific issues, technical support):
"I'm not able to help with that directly, but I can connect you with a specialist."

#Off-Scope Questions
-If asked about anything outside Copado Robotic Testing:
"I'm just set up to answer questions about Copado Robotic Testing today, but I'd be glad to help with that."

#Closing
-Always ask:
"Is there anything else I can help you with today?"
-Then thank them warmly and say:
"Thanks for calling. Take care and have a great day!"
"""

AGENTIC_SYSTEM_PROMPT = """\
#Role
You are a Copado Robotic Testing (CRT) support agent, speaking to a caller over the phone about a CRT test issue. Unlike a normal support line, you have real tools: you can inspect and fix the caller's actual test job, and you keep a support case updated as you work.

#General Guidelines
-Be warm, friendly, and professional.
-Speak clearly and naturally in plain language.
-Keep most responses to 1-2 sentences and under 120 characters unless more detail is needed (max: 300 characters).
-Do not use markdown formatting, like code blocks, quotes, bold, links, or italics.
-Use varied phrasing; avoid repetition.

#Voice-Specific Instructions
-Speak in a conversational tone -- your responses will be spoken aloud.
-Pause after questions to allow for replies.
-Never interrupt.

#Tools
-You have two functions available: diagnose_and_fix_test_job and update_case.
-Call diagnose_and_fix_test_job as soon as the caller describes a test that fails to start Live Testing, especially anything about "no browser was detected" or a missing Open Browser step. Don't ask permission first -- just do it, then tell the caller what you found.
-diagnose_and_fix_test_job reporting the Suite Setup step is already present (no change needed) means the "no browser was detected" issue the caller described IS RESOLVED -- either you just fixed it or it was already fixed. This is a successful outcome, not a sign of some other, unexplained problem. Do not treat "already present" as inconclusive or as reason to suspect a different issue -- explain to the caller that their browser launch step is in place and the error should be gone.
-If your own view of a diagnose_and_fix_test_job call looks interrupted or cancelled but you did receive a diagnostic result for it, trust and use that result -- it means the check completed for real even though the turn got interrupted.
-Call update_case after diagnosing or fixing the issue, and again right before ending the call, to record a short status and notes summarizing the outcome.

#Call Flow Objective
-Greet the caller and ask what test issue they're running into.
-Once they describe it, call diagnose_and_fix_test_job.
-Explain the result in plain language (what was wrong, what you changed).
-Call update_case to log the outcome (status "Closed" if the Suite Setup step is now in place, whether you just added it or it was already there; "Escalated" only if diagnose_and_fix_test_job could not find or explain the reported problem at all).
-Ask if there's anything else, then close out warmly.

#Closing
-Always ask: "Is there anything else I can help you with today?"
-Then thank them and say: "Thanks for calling. Take care and have a great day!"
"""


def _build_settings_message():
    agent = {
        "language": "en",
        "listen": {"provider": {"type": "deepgram", "model": "nova-3"}},
        "think": {
            "provider": {"type": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.5},
            "prompt": AGENTIC_SYSTEM_PROMPT if AGENTIC_MODE else AGENT_SYSTEM_PROMPT,
        },
        "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
        "greeting": "Hi there! Thanks for calling Copado Robotic Testing support -- how can I help today?",
    }
    if AGENTIC_MODE:
        agent["think"]["functions"] = agentic_functions.FUNCTION_DEFINITIONS
    return {
        "type": "Settings",
        "audio": {
            "input": {"encoding": "mulaw", "sample_rate": 8000},
            "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"},
        },
        "agent": agent,
    }

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", LOG_FILENAME)

# Second, much smaller log: same event stream as LOG_PATH, but limited to the
# event types worth actually reading (conversation text, turn-taking, function
# calls) -- dropping the noise (Welcome, SettingsApplied, History duplicate
# lines, LatencyReport). Name is derived from LOG_FILENAME so it stays in
# sync automatically across the base/agentic/CALLER_MODE log variants without
# needing a second env var wired through the RF Process call.
if LOG_FILENAME.endswith(".jsonl"):
    FILTERED_LOG_FILENAME = LOG_FILENAME[: -len(".jsonl")] + "_filtered.jsonl"
else:
    FILTERED_LOG_FILENAME = LOG_FILENAME + "_filtered"
FILTERED_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", FILTERED_LOG_FILENAME)

_FILTERED_EVENT_TYPES = {
    "ConversationText",
    "AgentAudioDone",
    "UserStartedSpeaking",
    "FunctionCallRequest",
    "FunctionCallResponse",
}

# Fixed script for CALLER_MODE. Deliberately not LLM-generated -- a real
# LLM-driven caller bot was considered and rejected as non-deterministic
# for a regression test (see project memory). Branching on turn 3 is
# bounded/rule-based (fixed keyword table), not another model, so it's
# still fully reproducible run to run while still adapting to what the
# agent actually said.
_BASE_CALLER_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caller_audio")
_BASE_CALLER_SCRIPT = [
    {"clip": "line1.wav"},
    {"clip": "line2.wav"},
    {
        "branch_on_last_assistant_text": [
            (["salesforce"], "line3_branch_pricing.wav"),
            (["record", "plain english", "started"], "line3_branch_salesforce.wav"),
        ],
        "default_clip": "line3_branch_generic.wav",
    },
    {"clip": "line4_goodbye.wav"},
]

# AGENTIC_MODE's caller: a linear (no branching needed) script describing
# the real known bug in job 197407 -- see resources/caller_audio_agentic/
# and agentic_functions.py's diagnose_and_fix_test_job for the fix logic
# this is meant to trigger.
_AGENTIC_CALLER_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caller_audio_agentic")
_AGENTIC_CALLER_SCRIPT = [
    {"clip": "line1.wav"},
    {"clip": "line2.wav"},
    {"clip": "line3.wav"},
]

CALLER_AUDIO_DIR = _AGENTIC_CALLER_AUDIO_DIR if AGENTIC_MODE else _BASE_CALLER_AUDIO_DIR
CALLER_SCRIPT = _AGENTIC_CALLER_SCRIPT if AGENTIC_MODE else _BASE_CALLER_SCRIPT

app = Flask(__name__)
sock = Sock(app)

_clip_cache = {}


# Truncated once per process start (not per-call) -- confirmed live 2026-08-13
# that leaving this file to accumulate across runs made an old run's
# leftover transcript look like it belonged to a call that actually failed
# before ever reaching the bridge (Twilio declined it with a 502 fetching
# /voice, confirmed via Twilio's own Monitor alert -- see project memory).
with open(LOG_PATH, "w"):
    pass
with open(FILTERED_LOG_PATH, "w"):
    pass


def _log_event(event_text):
    """Appends to the full raw event log (unchanged, everything the process
    sends or receives), and -- if this event's "type" is one worth reading
    (see _FILTERED_EVENT_TYPES) -- also appends the same line to the smaller
    filtered log. Called for both inbound Deepgram events and outbound
    FunctionCallResponse messages, so both logs stay in sync."""
    clean_text = event_text.rstrip("\n") + "\n"
    with open(LOG_PATH, "a") as f:
        f.write(clean_text)
    try:
        event_type = json.loads(event_text).get("type")
    except ValueError:
        event_type = None
    if event_type in _FILTERED_EVENT_TYPES:
        with open(FILTERED_LOG_PATH, "a") as f:
            f.write(clean_text)


def _wav_to_mulaw_bytes(wav_path):
    with wave.open(wav_path, "rb") as w:
        assert w.getframerate() == 8000, f"{wav_path} must be 8kHz, got {w.getframerate()}"
        assert w.getsampwidth() == 2, f"{wav_path} must be 16-bit PCM"
        assert w.getnchannels() == 1, f"{wav_path} must be mono"
        pcm_frames = w.readframes(w.getnframes())
    return audioop.lin2ulaw(pcm_frames, 2)


def _load_clip_mulaw(filename):
    """Fixes CRT's base64 resource mangling (same bug/fix as
    prepare_cloudflared, generalized -- see crt_voice_poc_vm_gotchas
    memory) then converts to raw mulaw, caching per-process since these
    clips are static for the life of one call."""
    if filename not in _clip_cache:
        bundled_path = os.path.join(CALLER_AUDIO_DIR, filename)
        usable_path = prepare_binary_resource(bundled_path, b"RIFF", f"caller_{filename}")
        _clip_cache[filename] = _wav_to_mulaw_bytes(usable_path)
    return _clip_cache[filename]


def _select_clip_for_turn(turn_index, last_assistant_text):
    turn = CALLER_SCRIPT[turn_index]
    if "clip" in turn:
        return turn["clip"]
    text_lower = (last_assistant_text or "").lower()
    for keywords, clip in turn["branch_on_last_assistant_text"]:
        if any(kw in text_lower for kw in keywords):
            return clip
    return turn["default_clip"]


def _end_call(call_sid):
    if not call_sid:
        print("CALLER_MODE script complete but no call_sid was captured -- can't hang up via API")
        return
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        print("CALLER_MODE script complete but no Twilio credentials in env -- can't hang up via API")
        return
    try:
        Client(account_sid, auth_token).calls(call_sid).update(status="completed")
        print(f"CALLER_MODE script complete -- ended call {call_sid}")
    except Exception as e:
        # Confirmed live 2026-08-13: both the grace-period timer (see
        # GRACE_HANGUP_SECONDS) and a genuine final AgentAudioDone can each
        # try to end the same call -- Twilio rejects updating an
        # already-completed call's status, which is fine, not a real
        # failure; just don't let it look like an unhandled crash.
        print(f"CALLER_MODE: end_call for {call_sid} failed (likely already ended): {e}")


def _identify_caller_and_open_case(call_sid, state):
    """Runs in a background thread right after the Twilio 'start' event
    (AGENTIC_MODE only). Fetches the real caller number from the Twilio
    Call resource (not the transcript -- deterministic, available the
    moment the call exists), matches it to a Contact, and opens a real
    Salesforce Case. Real side effects with real CreatedDate/
    LastModifiedDate timestamps -- validation cross-references those
    against the call's own start/end window rather than needing to watch
    the conversation live (see project_agentforce_voice_agentic memory)."""
    try:
        account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        auth_token = os.environ["TWILIO_AUTH_TOKEN"]
        call = Client(account_sid, auth_token).calls(call_sid).fetch()
        caller_number = call._from
        contact = sf_client.find_contact_by_phone(caller_number)
        if contact:
            subject = f"Support call from {contact['Name']} ({caller_number})"
            description = f"Inbound support call in progress. Caller matched to contact {contact['Id']}."
        else:
            subject = f"Support call from unrecognized number {caller_number}"
            description = "Inbound support call in progress. No matching Contact found for this phone number."
        case_id = sf_client.create_case(
            subject=subject, description=description,
            contact_id=contact["Id"] if contact else None,
            status="New", origin="Phone",
        )
        state["case_id"] = case_id
        state["contact"] = contact
        print(f"AGENTIC_MODE: opened Case {case_id} for caller {caller_number} "
              f"(contact: {contact['Id'] if contact else 'none matched'})", flush=True)
    except Exception:
        import traceback
        print("AGENTIC_MODE: _identify_caller_and_open_case failed:", flush=True)
        traceback.print_exc()
        sys.stdout.flush()


def _handle_function_call(dg_ws, event, state, send_lock):
    """A single FunctionCallRequest event batches one or more calls in
    its "functions" array (real schema confirmed 2026-08-17 from the
    Deepgram Python SDK's generated types, agent_v1function_call_request*
    .py -- NOT the flat function_name/function_call_id/input shape an
    earlier, wrong version of this handler used, copied from a stale
    community reference repo. That mismatch caused every call to dispatch
    as function "None" and sent back a response Deepgram couldn't
    correlate, stalling the session -- see
    reference_deepgram_voice_agent_functions memory). Each call gets its
    own FunctionCallResponse: {type, id, name, content} -- "content" is a
    plain string, "id" must echo the request's id for correlation,
    "arguments" arrives as a JSON string, not a dict."""
    for call in event.get("functions", []):
        call_id = call.get("id")
        function_name = call.get("name")
        try:
            params = json.loads(call.get("arguments") or "{}")
        except ValueError:
            params = {}
        print(f"AGENTIC_MODE: function call {function_name}({params})", flush=True)
        handler = agentic_functions.FUNCTION_MAP.get(function_name)
        if handler is None:
            result = {"error": f"Unknown function {function_name}"}
        else:
            try:
                result = handler(params, state)
            except Exception as e:
                import traceback
                traceback.print_exc()
                result = {"error": f"{e.__class__.__name__}: {e}"}
        response = {
            "type": "FunctionCallResponse",
            "id": call_id,
            "name": function_name,
            "content": json.dumps(result),
        }
        with send_lock:
            dg_ws.send(json.dumps(response))
        _log_event(json.dumps(response))
        print(f"AGENTIC_MODE: function response for {function_name}: {result}", flush=True)


def _send_audio_realtime(dg_ws, audio_bytes, send_lock, chunk_bytes=160, chunk_seconds=0.02):
    """Sends mulaw audio to Deepgram paced out like real-time speech --
    small chunks (160 bytes = 20ms at 8kHz mulaw, matching Deepgram's own
    documented guidance) with a real-time delay between them -- instead
    of one instantaneous blob. Confirmed live 2026-08-13: sending a whole
    clip as a single WebSocket binary message caused Deepgram's
    turn-detection to register only the very start as a complete
    utterance (a multi-second line transcribed as just "Hi."), then
    CLIENT_MESSAGE_TIMEOUT once nothing more arrived -- since everything
    had already been sent in one shot. Deepgram's docs confirm audio is
    expected as a continuous, realistically-paced stream, not a blob.

    send_lock serializes access to dg_ws.send() against the KeepAlive
    thread (see _keepalive_loop) -- websocket-client's WebSocket isn't
    documented as safe for concurrent sends from multiple threads, and
    interleaving a KeepAlive text frame between binary audio chunks could
    corrupt the stream.
    """
    for i in range(0, len(audio_bytes), chunk_bytes):
        with send_lock:
            dg_ws.send(audio_bytes[i:i + chunk_bytes], opcode=websocket.ABNF.OPCODE_BINARY)
        time.sleep(chunk_seconds)


SILENCE_PAD_SECONDS = 1.5
GRACE_HANGUP_SECONDS = 6
# How long to wait, quiet, after the agent's most recent AgentAudioDone before
# actually injecting the next scripted caller line. Confirmed live 2026-08-18:
# advancing immediately on AgentAudioDone is unsafe -- a quick filler
# utterance ("Got it!") generates its own AgentAudioDone before the agent's
# FunctionCallRequest even shows up in the event stream, so an immediate
# advance can inject caller audio mid-tool-call (Deepgram then reports the
# call CANCELLED in its own turn history, even though our backend keeps
# running it for real -- see project memory). The agent can also speak
# multiple separate audio bursts (multiple AgentAudioDone events) after a
# single tool call finishes, so the fix isn't just "wait for no function call
# in flight" -- it's debouncing on AgentAudioDone itself: only advance once
# nothing else (another AgentAudioDone or a FunctionCallRequest) has happened
# for this whole window.
CALLER_ADVANCE_DEBOUNCE_SECONDS = 1.5
_silence_pad_cache = None


def _silence_mulaw(seconds, sample_rate=8000):
    """Real mu-law silence bytes (via audioop, same codec path as the real
    clips), not a text KeepAlive -- see _keepalive_loop docstring for why
    those are different problems. Confirmed live 2026-08-13: a clip
    ("Hi, can you tell me what Copado Robotic Testing actually does")
    was getting split by Deepgram's turn-detection into two utterances at
    the natural pause after "Hi," -- it committed "Hi." as a complete
    turn, started generating a reply, then heard the rest of the sentence
    arriving and treated it as a barge-in, canceling the reply. That
    second utterance then never finalized, because our stream stopped
    dead the instant the clip ended -- no trailing silence to signal
    "user is done talking." In a real Twilio call, audio streams
    continuously (silence included) for the entire call, which is what
    normally gives Deepgram's VAD that signal; CALLER_MODE has no such
    continuous stream, so it has to fake the trailing silence explicitly.
    """
    global _silence_pad_cache
    if _silence_pad_cache is None:
        pcm_zeros = b"\x00\x00" * int(seconds * sample_rate)
        _silence_pad_cache = audioop.lin2ulaw(pcm_zeros, 2)
    return _silence_pad_cache


def _advance_caller_script(dg_ws, state, send_lock):
    idx = state["next_turn_index"]
    if idx >= len(CALLER_SCRIPT):
        _end_call(state.get("call_sid"))
        return
    clip_name = _select_clip_for_turn(idx, state.get("last_assistant_text"))
    audio = _load_clip_mulaw(clip_name)
    _send_audio_realtime(dg_ws, audio, send_lock)
    _send_audio_realtime(dg_ws, _silence_mulaw(SILENCE_PAD_SECONDS), send_lock)
    print(
        f"CALLER_MODE: injected turn {idx} -> {clip_name} "
        f"({len(audio)} bytes, paced) + {SILENCE_PAD_SECONDS}s silence pad",
        flush=True,
    )
    state["next_turn_index"] = idx + 1
    if state["next_turn_index"] >= len(CALLER_SCRIPT):
        # Confirmed live 2026-08-13: hanging up used to wait for one more
        # AgentAudioDone after the script's last line, but a closing line
        # that isn't a direct reply to the agent's own prior question
        # (e.g. the caller says goodbye without the agent ever asking "is
        # there anything else?") can leave the agent with no further
        # reply queued at all -- no ConversationText, no AgentAudioDone,
        # ever. The call would then sit open indefinitely with nothing
        # left to advance it. Give the agent a grace window to speak a
        # farewell if it has one ready, then hang up regardless -- this
        # mirrors a real caller who says goodbye and hangs up rather than
        # waiting forever for a reply that may never come.
        timer = threading.Timer(GRACE_HANGUP_SECONDS, _end_call, args=(state.get("call_sid"),))
        timer.daemon = True
        timer.start()


def _run_advance_safely(dg_ws, state, send_lock):
    """_advance_caller_script now runs on a Timer thread instead of the relay
    thread -- an uncaught exception there won't hit the relay loop's own
    try/except at all, so this wraps it with the same flush-on-failure
    diagnostic behavior (see the confirmed-live-2026-08-13 comment at the
    AgentAudioDone handler) so a failure here doesn't go unseen."""
    try:
        _advance_caller_script(dg_ws, state, send_lock)
    except Exception:
        import traceback
        print("CALLER_MODE: _advance_caller_script failed:", flush=True)
        traceback.print_exc()
        import sys as _sys
        _sys.stdout.flush()
        _sys.stderr.flush()


def _schedule_caller_advance(dg_ws, state, send_lock):
    """Debounced replacement for calling _advance_caller_script directly on
    every AgentAudioDone. Cancels whatever advance timer is already pending
    (if any) and starts a fresh one -- so the next caller line only actually
    plays once CALLER_ADVANCE_DEBOUNCE_SECONDS pass with no further
    AgentAudioDone AND no FunctionCallRequest arriving in between. Runs on a
    Timer thread, not the relay thread, so _advance_caller_script's own
    dg_ws.send calls go through send_lock like every other sender here."""
    existing = state.get("advance_timer")
    if existing is not None:
        existing.cancel()
    timer = threading.Timer(
        CALLER_ADVANCE_DEBOUNCE_SECONDS, _run_advance_safely, args=(dg_ws, state, send_lock)
    )
    timer.daemon = True
    state["advance_timer"] = timer
    timer.start()


def _cancel_pending_caller_advance(state):
    """Called when a FunctionCallRequest arrives -- a pending debounced
    advance (scheduled off an earlier filler-utterance AgentAudioDone) must
    not fire while/just as a real tool call is starting."""
    existing = state.get("advance_timer")
    if existing is not None:
        existing.cancel()
        state["advance_timer"] = None


def _keepalive_loop(dg_ws, send_lock, stop_event, interval_seconds=5):
    """CALLER_MODE has no continuous audio source -- unlike the real
    Twilio media stream (which sends silence-filled frames every 20ms for
    the whole call, keeping Deepgram's connection alive by default), this
    bridge only sends bytes in short bursts once per turn, then goes
    completely silent while waiting for the agent to respond. Confirmed
    live 2026-08-13 (Deepgram's own docs, developers.deepgram.com/docs/
    agent-keep-alive): "The server closes connections that go silent" --
    exactly the CLIENT_MESSAGE_TIMEOUT ("We waited too long for a
    websocket message") seen right after a caller line finished sending
    and the agent hadn't replied yet. Docs specify sending one KeepAlive
    every 8s during silence; 5s here for margin. The server sends no
    response to it, and it doesn't extend the 2-hour session cap.
    """
    while not stop_event.wait(interval_seconds):
        try:
            with send_lock:
                dg_ws.send(json.dumps({"type": "KeepAlive"}))
        except Exception:
            break


@app.route("/health", methods=["GET"])
def health():
    """Lets a caller confirm the full chain (cloudflared edge -> tunnel ->
    this Flask process) is actually reachable before relying on it --
    confirmed live 2026-08-13 that a tunnel can report itself connected in
    its own logs while the very first real proxied request still 502s
    (Twilio's Monitor alerts showed error 11200 fetching /voice at the
    exact moment the automated call was placed). See tunnel_helper.
    wait_for_bridge_ready, used to poll this before Set Number Voice Url."""
    return "ok", 200


@app.route("/voice", methods=["POST"])
def voice():
    host = request.host
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<Stream url="wss://{host}/media-stream" />'
        "</Connect></Response>"
    ), 200, {"Content-Type": "text/xml"}


@sock.route("/media-stream")
def media_stream(ws):
    api_key = os.environ["DEEPGRAM_API_KEY"]
    dg_ws = websocket.create_connection(DEEPGRAM_AGENT_URL, subprotocols=["token", api_key])
    dg_ws.send(json.dumps(_build_settings_message()))

    state = {
        "stream_sid": None,
        "call_sid": None,
        "next_turn_index": 0,
        "last_assistant_text": None,
        "case_id": None,
        "contact": None,
        "advance_timer": None,
    }
    stop_event = threading.Event()
    dg_send_lock = threading.Lock()

    def relay_from_deepgram():
        while not stop_event.is_set():
            try:
                message = dg_ws.recv()
            except Exception:
                break
            if message is None:
                break
            if isinstance(message, (bytes, bytearray)):
                if state["stream_sid"]:
                    payload = base64.b64encode(message).decode("ascii")
                    ws.send(json.dumps({
                        "event": "media",
                        "streamSid": state["stream_sid"],
                        "media": {"payload": payload},
                    }))
            else:
                _log_event(message)
                try:
                    event = json.loads(message)
                except ValueError:
                    event = {}
                event_type = event.get("type")
                if event_type == "UserStartedSpeaking" and state["stream_sid"]:
                    ws.send(json.dumps({"event": "clear", "streamSid": state["stream_sid"]}))
                elif event_type == "ConversationText" and event.get("role") == "assistant":
                    state["last_assistant_text"] = event.get("content", "")
                elif event_type == "FunctionCallRequest" and AGENTIC_MODE:
                    # A caller-script advance may already be pending from an
                    # earlier filler-utterance AgentAudioDone -- see
                    # CALLER_ADVANCE_DEBOUNCE_SECONDS. Cancel it before this
                    # real tool call starts, not after, so it can't fire
                    # mid-call.
                    if CALLER_MODE:
                        _cancel_pending_caller_advance(state)
                    _handle_function_call(dg_ws, event, state, dg_send_lock)
                elif event_type == "AgentAudioDone" and CALLER_MODE:
                    try:
                        _schedule_caller_advance(dg_ws, state, dg_send_lock)
                    except Exception:
                        # Confirmed live 2026-08-13: an exception here used to
                        # silently kill this daemon thread with no traceback
                        # (this call sat outside the try/except that only
                        # wraps dg_ws.recv()), leaving a call that looked
                        # "stuck after the greeting" with zero diagnostic
                        # signal. Print with flush -- stdout is block-buffered
                        # when redirected to a file via Process/subprocess, so
                        # without flush=True this could sit unseen until exit.
                        import traceback
                        print("CALLER_MODE: _schedule_caller_advance failed:", flush=True)
                        traceback.print_exc()
                        import sys as _sys
                        _sys.stdout.flush()
                        _sys.stderr.flush()

    relay_thread = threading.Thread(target=relay_from_deepgram, daemon=True)
    relay_thread.start()

    if CALLER_MODE:
        keepalive_thread = threading.Thread(
            target=_keepalive_loop, args=(dg_ws, dg_send_lock, stop_event), daemon=True
        )
        keepalive_thread.start()

    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            msg = json.loads(raw)
            event = msg.get("event")
            if event == "start":
                state["stream_sid"] = msg["start"]["streamSid"]
                state["call_sid"] = msg["start"].get("callSid")
                if AGENTIC_MODE and state["call_sid"]:
                    threading.Thread(
                        target=_identify_caller_and_open_case,
                        args=(state["call_sid"], state),
                        daemon=True,
                    ).start()
            elif event == "media":
                if not CALLER_MODE:
                    audio_bytes = base64.b64decode(msg["media"]["payload"])
                    dg_ws.send(audio_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
            elif event == "stop":
                break
    finally:
        stop_event.set()
        try:
            dg_ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
