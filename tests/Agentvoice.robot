*** Settings ***
Library           QForce
Resource          ../resources/common.robot
Suite Setup       Setup Browser
Suite Teardown    End suite
Library    ../resources/vm_check.py
Library    ../resources/call_harness.py
Library    ../resources/tunnel_helper.py


*** Test Cases ***
Test
    ${report}=    Run Vm Check
    Log To Console    ${report}
    GoTo                    file:///home/services/suite/resources/bin/
    ${call_sid}=    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${TWILIO_CALLER_NUMBER}    ${TWILIO_AGENT_TWIML_URL}
    Log To Console    ${call_sid}
    Sleep    20s
    ${call_status}=    Get Call Status    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    Log To Console    ${call_status}

Talk To Voice Agent
    [Documentation]    Starts the Deepgram Voice Agent bridge + a cloudflared
    ...    tunnel as background processes, places a real call from the agent
    ...    number to the user's cell with the tunnel's /voice endpoint as the
    ...    TwiML url, so answering the call connects to a live Claude-powered
    ...    voice agent. Tears down both background processes afterward, and
    ...    ends the call itself if it's somehow still active -- killing the
    ...    local bridge process does NOT hang up the actual Twilio call.
    [Teardown]    Run Keywords
    ...    Cleanup Background Processes    ${bridge_process}    ${tunnel_process}    AND
    ...    End Call If Active    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    ${bridge_process}=    Set Variable    ${EMPTY}
    ${tunnel_process}=    Set Variable    ${EMPTY}
    ${call_sid}=    Set Variable    ${EMPTY}
    ${cwd}=    Get Working Directory
    ${cloudflared_path}=    Prepare Cloudflared
    ${bridge_process}=    Start Process
    ...    /usr/bin/python3.11 ${cwd}/../resources/voice_agent_bridge.py > ${cwd}/bridge.log 2> ${cwd}/bridge_err.log
    ...    shell=True    env:DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}    cwd=${cwd}
    Sleep    3s
    ${tunnel_process}=    Start Process
    ...    ${cloudflared_path} tunnel --url http://localhost:5000 > ${cwd}/tunnel.log 2> ${cwd}/tunnel_err.log
    ...    shell=True    cwd=${cwd}
    ${tunnel_url}=    Wait For Tunnel Url    ${cwd}/tunnel_err.log
    ${voice_url}=    Catenate    SEPARATOR=    ${tunnel_url}    /voice
    Log To Console    Voice webhook: ${voice_url}
    ${call_sid}=    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${TWILIO_CALLER_NUMBER}    ${voice_url}
    Log To Console    Call is live -- answer your phone and talk to the agent. SID: ${call_sid}
    ${final_status}=    Wait For Call Completion    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    Log To Console    Call ended with status: ${final_status}
    Log File If Exists    ${cwd}/conversation_log.jsonl    Conversation transcript
    Log File If Exists    ${cwd}/bridge_err.log    Bridge stderr
    Log File If Exists    ${cwd}/bridge.log    Bridge stdout
    Log File If Exists    ${cwd}/tunnel_err.log    Tunnel stderr (final state)

