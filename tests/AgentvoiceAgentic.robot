*** Settings ***
Library           QForce
Resource          ../resources/common.robot
Suite Setup       Setup Browser
Suite Teardown    End suite
Library    ../resources/vm_check.py
Library    ../resources/call_harness.py
Library    ../resources/tunnel_helper.py


*** Test Cases ***
Talk To Agentic Voice Agent
    [Documentation]    Same shape as "Talk To Voice Agent" in Agentvoice.robot,
    ...    but AGENTIC_MODE=1 instead of plain conversation -- the agent can
    ...    create/update a real Salesforce Case and diagnose/fix a real CRT
    ...    test job via the PACE API mid-call, on top of talking. See
    ...    project_agentforce_voice_agentic memory for the full design.
    ...
    ...    Uses a NAMED Cloudflare Tunnel (fixed hostname
    ...    voice-bridge.copadojgcrt.us, tunnel "agentforce-voice-poc") via a
    ...    TUNNEL_TOKEN vault variable, instead of a throwaway quick tunnel
    ...    -- quick tunnels mint a brand-new random subdomain every run,
    ...    which hit DNS-propagation flakiness on two independent networks
    ...    the same night this was built (see reference_pace_api /
    ...    project_agentforce_voice_agentic memory). A token-based named
    ...    tunnel needs no cert.pem/credentials.json on the VM at all --
    ...    just the cloudflared binary (already handled by Prepare
    ...    Cloudflared) plus this one secret string.
    [Teardown]    Run Keywords
    ...    Cleanup Background Processes    ${bridge_process}    ${tunnel_process}    AND
    ...    End Call If Active    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    ${bridge_process}=    Set Variable    ${EMPTY}
    ${tunnel_process}=    Set Variable    ${EMPTY}
    ${call_sid}=    Set Variable    ${EMPTY}
    ${cwd}=    Get Working Directory
    ${cloudflared_path}=    Prepare Cloudflared
    ${bridge_process}=    Start Process
    ...    /usr/bin/python3.11 ${cwd}/../resources/voice_agent_bridge.py > ${cwd}/agentic_bridge.log 2> ${cwd}/agentic_bridge_err.log
    ...    shell=True    cwd=${cwd}
    ...    env:DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}    env:AGENTIC_MODE=1
    ...    env:SF_ACCESS_TOKEN=${TOKEN}    env:SF_INSTANCE_URL=${login_url}
    ...    env:PACE_API_KEY=${PACE_API_KEY}
    Sleep    3s
    ${tunnel_process}=    Start Process
    ...    ${cloudflared_path} tunnel run --token ${TUNNEL_TOKEN} --url http://localhost:5000 > ${cwd}/agentic_tunnel.log 2> ${cwd}/agentic_tunnel_err.log
    ...    shell=True    cwd=${cwd}
    ${voice_url}=    Set Variable    https://voice-bridge.copadojgcrt.us/voice
    Log To Console    Voice webhook: ${voice_url}
    # REQUIRED: a tunnel connecting does NOT mean the full chain is reachable
    # yet -- see Wait For Bridge Ready's own docstring / project memory.
    Wait For Bridge Ready    https://voice-bridge.copadojgcrt.us
    ${call_sid}=    Place Verification Call    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${TWILIO_CALLER_NUMBER}    ${voice_url}
    Log To Console    Call is live -- answer your phone and talk to the agent. SID: ${call_sid}
    ${final_status}=    Wait For Call Completion    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    Log To Console    Call ended with status: ${final_status}
    Log File If Exists    ${cwd}/conversation_log.jsonl    Conversation transcript
    Log File If Exists    ${cwd}/agentic_bridge_err.log    Bridge stderr
    Log File If Exists    ${cwd}/agentic_bridge.log    Bridge stdout
    Log File If Exists    ${cwd}/agentic_tunnel_err.log    Tunnel stderr (final state)

