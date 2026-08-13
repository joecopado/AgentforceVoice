*** Settings ***
Library           QForce
Resource          ../resources/common.robot
Suite Setup       Setup Browser
Suite Teardown    End suite
Library    ../resources/vm_check.py
Library    ../resources/call_harness.py


*** Test Cases ***
Test
    ${report}=    Run Vm Check
    Log To Console    ${report}
    GoTo                    file:///home/services/suite/resources/bin/
    ${call_sid}=    Place Verification Call
    Log To Console    ${call_sid}