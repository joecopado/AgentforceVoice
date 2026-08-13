*** Settings ***
Library           QForce
Resource          ../resources/common.robot
Suite Setup       Setup Browser
Suite Teardown    End suite
Library    ../resources/vm_check.py


*** Test Cases ***
Test
    ${report}=    Run Vm Check
    Log To Console    ${report}