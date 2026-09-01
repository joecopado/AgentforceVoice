*** Settings ***
Library                         QForce
Resource                        ../resources/common.robot
Suite Setup                     Setup Browser
Suite Teardown                  End suite
Library                         ../resources/vm_check.py
Library                         ../resources/call_harness.py
Library                         ../resources/tunnel_helper.py

*** Test Cases ***
CDP Observation Session
    # 0. ensure no browser exists yet -- the flagged chrome must be the only one
    CloseAllBrowsers
    ${cloudflared}=    Prepare Cloudflared
    ${cwd}=            Get Working Directory

    # 1. raw Chrome binds the debug port (no chromedriver in the way; \= escapes matter)
    Start Process      google-chrome --remote-debugging-port\=9222 --user-data-dir\=/tmp/obsprof --no-first-run about:blank > /tmp/chrome.log 2>&1    shell=True
    Sleep              3
    ${result}=         Run Process    curl    -s    http://localhost:9222/json/version
    Should Contain     ${result.stdout}    Chrome

    # 2. tunnel the port out (URL is random per run -- read it from the console)
    Start Process      ${cloudflared} tunnel --url http://localhost:9222 --http-host-header localhost > ${cwd}/cdp_tunnel.log 2>&1    shell=True
    ${tunnel_url}=     Wait For Tunnel Url    ${cwd}/cdp_tunnel.log    3    45
    Log To Console     CDP TUNNEL FOR CLAUDE: ${tunnel_url}

    # 3. QWeb ATTACHES to that same Chrome (reuse path) -- now QForce drives the observed browser
    Set Global Variable    ${BROWSER_REUSE}    True
    OpenBrowser        about:blank    chrome    debugger_address=localhost:9222    executor_url=unused
    SwitchBrowser      NEW
    JwtAuthenticate    ${slockardClient}    ${slockardUser}    ${slockardPrivate}
    JwtLogin

    # 4. hand Claude the tunnel URL, wait for "recording", then drive the steps
