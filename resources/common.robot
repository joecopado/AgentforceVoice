*** Settings ***
Library                         QForce
Library                         String
Library                         DateTime
Library                         QWeb
Library                         QVision
Library                         QImage
Library                         RequestsLibrary
Library                         FakerLibrary
Library                         Collections
Library                         JSONLibrary
Library                         OperatingSystem
Library                         CopadoAI
Library                         Process

*** Variables ***
# IMPORTANT: Please read the readme.txt to understand needed variables and how to handle them!!
${BROWSER}                      chrome
${username}                     pace.delivery1@qentinel.com.demonew
${login_url}                    https://qentinel--demonew.my.salesforce.com/            # Salesforce instance. NOTE: Should be overwritten in CRT variables
${home_url}                     ${login_url}/lightning/page/home
${DOWNLOAD_DIR}    ${CURDIR}


*** Keywords ***
Setup Browser
    # Setting search order is not really needed here, but given as an example
    # if you need to use multiple libraries containing keywords with duplicate names
    Set Library Search Order    QForce                      QWeb
 

    Open Browser                about:blank                 ${BROWSER}    
    SetConfig                   LineBreak                   ${EMPTY}
    Evaluate                    random.seed()               random
    SetConfig                   DefaultTimeout              20s
    SetConfig                   Delay                       0.3
    ${token}                    JwtAuthenticate             ${AFclient_id}              ${username}    ${AFPrivate_key}
    Set Suite Variable          ${TOKEN}               ${token}       
    JwtLogin
End suite
    Close All Browsers


Login
    [Documentation]             Login to Salesforce instance. Takes instance_url, username and password as
    ...                         arguments. Uses values given in Copado Robotic Testing's variables section by default.
    JwtAuthenticate    ${CPQclient_id}    ${CPQusername}    ${CPQprivate_key}  
    JwtLogin  

JWT Login As
    [Documentation]             Login to Salesforce instance. Takes instance_url, username and password as
    ...                         arguments. Uses values given in Copado Robotic Testing's variables section by default.
    [Arguments]                 ${persona}
    JwtAuthenticate    ${CPQclient_id}    ${persona}    ${CPQprivate_key}  
    JwtLogin  




Create Govee OpenAPI Session
    ${headers}=                 Create Dictionary           Govee-API-Key=${API_KEY}    Content-Type=application/json
    Create Session              govee_open                  ${OPEN_URL}                 headers=${headers}          verify=True

Set Curtain Power State
    [Arguments]                 ${turn_on}
    ${capability}=              Create Dictionary           type=devices.capabilities.on_off                        instance=powerSwitch        value=${turn_on}
    ${payload}=                 Create Dictionary           sku=${MODEL}                device=${DEVICE_MAC}        capability=${capability}
    ${body}=                    Create Dictionary           requestId=crt_power         payload=${payload}
    ${response}=                POST On Session             govee_open                  /router/api/v1/device/control                           json=${body}
    Status Should Be            200                         ${response}

Set Curtain Dynamic Pattern
    [Arguments]                 ${instance_type}            ${pattern_id}
    # instance_type can be 'lightScene' (factory presets) or 'diyScene' (user finger paintings)
    ${id_int}=                  Convert To Integer          ${pattern_id}
    ${capability}=              Create Dictionary           type=devices.capabilities.dynamic_scene                 instance=${instance_type}    value=${id_int}
    ${payload}=                 Create Dictionary           sku=${MODEL}                device=${DEVICE_MAC}        capability=${capability}
    ${body}=                    Create Dictionary           requestId=crt_scene         payload=${payload}
    ${response}=                POST On Session             govee_open                  /router/api/v1/device/control                           json=${body}
    Status Should Be            200                         ${response}

Verify Current Scene Playing
    ${inner_payload}=           Create Dictionary           sku=${MODEL}                device=${DEVICE_MAC}
    ${body}=                    Create Dictionary           requestId=crt_check         payload=${inner_payload}
    ${response}=                POST On Session             govee_open                  /router/api/v1/device/state                             json=${body}

    # Log the output directly so you can see the active number in the Copado suite console
    Log To Console              Current Active State Tree: ${response.json()['payload']['capabilities']}

