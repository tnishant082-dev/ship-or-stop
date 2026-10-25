# Runs one DAX query against the Analysis Services engine inside a running Power BI Desktop
# and prints the result rows as JSON. Used by scripts/kpi_check.py.
param([Parameter(Mandatory = $true)][string]$QueryFile)
$ErrorActionPreference = "Stop"
Add-Type -Path "C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll"
$ws = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces" -Directory |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1
$port = [IO.File]::ReadAllText((Join-Path $ws.FullName "Data\msmdsrv.port.txt"), [Text.Encoding]::Unicode).Trim()
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection "Data Source=localhost:$port"
$conn.Open()
$cmd = $conn.CreateCommand()
$cmd.CommandText = Get-Content $QueryFile -Raw
$r = $cmd.ExecuteReader()
$rows = @()
while ($r.Read()) {
    $o = [ordered]@{}
    for ($i = 0; $i -lt $r.FieldCount; $i++) { $o[$r.GetName($i)] = $r.GetValue($i) }
    $rows += [pscustomobject]$o
}
$conn.Close()
ConvertTo-Json -InputObject @($rows) -Depth 3 -Compress
