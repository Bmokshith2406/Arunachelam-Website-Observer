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

## Deploy entirely from Chrome and Google Cloud Console

You do not need Docker or the Google Cloud CLI on your computer. Cloud Shell runs
inside Google Cloud Console, and Cloud Build builds the container from this
repository's `Dockerfile`.

Before beginning, have these ready:

- a Google Cloud project with billing enabled
- the project's **Project ID** (not its display name or project number)
- the Gmail address that will send alerts
- the email address that will receive alerts
- a Gmail app password created in the next step

The commands below are intended for **Cloud Shell's Bash terminal**, not Windows
PowerShell, unless the step explicitly says otherwise.

### 1. Create the Gmail app password

1. Sign in to the Google account that will send the alerts.
2. Turn on **2-Step Verification**.
3. Open [Google App passwords](https://myaccount.google.com/apppasswords).
4. Create an app password named `Arunachalam monitor`.
5. Copy the 16-character password. Remove the display spaces when storing it.

Do not put this password in the source ZIP or in a normal Cloud Run environment
variable. Google may revoke app passwords after the Google account password is
changed. Personal Gmail also has sending limits, so avoid repeatedly triggering
production test alerts; every new availability state sends ten messages.

### 2. Create the source ZIP on Windows

Open PowerShell in `D:\Arunachalam-Web-Observability` and run:

```powershell
$deployFiles = @("app", "requirements.txt", "Dockerfile", ".dockerignore", "pytest.ini", "README.md")
Compress-Archive -Path $deployFiles -DestinationPath "arunachalam-monitor-source.zip" -Force
```

This deliberately excludes `.venv`, `.git`, test caches, local `.env` files, and
credentials. The resulting file is
`D:\Arunachalam-Web-Observability\arunachalam-monitor-source.zip`.

### 3. Open the project and enable Google APIs

1. Open [Google Cloud Console](https://console.cloud.google.com/) in Chrome.
2. Use the project selector at the top to select the project with billing enabled.
3. Click **Activate Cloud Shell** (`>_`) in the top-right corner.
4. In Cloud Shell, replace the first value below and run all the commands:

```bash
PROJECT_ID="your-project-id"
gcloud config set project "$PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com

# Required by current Cloud Run source deployments so Cloud Build can build it.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
BUILD_SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role="roles/run.builder"
```

Wait until the commands finish, then allow a couple of minutes for the new build
permission to propagate. The selected project shown in the Console header must be
the same project printed by `gcloud config get-value project`.

These steps assume you own the project. In an organization-managed project, an
administrator may instead need to grant your Google account **Cloud Run Source
Developer**, **Service Usage Consumer**, and **Service Account User**.

### 4. Create Firestore in the Console

Firestore stores only dates, fingerprints, timestamps, leases, failure counters,
and alert keys. It stores no temple login, devotee details, OTP, CAPTCHA, card, or
payment information.

1. Use the Console search bar to open **Firestore**.
2. Open **Databases**, then click **Create database**.
3. Select **Firestore Native mode** and the **Standard** edition if an edition is
   requested.
4. Leave the database ID as `(default)`; if the form shows an empty optional ID,
   leave it empty so Standard edition creates `(default)`.
5. Select `asia-south1 (Mumbai)` as the location.
6. Choose production/locked security rules if prompted, then create the database.
7. Enable delete protection if the Console offers that option.

If `(default)` already exists, use it and do not create another database. A
Firestore location cannot be changed after creation. Do not manually create a
collection, document, or index; the service creates its state document during its
first successful transaction.

### 5. Create the runtime service account

1. Use the Console search bar to open **Service Accounts**.
2. Click **Create service account**.
3. Enter `arunachalam-monitor` as the service account name and click **Create and
   continue**.
4. Grant the role **Cloud Datastore User**.
5. Click **Done**. Do not create or download a JSON key.
6. Copy the service account email. It will look like
   `arunachalam-monitor@your-project-id.iam.gserviceaccount.com`.

The Cloud Datastore User role allows the server SDK to transact with Firestore.
Firestore browser/mobile security rules do not replace this IAM permission.

### 6. Store the Gmail password in Secret Manager

1. Use the Console search bar to open **Secret Manager**.
2. Click **Create secret**.
3. Name it `arunachalam-gmail-app-password`.
4. Paste the Gmail app password as the secret value, without spaces.
5. Leave automatic replication selected and click **Create secret**.
6. On the new secret's details page, open **Permissions** or **Show info panel**,
   then click **Grant access**.
7. Add the `arunachalam-monitor@...` service account as the principal.
8. Assign **Secret Manager Secret Accessor** and save.

Only the runtime service account should receive access to this secret.

### 7. Upload and deploy from Cloud Shell

1. Return to Cloud Shell.
2. Open its three-dot **More** menu, select **Upload**, and upload
   `arunachalam-monitor-source.zip`.
3. Run:

```bash
DEPLOY_DIR="$HOME/arunachalam-monitor-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEPLOY_DIR"
unzip -q "$HOME/arunachalam-monitor-source.zip" -d "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

PROJECT_ID="$(gcloud config get-value project)"
SERVICE_ACCOUNT="arunachalam-monitor@${PROJECT_ID}.iam.gserviceaccount.com"
ADMIN_API_KEY="$(openssl rand -hex 24)"

SMTP_USERNAME="sender@gmail.com"
ALERT_RECIPIENT="recipient@gmail.com"

echo "Save this ADMIN_API_KEY somewhere private: ${ADMIN_API_KEY}"
```

Replace `sender@gmail.com` and `recipient@gmail.com` in Cloud Shell with the real
addresses, rerun those two assignment lines, and save the printed admin API key.
Then deploy:

```bash
gcloud run deploy arunachalam-ticket-monitor \
  --source . \
  --region asia-south1 \
  --service-account "$SERVICE_ACCOUNT" \
  --allow-unauthenticated \
  --min 1 \
  --max 1 \
  --no-cpu-throttling \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 10 \
  --timeout 60 \
  --set-env-vars "^@^ENVIRONMENT=production@POLL_INTERVAL_SECONDS=20@FIRESTORE_PROJECT_ID=${PROJECT_ID}@FIRESTORE_DATABASE=(default)@SMTP_USERNAME=${SMTP_USERNAME}@SMTP_FROM_EMAIL=${SMTP_USERNAME}@ALERT_RECIPIENTS=[\"${ALERT_RECIPIENT}\"]@ADMIN_API_KEY=${ADMIN_API_KEY}" \
  --set-secrets "SMTP_APP_PASSWORD=arunachalam-gmail-app-password:1"
```

Answer `y` if Cloud Shell asks to create an Artifact Registry repository or
enable another required API. When deployment completes, copy the service URL
printed after `Service URL:`.

These flags are essential for an all-day background monitor: minimum instances
is `1`, maximum instances is `1`, and `--no-cpu-throttling` keeps CPU allocated
between HTTP requests. This configuration incurs ongoing Cloud Run charges and
Cloud Run can still occasionally restart the instance; Firestore preserves the
monitor state and the application resumes automatically.

### 8. Verify the deployment in Chrome

1. Open **Cloud Run** in the Console and select
   `arunachalam-ticket-monitor`.
2. Click its URL and append `/healthz/live`. The response should contain
   `"status":"alive"`.
3. Change the path to `/healthz/ready`. It should return HTTP 200 after startup.
4. Change the path to `/docs` to open the interactive FastAPI documentation.
5. In `/docs`, expand `GET /api/v1/monitor/status`, click **Try it out**, enter the
   saved key in `X-API-Key`, and click **Execute**.
6. To request one immediate check, do the same for
   `POST /api/v1/monitor/check`. This does not bypass the Firestore deduplication
   rules or deliberately send test emails.
7. Return to the Cloud Run service and open **Logs**. Confirm that the monitor
   started and availability checks are completing.
8. Open **Firestore → Data**. After the first successful HR&CE response, the
   `arunachalam_ticket_monitor` collection should appear automatically.

No availability email is expected while all dates are closed. A temporary HR&CE
timeout or invalid response is logged as a failure and does not stop the service,
erase the last successful state, or create a false “sold out” result. After three
consecutive monitor failures, the service sends one warning email and keeps
retrying.

The useful Cloud Logging fields are `outcome`, `available_dates`, `source_url`,
`consecutive_failures`, and the request trace ID. Prometheus-compatible process
and HTTP metrics are available at `/metrics`.

### 9. Deploy a later code update

Recreate the ZIP with step 2, upload it to Cloud Shell again, unzip it with the
same commands, restore the shell variables from step 7, and rerun the `gcloud run
deploy` command. Cloud Run creates a new revision while Firestore keeps the
availability and alert history.

If the Gmail app password is rotated, add a new version to the existing Secret
Manager secret and change the deploy flag from `:1` to the new version, such as
`:2`.

Official references: [deploy Cloud Run from source](https://docs.cloud.google.com/run/docs/deploying-source-code),
[create a Firestore database](https://docs.cloud.google.com/firestore/native/docs/manage-databases),
[grant Secret Manager access](https://docs.cloud.google.com/secret-manager/docs/manage-access-to-secrets),
and [Google app passwords](https://support.google.com/accounts/answer/185833).

## Optional local development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, authenticate Application Default Credentials to a test Firestore
project, and start the service with `uvicorn app.main:app --reload --port 8080`.
Run the test suite with `pytest -q`.

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
