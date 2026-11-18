# Deploying OPC on Google Cloud Run and Cloudflare

This is the step-by-step plan to move OPC off Vercel, for ₹0 a month at today's size.

There are two GitHub repositories, one per folder:

| Folder | GitHub repository | What it deploys |
|---|---|---|
| `backend/` | `opc_backend_new` | The website pages and the API, on **Google Cloud Run** |
| `frontend/` | `opc_frontend` | The dashboard on **Cloudflare Pages**, and the **Cloudflare Worker** in front of the site |

The frontend repo has its own short `DEPLOY.md` for its part (steps 6 to 8 here).

---

## 1. How it fits together

```
Visitors
  │
  ├─ www.theowncollab.com ─► Cloudflare (DNS, cache, Worker "opc-site-proxy")
  │                              └─► Cloud Run service "opc-backend" (Mumbai, asia-south1)
  │                                    └─► MongoDB Atlas (free cluster)
  ├─ theowncollab.com ──────► redirected to www.theowncollab.com by the same Worker
  └─ dashboard.theowncollab.com ─► Cloudflare Pages (built from frontend/dashboard-app)

GitHub Actions (backend repo): hourly deal auto-approve, weekly database backup,
optional automatic deploy on every push.
```

**Why it's set up this way:**
- **Cloud Run runs the backend for free** at OPC's size: 2 million requests a month. It shuts down when idle, so idle time costs nothing.
- **Cloudflare sits in front.** Cloud Run can't attach your own domain in Mumbai without a paid load balancer; the free Worker does that job. Cloudflare also caches images, styles and scripts, so Google sends almost no data.
- **The dashboard is a static site**, so Cloudflare Pages hosts it for free with no traffic limit.
- **No scheduled jobs on Vercel any more.** Its free plan only allows daily jobs and is for personal, non-commercial use only. GitHub Actions runs the hourly job for free.

---

## 2. Files added for this deploy

**`backend/` (this repo):**

| File | What it's for |
|---|---|
| `Dockerfile` | How Cloud Run builds and starts the backend (Python 3.12, uvicorn on `$PORT`) |
| `.dockerignore` | Keeps tests, `.venv`, `.env`, the old `admin_meet_controls` app and these notes out of the image |
| `.gcloudignore` | Keeps the same files from being uploaded to Google at all |
| `deploy/cloudrun.env.example.yaml` | Template for the plain (not secret) settings. Copy it to `deploy/cloudrun.env.yaml` (git ignores that name). |
| `deploy/artifact-cleanup.json` | Keeps only the 2 newest app images, so storage stays inside the free 0.5 GB |
| `deploy/sources-lifecycle.json` | Deletes uploaded source code after 7 days, so that storage stays free too |
| `deploy/github-actions/cron.yml` | Hourly deal auto-approve (copy into `.github/workflows/` to turn it on) |
| `deploy/github-actions/backup.yml` | Weekly encrypted database backup (copy into `.github/workflows/` to turn it on) |
| `deploy/github-actions/deploy.yml` | Optional: deploy on every push to `main`, after the tests pass |

The workflow files sit in `deploy/github-actions/` on purpose. GitHub only runs files in `.github/workflows/`, so nothing runs until you copy them there (step 10).

**`frontend/`:**

| File | What it's for |
|---|---|
| `cloudflare/worker.js` | The Worker that sends `www.theowncollab.com` to Cloud Run and caches static files |
| `cloudflare/wrangler.toml` | The Worker's name, domains and settings |
| `dashboard-app/package.json`, script `build:pages` | Builds the dashboard to be served from the root of `dashboard.theowncollab.com` |

None of these have been run yet. Test the backend at its Cloud Run address (step 5) before you move the domain (step 8).

---

## 3. Before you start

1. **Accounts:**
   - **Google Cloud.** Add a billing account with a card. You aren't charged within the free allowance.
   - **Cloudflare**, on the free plan.
   - **GitHub**, with both repositories.
   - **Hostinger** (where the domain is registered).
   - **MongoDB Atlas.**
