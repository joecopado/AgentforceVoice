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
    ...    voice agent. Tears down both background processes afterward.
    [Teardown]    Cleanup Background Processes    ${bridge_process}    ${tunnel_process}
    ${bridge_process}=    Set Variable    ${EMPTY}
    ${tunnel_process}=    Set Variable    ${EMPTY}
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
    ...    The call goes to=TWILIO_AGENT_NUMBER (a real Twilio number,
    ...    auto-answers via Twilio's own platform) with
    ...    from=TWILIO_AGENT_NUMBER2 (a second Twilio-owned number) used
    ...    as the caller-ID -- both ends are Twilio-owned, since a real
    ...    live run confirmed calling FROM a verified-but-not-Twilio-owned
    ...    number (a personal cell) TO one of your own Twilio numbers
    ...    fails instantly (status=failed, duration=0, TwiML never even
    ...    fetched) -- likely an anti-fraud restriction on that specific
    ...    call shape, not conclusively confirmed via Twilio's docs but
    ...    strongly evidenced live. The user's real phone never rings
    ...    either way. The bridge hangs up the call itself via the Twilio
    ...    API once the script is exhausted, which is why it also needs
    ...    Twilio credentials, not just Deepgram's.
    [Teardown]    Cleanup Background Processes    ${bridge_process}    ${tunnel_process}
    ${bridge_process}=    Set Variable    ${EMPTY}
    ${tunnel_process}=    Set Variable    ${EMPTY}
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
    # Place Verification Call's (agent_number, caller_number) args map to
    # (from_, to), so this places the call TO TWILIO_AGENT_NUMBER FROM
    # TWILIO_AGENT_NUMBER2 -- both Twilio-owned, see [Documentation] above
    # for why a verified personal cell doesn't work as from_ here.
    ${call_sid}=    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER2}    ${TWILIO_AGENT_NUMBER}    ${voice_url}
    Log To Console    Automated call is live, no human needed. SID: ${call_sid}
    ${final_status}=    Wait For Call Completion    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    Log To Console    Call ended with status: ${final_status}
    Log File If Exists    ${cwd}/automated_conversation_log.jsonl    Automated conversation transcript
    Log File If Exists    ${cwd}/auto_bridge_err.log    Bridge stderr
    Log File If Exists    ${cwd}/auto_bridge.log    Bridge stdout
    Log File If Exists    ${cwd}/auto_tunnel_err.log    Tunnel stderr (final state)

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