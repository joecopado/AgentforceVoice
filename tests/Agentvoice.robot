*** Settings ***
Library           QForce
Resource          ../resources/common.robot
Suite Setup       Setup Browser
Suite Teardown    End suite
Resource    ../resources/common.robot
Library    ../resources/vm_check.py


*** Test Cases ***
Test
    