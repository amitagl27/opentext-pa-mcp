# Reproducible OTDS login helper used during discovery.
# Usage:
#   . .\Login-Appworks.ps1
#   $s = Get-AwSession -BaseUrl 'https://api.example.com:3381' -EntityServicePath '/home/exampletenant/app/entityservice/ExampleLegalManagement' -Username 'awpadmin' -Password '<YOUR_PASSWORD>'
#   Invoke-WebRequest -Uri "$apiBase/..." -WebSession $s -UseBasicParsing
#
# Returns a Microsoft.PowerShell.Commands.WebRequestSession with three cookies set on the AppWorks host:
#   defaultinst_AuthContext (durable), defaultinst_SAMLart, defaultinst_ct
#
# DO NOT export the session via Export-Clixml — the deserialized type is incompatible with -WebSession.
# Just re-run Get-AwSession when you need a fresh session.

function Get-AwSession {
    param(
        [Parameter(Mandatory)] [string] $BaseUrl,
        [Parameter(Mandatory)] [string] $EntityServicePath,
        [Parameter(Mandatory)] [string] $Username,
        [Parameter(Mandatory)] [string] $Password,
        [int] $TimeoutSec = 30
    )

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

    # 1. Hit a protected resource → ends on OTDS login page; captures CSRF + RFA tokens.
    $loginPage = Invoke-WebRequest -Uri ($BaseUrl + $EntityServicePath) `
        -WebSession $session -UseBasicParsing `
        -MaximumRedirection 10 -TimeoutSec $TimeoutSec
    $loginUrl = $loginPage.BaseResponse.ResponseUri.AbsoluteUri
    $csrf = ([regex]::Match($loginPage.Content, 'name="otdscsrf"\s+value="([^"]+)"')).Groups[1].Value
    $rfa  = ([regex]::Match($loginPage.Content, 'name="RFA"\s+value="([^"]+)"')).Groups[1].Value
    if (-not $csrf -or -not $rfa) {
        throw "Failed to find otdscsrf / RFA tokens on login page."
    }

    # 2. POST credentials. NOTE: field names are otds_username / otds_password, not username / password.
    $r1 = Invoke-WebRequest -Uri $loginUrl -Method POST `
        -Body @{ otds_username=$Username; otds_password=$Password; otdscsrf=$csrf; RFA=$rfa; fragment=''; authhandler='' } `
        -WebSession $session -UseBasicParsing `
        -MaximumRedirection 15 -TimeoutSec $TimeoutSec `
        -ContentType 'application/x-www-form-urlencoded'

    # 3. The login response is an HTML page with an auto-submit form POSTing OTDSTicket to TicketConsumerService.
    $tm = [regex]::Match($r1.Content, '(?s)<form\s+action="([^"]+)"\s+method="post">.*?name="OTDSTicket"\s+value="([^"]+)"')
    if (-not $tm.Success) {
        throw "Login failed — no OTDSTicket form returned. Check credentials."
    }
    $tcAction   = [System.Net.WebUtility]::HtmlDecode($tm.Groups[1].Value)
    $otdsTicket = $tm.Groups[2].Value

    # 4. POST the ticket to TicketConsumerService; final cookies are set on the AppWorks host.
    Invoke-WebRequest -Uri $tcAction -Method POST `
        -Body @{ OTDSTicket = $otdsTicket } `
        -WebSession $session -UseBasicParsing `
        -MaximumRedirection 15 -TimeoutSec $TimeoutSec `
        -ContentType 'application/x-www-form-urlencoded' | Out-Null

    return $session
}
