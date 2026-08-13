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
"""
import base64
import json
import os
import threading

import websocket
from flask import Flask, request
from flask_sock import Sock

DEEPGRAM_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"
PORT = 5000

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

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "conversation_log.jsonl")

app = Flask(__name__)
sock = Sock(app)


def _log_event(event_text):
    with open(LOG_PATH, "a") as f:
        f.write(event_text.rstrip("\n") + "\n")


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

    state = {"stream_sid": None}
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
                if event.get("type") == "UserStartedSpeaking" and state["stream_sid"]:
                    ws.send(json.dumps({"event": "clear", "streamSid": state["stream_sid"]}))

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
            elif event == "media":
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
