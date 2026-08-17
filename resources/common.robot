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
 
    ${token}                    JwtAuthenticate             ${AFclient_id}              ${username}    ${AFPrivate_key}
    Set Suite Variable          ${TOKEN}               ${token}       
    JwtLogin
    Open Browser                about:blank                 ${BROWSER}    
    SetConfig                   LineBreak                   ${EMPTY}
    Evaluate                    random.seed()               random
    SetConfig                   DefaultTimeout              20s
    SetConfig                   Delay                       0.3
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