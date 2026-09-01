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
    GoTo               https://slockard-dev-ed.lightning.force.com/lightning/o/Case/new?count=1
    # PickList / ComboBox steps here, ~3s apart
