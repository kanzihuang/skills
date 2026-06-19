param(
    [Parameter(Mandatory=$true)]
    [string]$htmlPath
)

Add-Type -AssemblyName System.Windows.Forms

# Read the HTML file as UTF-8
$rawHtml = Get-Content $htmlPath -Raw -Encoding UTF8

$crlf = "`r`n"
$pre  = "<html><body><!--StartFragment-->"
$post = "<!--EndFragment--></body></html>"
$utf8 = [System.Text.Encoding]::UTF8

# Build header template with placeholder zeros (always 105 bytes in UTF-8)
$headerPlaceholder = "Version:0.9" + $crlf +
                     "StartHTML:0000000000" + $crlf +
                     "EndHTML:0000000000" + $crlf +
                     "StartFragment:0000000000" + $crlf +
                     "EndFragment:0000000000" + $crlf

# Calculate byte offsets in UTF-8
$hdrBytes  = $utf8.GetBytes($headerPlaceholder)
$preBytes  = $utf8.GetBytes($pre)
$rawBytes  = $utf8.GetBytes($rawHtml)
$postBytes = $utf8.GetBytes($post)

$startHTML     = $hdrBytes.Length
$startFragment = $startHTML + $preBytes.Length
$endFragment   = $startFragment + $rawBytes.Length
$endHTML       = $endFragment + $postBytes.Length

# Build final header with correct offsets (all offsets fit in 10 digits)
$header = "Version:0.9" + $crlf +
          "StartHTML:" + $startHTML.ToString("0000000000") + $crlf +
          "EndHTML:" + $endHTML.ToString("0000000000") + $crlf +
          "StartFragment:" + $startFragment.ToString("0000000000") + $crlf +
          "EndFragment:" + $endFragment.ToString("0000000000") + $crlf

# Recalculate header bytes to adjust offsets (digits may differ from placeholders)
$finalHdrBytes = $utf8.GetBytes($header)
$diff = $finalHdrBytes.Length - $hdrBytes.Length
$startHTML     += $diff
$startFragment += $diff
$endFragment   += $diff
$endHTML       += $diff

$header = "Version:0.9" + $crlf +
          "StartHTML:" + $startHTML.ToString("0000000000") + $crlf +
          "EndHTML:" + $endHTML.ToString("0000000000") + $crlf +
          "StartFragment:" + $startFragment.ToString("0000000000") + $crlf +
          "EndFragment:" + $endFragment.ToString("0000000000") + $crlf

$clipContent = $header + $pre + $rawHtml + $post

# Retry loop for clipboard (may be locked by another process)
for ($i = 0; $i -lt 5; $i++) {
    try {
        [System.Windows.Forms.Clipboard]::SetText($clipContent, [System.Windows.Forms.TextDataFormat]::Html)
        Write-Host "HTML copied to clipboard ($($utf8.GetBytes($clipContent).Length) bytes)"
        break
    } catch {
        if ($i -eq 4) {
            Write-Host "WARNING: Failed to copy to clipboard after 5 attempts"
        }
        Start-Sleep -Milliseconds 200
    }
}

# Open in browser
Start-Process "msedge" -ArgumentList "file:///$htmlPath" -NoNewWindow
Write-Host "Opened in browser: $htmlPath"
