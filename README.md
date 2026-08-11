# Arunachalam Ticket Observability Nanoservice

A FastAPI service for Google Cloud Run that checks the official Tamil Nadu HR&CE
₹2,500 **Swami Amman Special Abhishekam** calendar every 20 seconds. When a new
set of available dates appears, it sends ten Gmail SMTP messages spaced 0.5
seconds apart.

This service is alert-only. It does not solve CAPTCHA, submit OTPs, start a
payment, or reserve tickets.

## Reliability behavior

- Uses the central HR&CE host first and the Annamalaiyar subdomain as a fallback.
- Retries bounded network failures with exponential backoff.
- Rejects suspiciously small or structurally unexpected responses.
- Never interprets a timeout, HTTP error, DNS error, or parser error as “sold out.”
- Preserves the most recent successful state when HR&CE is unavailable.
- Contains every monitor iteration behind a final exception boundary, so one
  unexpected failure cannot terminate the all-day loop.
- Uses a Firestore lease to prevent two Cloud Run revisions from checking and
  notifying simultaneously.
- Claims an alert in Firestore before SMTP and marks it delivered only after the
  full ten-message burst succeeds.
- Sends one health-warning email after three consecutive monitor failures, then
  continues retrying. A later successful check resets that warning state.

Alert deduplication works as follows:

- A newly available date set sends one ten-message burst.
- Repeated checks of the same open dates do not send more mail.
- Adding or removing an available date creates a new state and a new burst.
- A fully closed state resets the key; the same dates reopening later trigger a
  new burst.

## Deploy from GitHub using local PowerShell

This is the primary deployment path. GitHub stores the code, while your local
PowerShell terminal configures Google Cloud and deploys the service. You do not
need to use Google Cloud Console or build a Docker image locally; Cloud Build
builds the repository's `Dockerfile` when `gcloud run deploy --source .` runs.

You need:

- Git for Windows
- Google Cloud CLI
- a Google Cloud project with billing enabled
- permission to manage APIs, IAM, Firestore, Secret Manager, and Cloud Run
- a Gmail account with 2-Step Verification enabled

All commands below run in Windows PowerShell.

### 1. Install and authenticate the Google Cloud CLI

Install the [Google Cloud CLI for Windows](https://docs.cloud.google.com/sdk/docs/install-sdk#windows),
open a new PowerShell window, and run:

```powershell
gcloud init
gcloud auth list
```

`gcloud init` opens a normal Google sign-in page for authentication; it does not
require you to configure the service through Google Cloud Console.

If you do not already have a project, it can also be created and linked to an
existing billing account from the terminal:

```powershell
gcloud billing accounts list
gcloud projects create "YOUR-GLOBALLY-UNIQUE-PROJECT-ID" --name="Arunachalam Monitor"
gcloud billing projects link "YOUR-GLOBALLY-UNIQUE-PROJECT-ID" --billing-account="YOUR-BILLING-ACCOUNT-ID"
```

Skip those three commands when the project already exists and has billing.

### 2. Clone the GitHub repository

```powershell
Set-Location "D:\"
git clone https://github.com/Bmokshith2406/Arunachelam-Website-Observer.git
Set-Location ".\Arunachelam-Website-Observer"
```

If you are already working in the cloned repository, use:

```powershell
git pull --ff-only origin main
```

Never create or commit a real `.env` file containing the Gmail app password.

### 3. Select the project and enable APIs

Replace the project ID, then run the entire block:

```powershell
$projectId = "YOUR-PROJECT-ID"
gcloud config set project $projectId

gcloud services enable `
  run.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  firestore.googleapis.com `
  secretmanager.googleapis.com

$projectNumber = gcloud projects describe $projectId --format="value(projectNumber)"
$buildServiceAccount = "${projectNumber}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding $projectId `
  --member="serviceAccount:$buildServiceAccount" `
  --role="roles/run.builder"
```

The final role allows the default Cloud Build identity to build source
deployments. Allow a couple of minutes for a newly granted role to propagate.

These instructions assume you own the project. In an organization-managed
project, an administrator may need to grant your Google account **Cloud Run
Source Developer**, **Service Usage Consumer**, and **Service Account User**.

### 4. Create Firestore from PowerShell

The app uses the `(default)` Firestore database in Mumbai. It stores only dates,
response fingerprints, timestamps, leases, failure counters, and alert keys. It
does not store devotee information, OTPs, CAPTCHA, cards, or payment details.

```powershell
gcloud firestore databases describe --database="(default)" 1>$null 2>$null

if ($LASTEXITCODE -ne 0) {
  gcloud firestore databases create `
    --database="(default)" `
    --location="asia-south1" `
    --edition="standard" `
    --type="firestore-native" `
    --delete-protection
}
```

If the database already exists, the block leaves it unchanged. A Firestore
location cannot be changed after creation. No collection, document, or index
needs to be created manually; the service creates its state document during its
first successful transaction.

### 5. Create the runtime service account

```powershell
$serviceAccountName = "arunachalam-monitor"
$serviceAccountEmail = "$serviceAccountName@$projectId.iam.gserviceaccount.com"