Trigger Pro Curtain Scene Matrix
    [Arguments]                 ${p_id}                     ${scene_id}
    # Convert data types to matching integers to avoid formatting flags
    ${p_id_int}=                Convert To Integer          ${p_id}
    ${sc_id_int}=               Convert To Integer          ${scene_id}

    # This constructs the exact composite dictionary pattern Govee demands
    ${inner_val}=               Create Dictionary           paramId=${p_id_int}         id=${sc_id_int}

    ${capability}=              Create Dictionary           type=devices.capabilities.dynamic_scene                 instance=lightScene         value=${inner_val}
    ${payload}=                 Create Dictionary           sku=${MODEL}                device=${DEVICE_MAC}        capability=${capability}
    ${body}=                    Create Dictionary           requestId=crt_matrix_scene                              payload=${payload}

    ${response}=                POST On Session             govee_open                  /router/api/v1/device/control                           json=${body}
    Status Should Be            200                         ${response}


Discover All Govee Matrix Scenes
    [Documentation]             Queries the Govee OpenAPI router to retrieve the complete
    ...                         unified list of available pattern options (including factory
    ...                         presets, DIY finger-sketches, and snapshot spaces).
    ...
    ...                         Returns a Robot Framework list of dictionaries containing
    ...                         the 'name' and composite 'value' object (paramId and id).
    ...
    ...                         Example Usage:
    ...                         | ${all_scenes}= | Discover All Govee Matrix Scenes |

    ${inner_payload}=           Create Dictionary           sku=${MODEL}                device=${DEVICE_MAC}
    ${body}=                    Create Dictionary           requestId=crt_scene_discovery                           payload=${inner_payload}
    ${response}=                POST On Session             govee_open                  /router/api/v1/device/scenes                            json=${body}
    Status Should Be            200                         ${response}

    # Extract the capabilities list
    ${capabilities}=            Set Variable                ${response.json()['payload']['capabilities']}

    # Grab the options array from the first dynamic_scene capability block
    FOR                         ${cap}                      IN                          @{capabilities}
        IF                      '${cap['type']}' == 'devices.capabilities.dynamic_scene'
            RETURN              ${cap['parameters']['options']}
        END
    END

    Fail                        No dynamic scene capabilities were returned for this device.
Set Pro Curtains Purple
    # Purple (R:255, G:0, B:255) = Decimal integer representation 16711935
    ${capability}=              Create Dictionary           type=devices.capabilities.color_setting                 instance=colorRgb           value=${16711935}
    ${payload}=                 Create Dictionary           sku=${MODEL}                device=${DEVICE_MAC}        capability=${capability}
    ${body}=                    Create Dictionary           requestId=crt_color         payload=${payload}

    ${response}=                POST On Session             govee_open                  /router/api/v1/device/control                           json=${body}
    Status Should Be            200                         ${response}

Set Pro Curtains Color 
    [Arguments]     ${color_name}
    # --- Color map: name (lowercase) -> RGB decimal integer ---
    &{COLOR_MAP}=       Create Dictionary
    ...                 red=${16711680}
    ...                 green=${32768}
    ...                 blue=${255}
    ...                 white=${16777215}
    ...                 black=${0}
    ...                 yellow=${16776960}
    ...                 orange=${16753920}
    ...                 purple=${16711935}
    ...                 cyan=${65535}
    ...                 pink=${16738740}
    ...                 lime=${65280}
    ...                 teal=${32896}
    ...                 navy=${128}
    ...                 maroon=${8388608}
    ...                 gold=${16766720}
    ...                 coral=${16744272}

    ${color_key}=       Convert To Lower Case       ${color_name}
    ${color_value}=     Get From Dictionary         ${COLOR_MAP}    ${color_key}

    ${capability}=      Create Dictionary
    ...                 type=devices.capabilities.color_setting
    ...                 instance=colorRgb
    ...                 value=${color_value}

    ${payload}=         Create Dictionary
    ...                 sku=${MODEL}
    ...                 device=${DEVICE_MAC}
    ...                 capability=${capability}

    ${body}=            Create Dictionary
    ...                 requestId=crt_color
    ...                 payload=${payload}

    ${response}=        POST On Session     govee_open    /router/api/v1/device/control    json=${body}
    Status Should Be    200                 ${response}

Initialize Test Agent Session
    [Documentation]             Persistent session for the DemoJam Test Agent review call.
    ${headers}=                 Create Dictionary
    ...                         accept=application/json
    ...                         X-Authorization=${PACE_API_KEY}
    ...                         Content-Type=application/json
    Create Session               alias=TestAgentSession       url=https://copadogpt-api.robotic.copado.com

