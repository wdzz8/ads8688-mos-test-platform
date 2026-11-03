$ErrorActionPreference = 'Stop'
$submissionRoot = Split-Path -Parent $PSScriptRoot
$submissionDocx = (Get-ChildItem -LiteralPath (Join-Path $submissionRoot 'output/submission_20261103') -Filter '*.docx').FullName
$submissionPdf = [System.IO.Path]::ChangeExtension($submissionDocx, '.pdf')
$submissionWord = New-Object -ComObject Word.Application
$submissionWord.Visible = $false
$submissionWord.DisplayAlerts = 0
try {
    $submissionDocument = $submissionWord.Documents.Open($submissionDocx, $false, $true)
    $submissionDocument.Repaginate()
    $submissionDocument.ExportAsFixedFormat($submissionPdf, 17)
    $submissionDocument.Close(0)
} finally {
    $submissionWord.Quit()
}
Write-Output $submissionPdf