gcloud iam service-accounts describe $serviceAccountEmail 1>$null 2>$null

if ($LASTEXITCODE -ne 0) {
  gcloud iam service-accounts create $serviceAccountName `
    --display-name="Arunachalam ticket monitor"
}

gcloud projects add-iam-policy-binding $projectId `
  --member="serviceAccount:$serviceAccountEmail" `
  --role="roles/datastore.user"
```

Do not create or download a service-account JSON key. Cloud Run uses the service
account directly. `roles/datastore.user` gives the runtime access to Firestore.

### 6. Create the Gmail app password and Secret Manager secret

1. Enable 2-Step Verification on the Gmail sender account.
2. Open [Google App passwords](https://myaccount.google.com/apppasswords).
3. Create an app password named `Arunachalam monitor`.
4. Keep the generated 16-character value ready and remove its display spaces.

Create the secret if it does not already exist:

```powershell
$secretName = "arunachalam-gmail-app-password"

gcloud secrets describe $secretName 1>$null 2>$null

if ($LASTEXITCODE -ne 0) {
  gcloud secrets create $secretName --replication-policy="automatic"
}
```

Add the Gmail password without placing it in PowerShell history. The following
block masks the input, writes a temporary file without a trailing newline,
uploads it, and removes the file in `finally` even if the upload fails:

```powershell
$temporarySecretFile = New-TemporaryFile
$temporarySecretPath = $temporarySecretFile.FullName
$secureAppPassword = Read-Host "Paste the Gmail app password" -AsSecureString
$temporaryCredential = [PSCredential]::new("gmail", $secureAppPassword)

try {
  $plainAppPassword = $temporaryCredential.GetNetworkCredential().Password
  [IO.File]::WriteAllText($temporarySecretPath, $plainAppPassword)
  gcloud secrets versions add $secretName --data-file=$temporarySecretPath
}
finally {
  Remove-Item -LiteralPath $temporarySecretPath -Force -ErrorAction SilentlyContinue
  Remove-Variable plainAppPassword -ErrorAction SilentlyContinue
  $temporaryCredential = $null
  $secureAppPassword = $null
}
```

Grant only the runtime service account permission to read it:

```powershell
gcloud secrets add-iam-policy-binding $secretName `
  --member="serviceAccount:$serviceAccountEmail" `
  --role="roles/secretmanager.secretAccessor"
```

The first secret version is version `1`. Check the active versions at any time:

```powershell
gcloud secrets versions list $secretName
```

### 7. Deploy to Cloud Run

Generate a private management API key and save it in a password manager:

```powershell
$randomBytes = New-Object byte[] 24
$randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
$randomGenerator.GetBytes($randomBytes)
$randomGenerator.Dispose()
$adminApiKey = [BitConverter]::ToString($randomBytes).Replace("-", "").ToLowerInvariant()
$adminApiKey
```

Deploy from the repository root after replacing the two email addresses:

```powershell
.\scripts\deploy_cloud_run.ps1 `
  -ProjectId $projectId `
  -ServiceAccountEmail $serviceAccountEmail `
  -SmtpUsername "sender@gmail.com" `
  -AlertRecipient "recipient@gmail.com" `
  -AdminApiKey $adminApiKey
```

The deployment uses:

- region `asia-south1` (Mumbai)
- one minimum and one maximum instance
- instance-based CPU allocation through `--no-cpu-throttling`
- one vCPU and 512 MiB memory
- a 20-second monitor interval
- the Gmail password from Secret Manager version `1`

Minimum instance `1` and instance-based CPU are required because the monitor runs
between HTTP requests. This creates ongoing Cloud Run charges. Cloud Run can
occasionally restart the instance, but Firestore preserves state and the monitor
automatically resumes.

### 8. Verify from PowerShell

```powershell
$serviceUrl = gcloud run services describe "arunachalam-ticket-monitor" `
  --region="asia-south1" `
  --format="value(status.url)"

Invoke-RestMethod "$serviceUrl/healthz/live"
Invoke-RestMethod "$serviceUrl/healthz/ready"
Invoke-RestMethod "$serviceUrl/api/v1/monitor/status" `
  -Headers @{ "X-API-Key" = $adminApiKey }
```

Request one immediate protected check with:

```powershell
Invoke-RestMethod "$serviceUrl/api/v1/monitor/check" `
  -Method Post `
  -Headers @{ "X-API-Key" = $adminApiKey }
```

View recent logs without opening Google Cloud Console:

```powershell
gcloud run services logs read "arunachalam-ticket-monitor" `
  --region="asia-south1" `
  --limit=100
```

No availability email is expected while all dates are closed. A temporary HR&CE
timeout or invalid response is logged as a failure and does not stop the service,
erase the last successful state, or create a false “sold out” result. After three
consecutive monitor failures, the service sends one warning email and keeps
retrying.

### 9. Deploy later GitHub updates

Pull the new code and rerun the same deployment script:

```powershell
git pull --ff-only origin main

.\scripts\deploy_cloud_run.ps1 `
  -ProjectId $projectId `
  -ServiceAccountEmail $serviceAccountEmail `
  -SmtpUsername "sender@gmail.com" `
  -AlertRecipient "recipient@gmail.com" `
  -AdminApiKey $adminApiKey
```

Cloud Run creates a new revision while Firestore keeps availability and alert
history. If the Gmail app password is rotated, repeat the secret-version upload,
find the new version number, and pass it during deployment:

```powershell
.\scripts\deploy_cloud_run.ps1 `
  -ProjectId $projectId `
  -ServiceAccountEmail $serviceAccountEmail `
  -SmtpUsername "sender@gmail.com" `
  -AlertRecipient "recipient@gmail.com" `
  -AdminApiKey $adminApiKey `
  -GmailSecretVersion "2"
```

Official references: [install Google Cloud CLI](https://docs.cloud.google.com/sdk/docs/install-sdk),
[deploy Cloud Run from source](https://docs.cloud.google.com/run/docs/deploying-source-code),
[create a Firestore database](https://docs.cloud.google.com/firestore/native/docs/manage-databases),
and [add a Secret Manager version](https://docs.cloud.google.com/secret-manager/docs/add-secret-version).

## Optional local development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, authenticate Application Default Credentials to a test Firestore
project with `gcloud auth application-default login`, and start the service with
`uvicorn app.main:app --reload --port 8080`. Run the tests with `pytest -q`.

## API

- `GET /healthz/live` — container liveness
- `GET /healthz/ready` — monitor task readiness and latest local status
- `GET /api/v1/monitor/status` — protected status endpoint
- `POST /api/v1/monitor/check` — protected immediate check
- `GET /metrics` — Prometheus metrics
- `GET /docs` — OpenAPI documentation

The management routes require `X-API-Key`. Cloud Run is configured for public
access so monitoring diagnostics are easy to reach, but no secret-bearing or
state-changing route is unauthenticated.
