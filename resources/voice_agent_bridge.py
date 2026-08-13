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

DEEPGRAM_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"
PORT = int(os.environ.get("PORT", "5000"))
CALLER_MODE = bool(os.environ.get("CALLER_MODE", ""))
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

SETTINGS_MESSAGE = {
    "type": "Settings",
    "audio": {
        "input": {"encoding": "mulaw", "sample_rate": 8000},
        "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"},
    },
    "agent": {
        "language": "en",
        "listen": {"provider": {"type": "deepgram", "model": "nova-3"}},
        "think": {
            "provider": {"type": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.5},
            "prompt": AGENT_SYSTEM_PROMPT,
        },
        "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
        "greeting": "Hi there! Thanks for calling Copado Robotic Testing support -- how can I help today?",
    },
}

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", LOG_FILENAME)

# Fixed script for CALLER_MODE. Deliberately not LLM-generated -- a real
# LLM-driven caller bot was considered and rejected as non-deterministic
# for a regression test (see project memory). Branching on turn 3 is
# bounded/rule-based (fixed keyword table), not another model, so it's
# still fully reproducible run to run while still adapting to what the
# agent actually said.
CALLER_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caller_audio")
CALLER_SCRIPT = [
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

app = Flask(__name__)
sock = Sock(app)

_clip_cache = {}


def _log_event(event_text):
    with open(LOG_PATH, "a") as f:
        f.write(event_text.rstrip("\n") + "\n")


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
    Client(account_sid, auth_token).calls(call_sid).update(status="completed")
    print(f"CALLER_MODE script complete -- ended call {call_sid}")


def _send_audio_realtime(dg_ws, audio_bytes, chunk_bytes=160, chunk_seconds=0.02):
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
    """
    for i in range(0, len(audio_bytes), chunk_bytes):
        dg_ws.send(audio_bytes[i:i + chunk_bytes], opcode=websocket.ABNF.OPCODE_BINARY)
        time.sleep(chunk_seconds)


def _advance_caller_script(dg_ws, state):
    idx = state["next_turn_index"]
    if idx >= len(CALLER_SCRIPT):
        _end_call(state.get("call_sid"))
        return
    clip_name = _select_clip_for_turn(idx, state.get("last_assistant_text"))
    audio = _load_clip_mulaw(clip_name)
    _send_audio_realtime(dg_ws, audio)
    print(f"CALLER_MODE: injected turn {idx} -> {clip_name} ({len(audio)} bytes, paced)")
    state["next_turn_index"] = idx + 1


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
    dg_ws.send(json.dumps(SETTINGS_MESSAGE))

    state = {
        "stream_sid": None,
        "call_sid": None,
        "next_turn_index": 0,
        "last_assistant_text": None,
    }
    stop_event = threading.Event()

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
                elif event_type == "AgentAudioDone" and CALLER_MODE:
                    _advance_caller_script(dg_ws, state)

    relay_thread = threading.Thread(target=relay_from_deepgram, daemon=True)
    relay_thread.start()

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