Create Test Agent Dialogue
    [Documentation]             Creates a dialogue thread in the DemoJam workspace, pinned to the
    ...                         built-in Test Agent (assistantId=test).
    ${dialogue_payload}=        Create Dictionary
    ...                         name=DemoJam call review
    ...                         workspaceId=009ea260-b4e2-4f47-8516-2a9b3d2a0554
    ...                         assistantId=test
    ${res}=                     POST On Session
    ...                         alias=TestAgentSession
    ...                         url=/organizations/47405/dialogues
    ...                         json=${dialogue_payload}
    ...                         headers=${headers}
    ...                         expected_status=201
    ...                         timeout=90
    ${dialogue_id}=             Set Variable                ${res.json()['id']}
    Set Suite Variable          ${TEST_AGENT_DIALOGUE_ID}   ${dialogue_id}
    RETURN                      ${dialogue_id}

Ask Test Agent To Review Call
    [Documentation]             Sends the filtered conversation transcript to the Test Agent and
    ...                         returns its plain-text verdict. Absorbs 403 indexing locks the same
    ...                         way the other Copado AI keywords in this project do.
    [Arguments]                 ${transcript_path}          ${max_attempts}=16          ${poll_interval}=15s

    ${transcript_exists}=       Run Keyword And Return Status    File Should Exist       ${transcript_path}
    IF                          ${transcript_exists}
        ${transcript}=          Get File                    ${transcript_path}
    ELSE
        ${transcript}=          Set Variable                (no filtered conversation log found -- the call may not have been answered)
    END

    ${eval_prompt}=              Catenate                    SEPARATOR=\n
    ...                         Here is the filtered conversation transcript (JSONL, one event per
    ...                         line) from a live demo call with the Agentforce voice agent. Give
    ...                         your read:
    ...
    ...                         1. HOW WELL did the agent follow its own instructions? Be concise
    ...                         and factual.
    ...                         2. Confirm, one by one, whether the transcript shows evidence the
    ...                         agent performed each agentic action:
    ...                         a. Diagnosed and fixed the CRT test job
    ...                         b. Created a Salesforce Case documenting the issue
    ...                         c. Updated/closed that Case with a clean resolution note
    ...                         For each, answer CONFIRMED (quote the line), NOT VISIBLE IN
    ...                         TRANSCRIPT, or CONTRADICTED.
    ...
    ...                         === TRANSCRIPT ===
    ...                         ${transcript}

    ${msg_uuid}=                Evaluate                    str(uuid.uuid4())            modules=uuid
    ${message_payload}=         Create Dictionary
    ...                         request_id=${msg_uuid}
    ...                         prompt=${eval_prompt}
    ...                         assistantId=test

    FOR                         ${attempt}                  IN RANGE                    1                           ${max_attempts} + 1
        ${response}=            POST On Session
        ...                     alias=TestAgentSession
        ...                     url=/organizations/47405/dialogues/${TEST_AGENT_DIALOGUE_ID}/messages
        ...                     json=${message_payload}
        ...                     headers=${headers}
        ...                     expected_status=any
        ...                     timeout=90
        END
        IF                      ${response.status_code} == 403
            IF                  ${attempt} == ${max_attempts}
                Fail            TIMEOUT: Test Agent dialogue thread locked for too long.
            END
            Sleep               ${poll_interval}
            CONTINUE
        END
        Fail                    ASK TEST AGENT FAILED: HTTP ${response.status_code}. Body: ${response.text}
    END

    ${read_res}=                 GET On Session
    ...                         alias=TestAgentSession
    ...                         url=/organizations/47405/dialogues/${TEST_AGENT_DIALOGUE_ID}
    ...                         headers=${headers}
    ...                         expected_status=200
    ...                         timeout=90
    ${messages}=                 Set Variable                ${read_res.json()['messages']}
    ${last_msg}=                 Set Variable                ${messages[-1]}
    ${content_blocks}=           Set Variable                ${last_msg['content']}
    ${verdict}=                  Set Variable                ${EMPTY}
    FOR                          ${block}                    IN                          @{content_blocks}
        ${verdict}=              Catenate                    ${verdict}                  ${block['text']}
    END

    Log To Console               \n=== Test Agent review of this call ===\n${verdict}
    RETURN                       ${verdict}