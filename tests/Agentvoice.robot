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
    Sleep    5s
    ${tunnel_output}=    Get File    ${cwd}/tunnel_err.log
    ${tunnel_url}=    Extract Tunnel Url    ${tunnel_output}
    ${voice_url}=    Catenate    SEPARATOR=    ${tunnel_url}    /voice
    Log To Console    Voice webhook: ${voice_url}
    ${call_sid}=    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${TWILIO_CALLER_NUMBER}    ${voice_url}
    Log To Console    Call is live -- answer your phone and talk to the agent. SID: ${call_sid}
    Sleep    120s
    Log File If Exists    ${cwd}/conversation_log.jsonl    Conversation transcript
    Log File If Exists    ${cwd}/bridge_err.log    Bridge stderr
    Log File If Exists    ${cwd}/bridge.log    Bridge stdout
    Log File If Exists    ${cwd}/tunnel_err.log    Tunnel stderr (final state)

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