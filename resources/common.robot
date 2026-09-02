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