LWC/Aura/VisualForce
#https://slockard-dev-ed.lightning.force.com/lightning/n/Refresh_View - bug here, work showing for our demo how it can be found
#https://slockard-dev-ed.lightning.force.com/lightning/n/Refresh_View - bug here same as above

   ${isntanceUrl}    GetInstanceUrl
    GoTo              ${isntanceUrl}/lightning/n/Zoo_Base_Inputs
    


    
    #Clicks Option A under Radio - closest text
    ClickText    Option A    anchor=Radio
    #Clicks OptionC under Radio (secondary) - closest text
    ClickText    Option C    anchor=Checkbox Group

    #Achoring may not be a very relaible approach. xpaths below parameterized would allow it to target more specifically as clickItem can only use one anchor making it not useable in this scenario. This would be likely be the best backup options.
    ClickElement             //fieldset[.//legend[normalize-space(text())\='Radio']]//span[contains(@class,'slds-radio')][.//span[contains(@class,'slds-form-element__label') and normalize-space(text())\='Option A']]//input[@type\='radio']
    ClickElement             //fieldset[.//legend[normalize-space(text())\='Radio (secondary)']]//span[contains(@class,'slds-radio')][.//span[contains(@class,'slds-form-element__label') and normalize-space(text())\='Option B']]//input[@type\='radio']

    ClickElement    //fieldset[.//legend[normalize-space(text())\='Checkbox Group (secondary)']]//span[contains(@class,'slds-checkbox')][.//span[contains(@class,'slds-form-element__label') and normalize-space(text())\='Option B']]//input[@type\='checkbox']

    
    #Disambiguate Color selectors
    ClickText    Choose a color. Current color:    anchor=Color (secondary)
    ClickText    Done

    #MultiPicklist - Available is the text above the left hand Dual Listbox. Move select to chosen is the button between the list that moves them, lement below. It basically just clicks an option, then moves it over.
    # <button lwc-485vfn4rmof="" class="slds-button slds-button_icon slds-button_icon-container" title="Move selection to Chosen" type="button" part="button button-icon" style="border: 5px solid blue;" data-position-id="lgcp-1000025"><lightning-primitive-icon lwc-485vfn4rmof="" exportparts="icon" variant="bare" lwc-d8atf0ck0l-host=""><svg focusable="false" aria-hidden="true" viewBox="0 0 520 520" part="icon" lwc-d8atf0ck0l="" data-key="right" class="slds-button__icon"><g lwc-d8atf0ck0l=""><path d="M140 437V83c0-10 13-17 22-9l212 173c8 6 8 19 0 25L162 447c-9 7-22 1-22-10" lwc-d8atf0ck0l=""></path></g></svg></lightning-primitive-icon><span class="slds-assistive-text" lwc-485vfn4rmof="">Move selection to Chosen</span></button>
    MultiPicklist    Available     Apex   action=Move selection to Chosen

    #Alternative to MultiPicklist (Also showing how to anchor to disambiguate the 2.)
    ClickText        LWC           anchor=Dual Listbox (secondary)
    ClickText        Move selection to Chosen      anchor=Dual Listbox (secondary)

    #Using the first multipicklist option wouldn't allow the ability to disambiguate between the 2. Using the title over the second box, despite both having available, will allow it to disambiguate
    MultiPicklist    Dual Listbox (secondary)     Apex   action=Move selection to Chosen

    TypeText         Salesforce Sans              234

    #Surprisignly, both of these options work for the 2 lightning-input-rich-text fields that have no unique identifier visible. This works because of aria-label="Rich Text (secondary)"
    #But, it isn't uncommon for these to have NOTHING unique
    TypeText    Rich Text    asd
    TypeText    Rich Text (secondary)    asd

    
    #The 2 account name fields would require an anchor to disambiguate
    TypeText    *Account Name    asd    anchor=Account Number
    TypeText    *Account Name    sdf    anchor=GarzAI Zoo Rating
    
    #Anchor as an index also works in this example
    TypeText    Account Name     234    anchor=2

    GoTo              ${isntanceUrl}/lightning/n/Zoo_Tables_Containers

    #Some basic table interactions on the first table at the top. Tables generally can just use a column name as well, but in this case both tables have the same column names.
    UseTable        xpath\=//table[@aria-label\="Zoo Datatable"][1]
    #r1 is always the header. r2 is the first row in a table. c? allows you to use the column header name. c by number is veeeeeeery flakey.
    VerifyTable     r2/c?Name    Zoo Row 1
    #The below click LOOKS like it should hit that checkmark, but it cannot. ClickCell isn't a good approach for interacting with different elements in a table. It hits the cell level primarily rather than the contents within.
    #ClickCell    r2/c2  tag=input    index=2
    #This click item approach will ONLY be applicable to the top table - no way to disambiguate for the second table. This click is to make it editable.
    ClickItem    enter,space   anchor=Zoo Row 1           tag=button
    #HotKey       CTRL           A
    #Hotkey crtl a couldn't clear this field.
    Sleep        1
    WriteText    asd
    HotKey       Enter

    #The second table below can be interacted with by using the xpath approach for use table. However, the edits, likely would have to utilize a relative xpath to the table itself. I don't see another option to truly make that possible

    
    #This exapands these rows. While this will work for Zoo Tree - there is no way to disambiguate this for Zoo Tree (secondary) - An xpath would be necessary
    ClickItem    Expand Tree Branch                       anchor=Branch 2    tag=button
    #This would be the only way to gain true flexibility over both of these zoo trees
    ClickElement                        //lightning-tree[@aria-label\="Zoo Tree (secondary)"]//lightning-tree-item[@aria-label\="Zoo Branch 2"]//button[@title\="Expand Tree Branch"]
    ClickElement                        //lightning-tree[@aria-label\="Zoo Tree (secondary)"]//lightning-tree-item[@aria-label\="Zoo Branch 1"]//button[@title\="Expand Tree Branch"]

    
    #These will work for these tabs, as these nearby text point are sufficient to disambiguate - maybe not idea, but it works
    ClickText    Zoo Tab Two    anchor=Zoo Parent 2
    ClickText    Zoo Tab Three    anchor=Zoo Parent 2
    ClickText    Zoo Tab Two    anchor=Zoo Section A
    ClickText    Zoo Tab Three    anchor=Zoo Section A
