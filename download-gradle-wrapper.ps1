# Gradle Wrapper Download Script
# Run this script to download the gradle-wrapper.jar if it is not present

$wrapperDir = "$PSScriptRoot\gradle\wrapper"
$jarPath = "$wrapperDir\gradle-wrapper.jar"

if (Test-Path $jarPath) {
    Write-Host "gradle-wrapper.jar already exists."
    exit 0
}

$wrapperUrl = "https://raw.githubusercontent.com/gradle/gradle/v8.5.0/gradle/wrapper/gradle-wrapper.jar"

Write-Host "Downloading gradle-wrapper.jar..."
try {
    Invoke-WebRequest -Uri $wrapperUrl -OutFile $jarPath
    Write-Host "Successfully downloaded gradle-wrapper.jar"
} catch {
    Write-Error "Failed to download gradle-wrapper.jar: $_"
    exit 1
}