Automated Agentic Voice Agent Conversation
    [Documentation]    Same shape as "Automated Voice Agent Conversation" in
    ...    Agentvoice.robot, but with AGENTIC_MODE=1 as well as CALLER_MODE=1
    ...    -- a fixed, scripted caller (resources/caller_audio_agentic/)
    ...    describes the known CRT test bug (job 197407's missing Suite
    ...    Setup), while the agent identifies the caller by phone against a
    ...    Salesforce Contact, opens a real Case, diagnoses/fixes the bug via
    ...    the PACE API, and updates the Case before hanging up -- no human
    ...    involved. Requires a Contact in the target org whose Phone field
    ...    matches TWILIO_AGENT_NUMBER2 (used here as the caller-ID) --
    ...    "CRT Test Caller" was created for this purpose 2026-08-17.
    ...
    ...    Same Twilio-owned-destination-number requirements as the base
    ...    Automated Voice Agent Conversation test: TWILIO_AGENT_NUMBER's own
    ...    "A call comes in" webhook must be set to this run's URL before
    ...    placing the call (Set Number Voice Url), and the outbound leg uses
    ...    a passive TwiML (Place Call To Configured Number), not the bridge
    ...    URL again -- see that test's own [Documentation] / project memory
    ...    for why (duplicated-session bug if both legs run the real bridge).
    [Teardown]    Run Keywords
    ...    Cleanup Background Processes    ${bridge_process}    ${tunnel_process}    AND
    ...    End Call If Active    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    ${bridge_process}=    Set Variable    ${EMPTY}
    ${tunnel_process}=    Set Variable    ${EMPTY}
    ${call_sid}=    Set Variable    ${EMPTY}
    ${cwd}=    Get Working Directory
    ${cloudflared_path}=    Prepare Cloudflared
    ${bridge_process}=    Start Process
    ...    /usr/bin/python3.11 ${cwd}/../resources/voice_agent_bridge.py > ${cwd}/auto_agentic_bridge.log 2> ${cwd}/auto_agentic_bridge_err.log
    ...    shell=True    cwd=${cwd}
    ...    env:DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}    env:TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}
    ...    env:TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}    env:CALLER_MODE=1    env:AGENTIC_MODE=1
    ...    env:SF_ACCESS_TOKEN=${TOKEN}    env:SF_INSTANCE_URL=${login_url}
    ...    env:PACE_API_KEY=${PACE_API_KEY}
    ...    env:LOG_FILENAME=automated_agentic_conversation_log.jsonl
    Sleep    3s
    ${tunnel_process}=    Start Process
    ...    ${cloudflared_path} tunnel run --token ${TUNNEL_TOKEN} --url http://localhost:5000 > ${cwd}/auto_agentic_tunnel.log 2> ${cwd}/auto_agentic_tunnel_err.log
    ...    shell=True    cwd=${cwd}
    ${voice_url}=    Set Variable    https://voice-bridge.copadojgcrt.us/voice
    Log To Console    Voice webhook: ${voice_url}
    Wait For Bridge Ready    https://voice-bridge.copadojgcrt.us
    Set Number Voice Url    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${voice_url}
    ${call_sid}=    Place Call To Configured Number    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${TWILIO_AGENT_NUMBER}    ${TWILIO_AGENT_NUMBER2}
    Log To Console    Automated call is live, no human needed. SID: ${call_sid}
    ${final_status}=    Wait For Call Completion    ${TWILIO_ACCOUNT_SID}    ${TWILIO_AUTH_TOKEN}    ${call_sid}
    Log To Console    Call ended with status: ${final_status}
    Log File If Exists    ${cwd}/automated_agentic_conversation_log.jsonl    Automated agentic conversation transcript
    Log File If Exists    ${cwd}/auto_agentic_bridge_err.log    Bridge stderr
    Log File If Exists    ${cwd}/auto_agentic_bridge.log    Bridge stdout
    Log File If Exists    ${cwd}/auto_agentic_tunnel_err.log    Tunnel stderr (final state)

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