Automated Voice Agent Conversation
    [Documentation]    No human involved at all. The bridge runs in
    ...    CALLER_MODE: instead of relaying a real human's voice, it
    ...    injects a fixed, pre-recorded script into the same Deepgram
    ...    session on each AgentAudioDone event, with bounded keyword
    ...    branching on the third turn -- deterministic by design (a
    ...    fully LLM-driven caller bot was considered and rejected as
    ...    non-reproducible for a regression test, see project memory).
    ...    The call goes to=TWILIO_AGENT_NUMBER with from=TWILIO_AGENT_NUMBER2
    ...    used as the caller-ID -- the user's real phone never rings.
    ...    REQUIRED: TWILIO_AGENT_NUMBER's own "A call comes in" webhook
    ...    must be set to this run's fresh voice_url before placing the
    ...    call -- confirmed live that a Twilio-owned destination number
    ...    will NOT answer an API-originated call based on that call's own
    ...    url=/application_sid= alone; the destination needs its own
    ...    separate inbound config or it fails instantly (status=failed,
    ...    duration=0, no error anywhere -- cost a very long diagnostic
    ...    session before this was found, see project memory). The bridge
    ...    hangs up the call itself via the Twilio API once the script is
    ...    exhausted, which is why it also needs Twilio credentials, not
    ...    just Deepgram's. Teardown also ends the call itself if it's
    ...    somehow still active, as a safety net independent of the
    ...    bridge's own hangup logic -- see project memory for the real
    ...    incident (a duplication bug) that left a call stuck in-progress
    ...    after its test had already finished and torn down the local
    ...    processes, which does NOT hang up the actual Twilio call.
    [Teardown]    Run Keywords
    ...    Cleanup Background Processes    ${bridge_process}    ${tunnel_process}    AND
    ...    End Call If Active    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    ${bridge_process}=    Set Variable    ${EMPTY}
    ${tunnel_process}=    Set Variable    ${EMPTY}
    ${call_sid}=    Set Variable    ${EMPTY}
    ${cwd}=    Get Working Directory
    ${cloudflared_path}=    Prepare Cloudflared
    ${bridge_process}=    Start Process
    ...    /usr/bin/python3.11 ${cwd}/../resources/voice_agent_bridge.py > ${cwd}/auto_bridge.log 2> ${cwd}/auto_bridge_err.log
    ...    shell=True    cwd=${cwd}
    ...    env:DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}    env:TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}
    ...    env:TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}    env:CALLER_MODE=1
    ...    env:LOG_FILENAME=automated_conversation_log.jsonl
    Sleep    3s
    ${tunnel_process}=    Start Process
    ...    ${cloudflared_path} tunnel --url http://localhost:5000 > ${cwd}/auto_tunnel.log 2> ${cwd}/auto_tunnel_err.log
    ...    shell=True    cwd=${cwd}
    ${tunnel_url}=    Wait For Tunnel Url    ${cwd}/auto_tunnel_err.log
    ${voice_url}=    Catenate    SEPARATOR=    ${tunnel_url}    /voice
    Log To Console    Voice webhook: ${voice_url}
    # REQUIRED: a tunnel URL appearing in cloudflared's own log does NOT
    # mean the full chain is reachable yet -- confirmed live 2026-08-13
    # that a call placed right after that point got an instant Twilio
    # decline (502 fetching /voice, see [Documentation] and project memory).
    Wait For Bridge Ready    ${tunnel_url}
    # REQUIRED: without this, the call fails instantly -- see [Documentation].
    Set Number Voice Url    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${voice_url}
    # Uses a passive inline TwiML for the outbound leg itself (NOT the bridge
    # URL again) -- passing the same bridge url= on both the outbound call
    # and the destination's voice_url caused Twilio to run the full bridge
    # independently on both legs (confirmed live: duplicated transcript
    # events, duplicated /voice hits). Twilio bridges the two legs' real
    # audio together at the platform level regardless, so only the
    # destination's own voice_url (already set above) needs to run it.
    ${call_sid}=    Place Call To Configured Number    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${TWILIO_AGENT_NUMBER2}
    Log To Console    Automated call is live, no human needed. SID: ${call_sid}
    ${final_status}=    Wait For Call Completion    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    Log To Console    Call ended with status: ${final_status}
    Log File If Exists    ${cwd}/automated_conversation_log.jsonl    Automated conversation transcript
    Log File If Exists    ${cwd}/auto_bridge_err.log    Bridge stderr
    Log File If Exists    ${cwd}/auto_bridge.log    Bridge stdout
    Log File If Exists    ${cwd}/auto_tunnel_err.log    Tunnel stderr (final state)
    Cleanup Background Processes    ${bridge_process}    ${tunnel_process}    
    End Call If Active    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    
*** Keywords ***
Log File If Exists
    [Documentation]    Prints a file's contents to the console with a
    ...    label, or says so if it's missing -- surfaces bridge/tunnel
    ...    diagnostics automatically instead of needing another round
    ...    trip asking the user to go check a file manually.
    [Arguments]    ${path}    ${label}
    ${exists}=    Run Keyword And Return Status    File Should Exist    ${path}
    IF    ${exists}
        ${contents}=    Get File    ${path}
        Log To Console    \n=== ${label} (${path}) ===\n${contents}
    ELSE
        Log To Console    \n=== ${label}: not found at ${path} ===
    END

Cleanup Background Processes
    [Documentation]    Safe even if the test failed before one or both
    ...    processes were started -- ${EMPTY} means "never started."
    [Arguments]    ${bridge_process}    ${tunnel_process}
    IF    "${bridge_process}" != "${EMPTY}"
        Terminate Process    ${bridge_process}
    END
    IF    "${tunnel_process}" != "${EMPTY}"
        Terminate Process    ${tunnel_process}
    END