2. **Where to type the commands:** the easiest place is **Google Cloud Shell**, the terminal button at the top of [console.cloud.google.com](https://console.cloud.google.com). It has `gcloud` and `git` ready. To use your own computer instead, install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) and use Git Bash.
3. **For the Worker:** Node.js 22 or newer, on any computer.
4. **Have these values ready:** Gmail app password, Atlas database user and password, and your current Vercel `SECRET_KEY`. (Reusing `SECRET_KEY` keeps people signed in. A new one signs everyone out once.)
5. **Leave Vercel running** until step 8 works. It's your fallback.

In the commands below, replace `opc-prod` with your Google Cloud project ID wherever it appears.

---

## 4. Step-by-step

### Step 1: Create the Google Cloud project

1. In [console.cloud.google.com](https://console.cloud.google.com): **project picker → New project**. Name it, for example, `opc-prod`.
2. **Billing:** link the project to your billing account.
3. **Billing → Budgets & alerts → Create budget:**
   - Amount ₹200 a month, with alerts at 50%, 90% and 100%.
   - A budget only *warns* you; the instance cap in step 5 is what limits spending.
4. In Cloud Shell, set the project and region, and switch on the services OPC needs:

```bash
gcloud config set project opc-prod
gcloud config set run/region asia-south1
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

### Step 2: Get the backend code into Cloud Shell

```bash
git clone https://github.com/YOUR-GITHUB-USER/opc_backend_new.git
cd opc_backend_new
```

(On your own computer, just open a terminal in the `backend/` folder.)

### Step 3: Store the 5 secrets in Secret Manager

The free tier covers 6 active secret versions, and OPC uses 5. Run each line with the real value between the quotes:

```bash
printf '%s' 'PASTE-SECRET-KEY'     | gcloud secrets create SECRET_KEY    --data-file=-
printf '%s' 'PASTE-DB-USER'        | gcloud secrets create DB_USER       --data-file=-
printf '%s' 'PASTE-DB-PASSWORD'    | gcloud secrets create DB_PASSWORD   --data-file=-
printf '%s' 'PASTE-GMAIL-APP-PASS' | gcloud secrets create SMTP_PASSWORD --data-file=-
printf '%s' 'PASTE-CRON-SECRET'    | gcloud secrets create CRON_SECRET   --data-file=-
```

**`SECRET_KEY`:** reuse the Vercel value, or make a new one with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**`CRON_SECRET`:** make one the same way, and keep it for step 10.

Then create the account the backend runs as, and let it read those secrets (and nothing else):

```bash
gcloud iam service-accounts create opc-backend-run --display-name="OPC backend (Cloud Run)"

for s in SECRET_KEY DB_USER DB_PASSWORD SMTP_PASSWORD CRON_SECRET; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:opc-backend-run@opc-prod.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

### Step 4: Fill in the plain settings, and open the database to Cloud Run

1. **Settings file:** copy `deploy/cloudrun.env.example.yaml` to `deploy/cloudrun.env.yaml` and check each value. The table in section 5 explains them all.

   ```bash
   cp deploy/cloudrun.env.example.yaml deploy/cloudrun.env.yaml
   ```

2. **Atlas network access:** in **MongoDB Atlas → Network Access**, allow `0.0.0.0/0` (anywhere). It's probably already set, because Vercel needs the same.
   - Cloud Run has no fixed IP address; a fixed one needs Google's paid Cloud NAT.
   - That's why the database password must be long and random, and the database user should only have **readWrite** on OPC's database.
3. **Atlas region:** the backend connects to the cluster at `opc.fimitv0.mongodb.net` (set in `database/config.py`). If that cluster isn't in **Mumbai** (AWS `ap-south-1`), every database call travels further. That's fine to start. Later you can create a free Mumbai cluster, copy the data over (step 10's backup can do it) and change that one line.

### Step 5: Deploy the backend to Cloud Run

From the backend folder:

```bash
gcloud run deploy opc-backend \
  --source . \
  --region asia-south1 \
  --service-account opc-backend-run@opc-prod.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 80 \
  --timeout 60 \
  --env-vars-file deploy/cloudrun.env.yaml \
  --set-secrets "SECRET_KEY=SECRET_KEY:latest,DB_USER=DB_USER:latest,DB_PASSWORD=DB_PASSWORD:latest,SMTP_PASSWORD=SMTP_PASSWORD:latest,CRON_SECRET=CRON_SECRET:latest"
```

What happens:
- **First run:** it asks to create an Artifact Registry repository named `cloud-run-source-deploy`; answer **Y**.
- **Build:** Google builds the image from the `Dockerfile` (a few minutes) and starts the service.
- **Address:** at the end it prints a **Service URL**, like `https://opc-backend-abc123xyz-el.a.run.app`. Keep it for step 8.

**What the flags do:**
- `--min-instances 0`: nothing runs while nobody visits, so idle costs ₹0. The first visit after a quiet spell takes about 2–4 seconds.
- `--max-instances 2`: the cap on spending. Even a traffic spike can't run more than 2 servers.
- `--allow-unauthenticated`: it's a public website.

**Test it at the Service URL before going further:**
- `/` and `/brands` show the new website.
- `/schedule-a-meet` loads tomorrow's times. This also proves the database connection works.
- `/docs` shows the API list.
- In **Cloud Run → opc-backend → Logs**, there are no red errors.

**Keep storage inside the free tier** (run once):

```bash
gcloud artifacts repositories set-cleanup-policies cloud-run-source-deploy \
  --location=asia-south1 --policy=deploy/artifact-cleanup.json --no-dry-run

gcloud storage buckets update gs://run-sources-opc-prod-asia-south1 \
  --lifecycle-file=deploy/sources-lifecycle.json
```

If the second command says the bucket doesn't exist, find the exact `run-sources-…` bucket name under **Cloud Storage → Buckets** and use that.

**Deploying again later:** this short command keeps all the settings, secrets and limits:

```bash
gcloud run deploy opc-backend --source . --region asia-south1
```

**Changing one setting without a full deploy:**

```bash
gcloud run services update opc-backend --region asia-south1 --update-env-vars STAFF_OWNER_EMAILS=ceo@theowncollab.com,ops@theowncollab.com
```

**Changing a secret:** add a new version, then point the service at it:

```bash
printf '%s' 'NEW-VALUE' | gcloud secrets versions add SMTP_PASSWORD --data-file=-
gcloud run services update opc-backend --region asia-south1 --update-secrets SMTP_PASSWORD=SMTP_PASSWORD:latest
```

Then disable the old version under **Secret Manager → SMTP_PASSWORD**. Only 6 active versions are free.

### Step 6: Put the dashboard on Cloudflare Pages

From the frontend repo (also in `frontend/DEPLOY.md`):

1. **Cloudflare → Workers & Pages → Create → Pages → Connect to Git:** pick `opc_frontend`, branch `main`.
2. **Build settings:**
   - Framework preset: **None**
   - Root directory: `dashboard-app`
   - Build command: `npm ci && npm run build:pages`
   - Build output directory: `dist`
3. **Environment variables (Production):**
   - `VITE_API_BASE_URL` = `https://www.theowncollab.com`
   - `VITE_WEB_APP_URL` = `https://www.theowncollab.com/`
   - `NODE_VERSION` = `22`

   **Without `VITE_API_BASE_URL`, the dashboard shows sample data instead of real accounts.**
4. **Save and Deploy.** It gets a `*.pages.dev` address. The domain is added in step 8, after Cloudflare manages your DNS.

From then on, every push to `main` in the frontend repo rebuilds the dashboard, and pull requests get preview links.

### Step 7: Move the domain's DNS to Cloudflare (the domain stays at Hostinger)

1. **Cloudflare → Add a domain →** `theowncollab.com` → **Free** plan.
2. Cloudflare copies your existing DNS records. **Compare them with Hostinger's list** before continuing:
   - **Email records** (MX, and TXT such as SPF and DKIM) must all be there.
   - **Google site-verification TXT records** must be there.
   - **Leave the `www` and `@` records pointing at Vercel for now,** so the site keeps working during the move.
3. **In Hostinger hPanel → Domains → theowncollab.com:**
   - If **DNSSEC** is on, turn it off first.
   - Then **Nameservers → Change → Use custom nameservers**, and paste the two nameservers Cloudflare shows.
4. **Wait until Cloudflare shows the domain as Active.** It's often minutes, at most a day. The site keeps working on Vercel meanwhile.
5. **Cloudflare → SSL/TLS → Overview:** set the mode to **Full (strict)**.

### Step 8: Switch the site to Cloud Run

This takes a few minutes. Do it at a quiet time.

1. In `frontend/cloudflare/wrangler.toml`, set `ORIGIN_URL` to the Service URL from step 5, with no trailing slash.
2. **In Cloudflare → DNS, delete the old `www` and `@` (theowncollab.com) records** that point to Vercel. A Worker can't take over a name that still has a record.
3. **Deploy the Worker** from `frontend/cloudflare/`:

   ```bash
   npx wrangler login
   npx wrangler deploy
   ```

   This creates the Worker, attaches `www.theowncollab.com` and `theowncollab.com`, and makes their certificates.

   **Without the command line:**
   1. **Workers & Pages → Create → Worker**, and paste `worker.js`.
   2. Under **Settings → Variables and secrets**, add `ORIGIN_URL`, `SITE_HOST` and `APEX_HOST`, with the values from `wrangler.toml`.
   3. Under **Settings → Domains & Routes → Add → Custom domain**, add `www.theowncollab.com`, then `theowncollab.com`.
4. **Dashboard domain:** in the Pages project from step 6, go to **Custom domains → Set up a custom domain** and add `dashboard.theowncollab.com`.
5. **Check:**
   - `https://theowncollab.com` jumps to `https://www.theowncollab.com`.
   - The pages load.
   - Booking a meeting works.
   - Signing in takes you to `https://dashboard.theowncollab.com/`, and your deals load there.

### Step 9: Update the Google sign-in settings

In the Google Cloud project that owns the OAuth client (client ID `828246651523-…`), go to **APIs & Services → Credentials →** that OAuth client **→ Authorized JavaScript origins**, and add:
- `https://www.theowncollab.com`
- `https://theowncollab.com`
- `https://dashboard.theowncollab.com`
- `http://localhost:5173` (local dashboard)
- `http://127.0.0.1:8000` (local backend)

Remove any Vercel addresses after step 13. For YouTube verification, also follow the YouTube steps in `DEVELOPER_GUIDE.md` (enable the YouTube Data API, add the scope, test users).

### Step 10: Turn on the hourly job and the weekly backup (GitHub Actions)

1. **In the backend repo on GitHub → Settings → Secrets and variables → Actions → New repository secret,** add:
   - `SITE_URL` = `https://www.theowncollab.com`
   - `CRON_SECRET` = the same value as in step 3
   - `MONGODB_URI` = `mongodb+srv://DB_USER:DB_PASSWORD@opc.fimitv0.mongodb.net/?appName=OPC` (with the real user and password)
   - `BACKUP_PASSPHRASE` = a long password that encrypts the backups. Keep it somewhere safe: without it a backup can't be opened.
2. **Copy** `deploy/github-actions/cron.yml` and `deploy/github-actions/backup.yml` into `.github/workflows/`, then commit and push.
3. **Run each once:** **Actions →** the workflow **→ Run workflow**, and check it finishes green.

**Good to know:**
- Scheduled runs only happen on the default branch, and can start a few minutes late.
- In a **public** repo, GitHub pauses schedules after 60 days without commits. Keep the repo private: the backups hold personal data anyway.
- An hourly run uses about 720 of the 2,000 free GitHub minutes a month.

**To restore a backup:**
1. Download it from the run's **Artifacts**.
2. Decrypt it, then load it into the database. Restoring into the live database overwrites data, so try a spare Atlas cluster first:

```bash
gpg --decrypt opc-2026-11-23.archive.gz.gpg > opc.archive.gz
mongorestore --uri="mongodb+srv://USER:PASSWORD@CLUSTER/" --archive=opc.archive.gz --gzip
```

### Step 11 (optional): Deploy automatically on every push

So you don't run step 5 by hand. GitHub proves who it is to Google, so no Google key is stored in GitHub.

```bash
PROJECT_ID=opc-prod
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
REPO=YOUR-GITHUB-USER/opc_backend_new
DEPLOYER=github-deployer@$PROJECT_ID.iam.gserviceaccount.com

gcloud services enable iamcredentials.googleapis.com
gcloud iam service-accounts create github-deployer --display-name="GitHub deploys"

gcloud iam workload-identity-pools create github --location=global --display-name="GitHub"
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$REPO'"

# Only this repository may act as the deployer.
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"

# What the deployer may do: deploy from source and attach the runtime account.
for role in roles/run.sourceDeveloper roles/serviceusage.serviceUsageConsumer roles/cloudbuild.builds.editor roles/artifactregistry.writer roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOYER" --role="$role"
done
gcloud iam service-accounts add-iam-policy-binding "opc-backend-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --member="serviceAccount:$DEPLOYER" --role=roles/iam.serviceAccountUser

echo "GCP_WORKLOAD_IDENTITY_PROVIDER = projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github"
```

1. Add three repository secrets on GitHub:
   - `GCP_PROJECT_ID` = `opc-prod`
   - `GCP_WORKLOAD_IDENTITY_PROVIDER` = the line printed by the last command
   - `GCP_DEPLOY_SERVICE_ACCOUNT` = `github-deployer@opc-prod.iam.gserviceaccount.com`
2. Copy `deploy/github-actions/deploy.yml` into `.github/workflows/` and push. It runs the tests, then deploys.
3. If the first run fails with *permission denied*, the error names the missing role. Add it with the same `add-iam-policy-binding` command.
4. **Disconnect Vercel from the GitHub repos** (step 13), or every push deploys to both places.

### Step 12: Monitoring (free)

- **[UptimeRobot](https://uptimerobot.com):** add an HTTP monitor for `https://www.theowncollab.com/`, every 5 minutes, alerting your email. It also usually keeps the backend awake, so visitors rarely wait for it to start.
- **Errors:** check **Cloud Run → opc-backend → Logs**. Up to 50 GB of logs a month are free.
- **Spend:** check **Billing → Reports** once a week for the first month.

### Step 13: Retire Vercel (about a week after step 8)

1. In each Vercel project (the backend, `opc_frontend`, and `admin_meet_controls` if you no longer use it), remove the custom domains.
2. **Settings → Git → Disconnect**, so pushes stop deploying there.
3. Delete the projects, which also deletes their stored environment variables.
4. In Google sign-in settings (step 9), remove any `vercel.app` origins.

`admin_meet_controls` is the older, separate meeting tool. The team console's **Meetings** page replaces it, which is why it's left out of the Cloud Run image.

### If something goes wrong (rollback)

- **A bad deploy:** in **Cloud Run → opc-backend → Revisions → Manage traffic**, send 100% to the previous revision. It takes seconds.
- **The new setup itself:** until step 13, Vercel is still there.
  1. In Cloudflare, remove the Worker's two custom domains.
  2. Add back `www` (CNAME `cname.vercel-dns.com`) and `@` (A `76.76.21.21`). Use the values your Vercel project shows.

---

## 5. Every setting and secret

### A. Secrets in Google Secret Manager (attached to Cloud Run in step 5)

| Name | What it is | Where to get it |
|---|---|---|
| `SECRET_KEY` | Signs everyone's sign-in tokens. Without it, the code falls back to a built-in key that isn't secret. | Your Vercel value, or `secrets.token_hex(32)` |
| `DB_USER` | MongoDB Atlas database user | Atlas → Database Access |
| `DB_PASSWORD` | That user's password | Atlas → Database Access |
| `SMTP_PASSWORD` | Gmail **app password** for `SMTP_USER` | Google Account → Security → App passwords |
| `CRON_SECRET` | Lets only the scheduled job call `/cron/deals/auto-approve` | Make a random one |

### B. Plain settings on Cloud Run (`deploy/cloudrun.env.yaml`)

| Name | Value | What it does |
|---|---|---|
| `ENVIRONMENT` | `PRODUCTION` | Anything but `DEVELOPMENT`, which lets localhost call the API |
| `ALGORITHM` | `HS256` | How sign-in tokens are signed |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | How long a sign-in lasts before a silent refresh |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | How long before someone must sign in again |
| `GOOGLE_CLIENT_ID` | `828246651523-ulnokv5h94loanmj3pd8t8ud6kc72ov5.apps.googleusercontent.com` | Google sign-in and YouTube verification (public) |
| `SMTP_SERVER` | `smtp.gmail.com` | Email server |
| `SMTP_PORT` | `587` | Email port |
| `SMTP_USER` | `opc.owncollab@gmail.com` | The Gmail account that sends OPC's emails, and the team inbox for forms |
| `MEET_FROM_EMAIL` | `support@theowncollab.com` | Optional: the address shown to people booking a meeting (defaults to `SMTP_USER`) |
| `WEB_APP_URL` | `https://www.theowncollab.com` | The website's address (allowed to call the API) |
| `DASHBOARD_URL` | `https://dashboard.theowncollab.com/` | Where sign-in sends people |
| `DASHBOARD_ORIGINS` | `https://dashboard.theowncollab.com` | Other sites allowed to call the API, comma-separated |
| `STAFF_OWNER_EMAILS` | `ceo@theowncollab.com` | Who owns the team console; they add the rest of the team there |

### C. Don't set these

| Name | Why not |
|---|---|
| `PORT` | Cloud Run sets it |
| `API_BASE_URL` | Not needed: the website calls the API on its own address |
| `GSCRIPT_URL` | The old Google Apps Script meeting scheduler is gone |
| `APPLE_SERVICES_ID` | Sign in with Apple was removed |
| `EMAIL_USER`, `EMAIL_PASSWORD` | Only used by the old `admin_meet_controls` app, which isn't deployed here |

### D. GitHub Actions secrets (backend repo → Settings → Secrets and variables → Actions)

| Name | Used by | Value |
|---|---|---|
| `SITE_URL` | `cron.yml` | `https://www.theowncollab.com` |
| `CRON_SECRET` | `cron.yml` | Same as the Secret Manager value |
| `MONGODB_URI` | `backup.yml` | `mongodb+srv://USER:PASSWORD@opc.fimitv0.mongodb.net/?appName=OPC` |
| `BACKUP_PASSPHRASE` | `backup.yml` | A long password that encrypts the backups |
| `GCP_PROJECT_ID` | `deploy.yml` (optional) | `opc-prod` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `deploy.yml` (optional) | `projects/NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `deploy.yml` (optional) | `github-deployer@opc-prod.iam.gserviceaccount.com` |

### E. Cloudflare Pages environment variables (frontend repo's dashboard)

| Name | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://www.theowncollab.com` (required, or the dashboard shows sample data) |
| `VITE_WEB_APP_URL` | `https://www.theowncollab.com/` |
| `NODE_VERSION` | `22` |
| `VITE_GOOGLE_CLIENT_ID` | Optional; the dashboard already knows the public ID |

### F. Cloudflare Worker settings (`frontend/cloudflare/wrangler.toml`, not secret)

| Name | Value |
|---|---|
| `ORIGIN_URL` | The Cloud Run Service URL from step 5 |
| `SITE_HOST` | `www.theowncollab.com` |
| `APEX_HOST` | `theowncollab.com` |

---

## 6. What's free and what isn't

| Service | Free allowance | OPC's use |
|---|---|---|
| Cloud Run | 2 million requests, 180,000 CPU-seconds and 360,000 GB-seconds a month | Far below, at today's traffic |
| Cloud Build | 2,500 build minutes a month | A few minutes per deploy |
| Artifact Registry | 0.5 GB storage | 2 images kept, by the clean-up policy |
| Secret Manager | 6 active secret versions | 5 |
| Cloud Logging | 50 GB a month | Tiny |
| Cloudflare (DNS, cache, Pages, Worker) | Free plan; Worker 100,000 requests a day; Pages 500 builds a month | Well within |
| MongoDB Atlas (free cluster) | 512 MB storage | Plenty for thousands of users |
| GitHub Actions (private repo) | 2,000 minutes a month | About 750 |
| UptimeRobot | 50 monitors, 5-minute checks | 1 |

**What can still cost money:**
- **The domain renewal** at Hostinger, once a year.
- **A few rupees** of Google data transfer for pages and API answers sent to India. Cloudflare's cache covers the heavy files.
- **Growth well beyond a few lakh page views a month.**

Free tiers change. Recheck each provider's pricing page before you sign up.

---

## 7. Go-live checklist

- [ ] `https://www.theowncollab.com` loads, and `https://theowncollab.com` redirects to it
- [ ] Schedule a meet shows tomorrow's times, and a booking appears in the team console under Meetings
- [ ] Contact and Register an event forms arrive in the team inbox
- [ ] Sign in with Google goes to `https://dashboard.theowncollab.com/`, and real data shows (not sample data)
- [ ] The team console (`/admin` on the dashboard) opens for the `STAFF_OWNER_EMAILS` account
- [ ] The **Hourly jobs** and **Weekly database backup** workflows have each run green once
- [ ] The UptimeRobot monitor is green
- [ ] Billing budget alert is set
- [ ] Vercel retired (a week later)

**Keeping the two copies of the website in sync:** the live pages are served from **this repo's** `templates/` and `static/` folders. The frontend repo keeps an identical copy for local work (`node server.js`). After changing the site, copy the changed files from `frontend/` into `backend/` as well.
