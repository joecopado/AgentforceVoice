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
    ${cloudflared_path}=    Prepare Cloudflared
    ${bridge_process}=    Start Process
    ...    python3 ${CURDIR}/../resources/voice_agent_bridge.py > ${CURDIR}/bridge.log 2> ${CURDIR}/bridge_err.log
    ...    shell=True    env:DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}    cwd=${CURDIR}
    Sleep    3s
    ${tunnel_process}=    Start Process
    ...    ${cloudflared_path} tunnel --url http://localhost:5000 > ${CURDIR}/tunnel.log 2> ${CURDIR}/tunnel_err.log
    ...    shell=True    cwd=${CURDIR}
    Sleep    5s
    ${tunnel_output}=    Get File    ${CURDIR}/tunnel_err.log
    ${tunnel_url}=    Extract Tunnel Url    ${tunnel_output}
    ${voice_url}=    Catenate    SEPARATOR=    ${tunnel_url}    /voice
    Log To Console    Voice webhook: ${voice_url}
    ${call_sid}=    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${TWILIO_CALLER_NUMBER}    ${voice_url}
    Log To Console    Call is live -- answer your phone and talk to the agent. SID: ${call_sid}
    Sleep    120s
    ${log_exists}=    Run Keyword And Return Status    File Should Exist    ${CURDIR}/conversation_log.jsonl
    IF    ${log_exists}
        ${transcript}=    Get File    ${CURDIR}/conversation_log.jsonl
        Log To Console    ${transcript}
    ELSE
        Log To Console    No conversation_log.jsonl found -- check bridge_err.log for a bridge-side failure.
    END

*** Keywords ***
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