param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$ServiceAccountEmail,

    [Parameter(Mandatory = $true)]
    [string]$SmtpUsername,

    [Parameter(Mandatory = $true)]
    [string]$AlertRecipient,

    [Parameter(Mandatory = $true)]
    [string]$AdminApiKey,

    [string]$Region = "asia-south1",
    [string]$ServiceName = "arunachalam-ticket-monitor",
    [string]$GmailSecretName = "arunachalam-gmail-app-password",
    [string]$GmailSecretVersion = "1"
)

$ErrorActionPreference = "Stop"

gcloud config set project $ProjectId

$environmentVariables = @(
    "ENVIRONMENT=production",
    "POLL_INTERVAL_SECONDS=20",
    "FIRESTORE_PROJECT_ID=$ProjectId",
    "FIRESTORE_DATABASE=(default)",
    "SMTP_USERNAME=$SmtpUsername",
    "SMTP_FROM_EMAIL=$SmtpUsername",
    "ALERT_RECIPIENTS=[`"$AlertRecipient`"]",
    "ADMIN_API_KEY=$AdminApiKey"
) -join ","

gcloud run deploy $ServiceName `
    --source . `
    --region $Region `
    --service-account $ServiceAccountEmail `
    --allow-unauthenticated `
    --min 1 `
    --max 1 `
    --no-cpu-throttling `
    --cpu 1 `
    --memory 512Mi `
    --concurrency 10 `
    --timeout 60 `
    --set-env-vars $environmentVariables `
    --set-secrets "SMTP_APP_PASSWORD=$GmailSecretName`:$GmailSecretVersion"

Write-Host "Deployment submitted. Verify /healthz/ready and Cloud Logging before relying on alerts."
