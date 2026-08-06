# AWS Deployment Guide — Forensic Delay Analysis Toolkit (COAIR)

This folder contains **everything needed to run the toolkit on AWS with
zero changes to the application**: same UI, same 19 modules, same
charts, gantts, exports and audit trail you use today. The only thing
that changes relative to the Streamlit Cloud pilot is **where it runs**
and **which AI credential is provided**: the managed NVIDIA free
endpoint is not configured, and a **Gemini API key is introduced
through one single configuration layer** (AWS Secrets Manager). No code
edit is required for that — the app already reads `GEMINI_API_KEY` /
`GOOGLE_API_KEY` from the environment and pre-fills the Gemini
credential for the analyst.

---

## What's in this folder

| File | Purpose |
| --- | --- |
| `DEPLOYMENT_GUIDE.md` | This document — the narrative, every step. |
| `Dockerfile` | Builds the production image from the unchanged repo. |
| `entrypoint.sh` | Renders secrets → `.streamlit/secrets.toml` at container start; refuses to serve without a password. |
| `config.toml` | Streamlit server settings (400 MB uploads, headless). |
| `docker-compose.yml` + `secrets.env.example` | Run the exact production container locally before AWS. |
| `cloudformation.yaml` | The whole AWS stack as one template: ECS Fargate, ALB, security groups, logs, IAM. |
| `deploy.sh` | The one routine command after setup: build → push → roll. |

## Architecture (what you are building)

```
                    Internet (or COAIR VPN CIDR only)
                              │
                    ┌─────────▼──────────┐
                    │  Application Load  │  HTTPS (ACM cert)
                    │  Balancer          │  websocket idle 3600 s
                    │  sticky sessions   │  health: /_stcore/health
                    └─────────┬──────────┘
                              │ :8501 (ALB SG → task SG only)
                    ┌─────────▼──────────┐
                    │  ECS Fargate task  │  1 vCPU / 4 GB
                    │  ┌──────────────┐  │
                    │  │ Streamlit app│  │  the repo, unchanged
                    │  │ (this repo)  │  │  logs → CloudWatch
                    │  └──────────────┘  │
                    └─────────┬──────────┘
                              │ at container start only
                    ┌─────────▼──────────┐
                    │  Secrets Manager   │  ONE secret:
                    │  delay-toolkit/app │  APP_PASSWORD
                    └────────────────────┘  GEMINI_API_KEY
```

Design decisions, stated so your team can challenge them:

- **The app ships as-is.** All ~20,500 engine lines and ~8,250 UI lines
  run unmodified. The container is the integration boundary COAIR asked
  for — anything that can host a container and pass environment
  variables can run this.
- **One task by default.** Analyst decisions (adopted paths, key-date
  justifications, TIA events, path-gantt adjustments) live in Streamlit
  session state — in the task's memory, per browser tab. Sticky
  sessions are configured so scaling out works, but a task restart still
  ends its sessions (the app now warns about this on the intake page).
  For a team of analysts, one 4 GB task is comfortably enough; scale the
  task size before you scale the count.
- **Fail closed, on purpose.** The repository's own fail-closed gate is
  keyed to Streamlit Cloud's filesystem and does not trip on AWS — an
  unconfigured container would serve **open**. `entrypoint.sh` closes
  that hole: it **refuses to start** unless `APP_PASSWORD` is set (or
  `ALLOW_PUBLIC=true` is set deliberately).
- **One secret, one layer.** Both credentials live in a single Secrets
  Manager secret, injected as environment variables by ECS, rendered to
  `secrets.toml` by the entrypoint. Nothing is baked into the image, no
  credential appears in the task definition, the template, this repo, or
  the browser.

### How the Gemini "single layer" reaches the analyst

The credentials panel in the app resolves keys in this order (existing
behaviour, no change):

1. If `NVIDIA_API_KEY` is configured → managed NVIDIA default. **In
   COAIR we simply never set it**, so this path is off.
2. Otherwise the analyst sees the provider dropdown. Choosing
   **Google (Gemini)** pre-fills the key field from `GEMINI_API_KEY`
   (falling back to `GOOGLE_API_KEY`) — both are exported by
   `entrypoint.sh`. The analyst clicks nothing else and never sees,
   types, or handles the key itself.

The one UX seam to know: the dropdown's first entry is NVIDIA, so an
analyst selects "Google (Gemini)" once per session. If COAIR wants
Gemini to be the zero-click managed default exactly as NVIDIA was, that
is a small, contained change in `views/_shared.py`
(`ai_credentials_panel` / `resolve_ai_credentials`) — deliberately
**not** made here because the brief was "nothing changes in the
system". Ask and it ships as a separate reviewed commit.

---

## Prerequisites

- An AWS account with rights for: ECR, ECS, EC2 (security groups),
  ELBv2, IAM (two roles), CloudWatch Logs, Secrets Manager,
  CloudFormation.
- AWS CLI v2 configured (`aws configure`), Docker Desktop (or any
  Docker engine) locally.
- A Gemini API key for the COAIR workspace
  (aistudio.google.com → API keys).
- Optional but strongly recommended: a domain/subdomain and an ACM
  certificate in the deployment region for HTTPS — analysts type a
  password into this app.

Set two variables used by every command below:

```bash
export AWS_REGION=eu-west-1          # your region
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
```

---

## Step 0 — Prove the container locally (10 minutes, catches 90 % of issues)

From the repository root:

```bash
cp deploy/aws/secrets.env.example deploy/aws/secrets.env
# edit deploy/aws/secrets.env: set APP_PASSWORD and GEMINI_API_KEY
docker compose -f deploy/aws/docker-compose.yml up --build
```

Open <http://localhost:8501> and verify, in order:

1. The **password gate** appears; your `APP_PASSWORD` gets you in.
2. **Data Intake** → "Use bundled sample programmes" loads the Harbour
   Point pair.
3. **As-Planned vs As-Built** → adopt a path → the interactive path
   gantt renders inside the expander (this exercises the custom
   component that historically breaks first on new hosts).
4. Any module → **AI Narrative Report** → provider "Google (Gemini)" —
   the key field arrives **pre-filled**. Generate one narrative: this
   is the single end-to-end proof of the COAIR Gemini layer.
5. Download one Excel export (exercises the PNG rasteriser + openpyxl).

Only proceed to AWS when all five pass. `secrets.env` is gitignored —
never commit a filled copy.

## Step 1 — Create the image registry (once)

```bash
aws ecr create-repository \
  --repository-name delay-toolkit \
  --image-scanning-configuration scanOnPush=true \
  --region $AWS_REGION
```

## Step 2 — Build and push the first image

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com

# --platform matters: Apple-Silicon laptops otherwise build arm64
# images that default Fargate will not start.
docker build --platform linux/amd64 \
  -f deploy/aws/Dockerfile \
  -t $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/delay-toolkit:v1 .

docker push $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/delay-toolkit:v1
```

## Step 3 — Create THE secret (the single configuration layer)

```bash
aws secretsmanager create-secret \
  --name delay-toolkit/app \
  --description "Delay toolkit: access password + COAIR Gemini key" \
  --secret-string '{
    "APP_PASSWORD": "choose-a-strong-passphrase",
    "GEMINI_API_KEY": "AIza...your-coair-key"
  }' \
  --region $AWS_REGION
```

Note the returned `ARN` — the stack needs it. This is the **only place
either credential exists**. Rotating the Gemini key later is:

```bash
aws secretsmanager update-secret --secret-id delay-toolkit/app \
  --secret-string '{"APP_PASSWORD":"...","GEMINI_API_KEY":"new-key"}' \
  --region $AWS_REGION
aws ecs update-service --cluster delay-toolkit --service delay-toolkit \
  --force-new-deployment --region $AWS_REGION   # tasks pick it up on restart
```

## Step 4 — Launch the stack

Find a VPC and two public subnets (the default VPC works):

```bash
aws ec2 describe-vpcs   --query "Vpcs[?IsDefault].VpcId" --output text
aws ec2 describe-subnets --filters Name=default-for-az,Values=true \
  --query "Subnets[].SubnetId" --output text
```

Then:

```bash
aws cloudformation deploy \
  --stack-name delay-toolkit \
  --template-file deploy/aws/cloudformation.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    VpcId=vpc-xxxxxxxx \
    "SubnetIds=subnet-aaaa,subnet-bbbb" \
    ImageUri=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/delay-toolkit:v1 \
    SecretArn=arn:aws:secretsmanager:...:secret:delay-toolkit/app-XXXXXX \
    AllowedCidr=203.0.113.0/24 \
    CertificateArn=arn:aws:acm:...   # omit for HTTP-only pilot
```

Two parameters your team should consciously set rather than default:

- **`AllowedCidr`** — lock to the COAIR office/VPN range. The password
  gate is the second line of defence, not the first.
- **`CertificateArn`** — without it the app serves plain HTTP and the
  password crosses the wire unencrypted. Fine inside a private network
  pilot; not fine on the open internet.

Get the URL:

```bash
aws cloudformation describe-stacks --stack-name delay-toolkit \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" \
  --output text
```

First boot takes ~2 minutes (image pull + health-check grace). If you
supplied a certificate, add a DNS CNAME from your subdomain to the ALB
DNS name.

## Step 5 — Acceptance test on AWS

Repeat the five checks from Step 0 against the ALB URL, plus:

6. Hard-refresh mid-analysis and confirm the intake page's
   **session-reload warning** matches reality (state resets — this is
   inherent to the app, not to AWS).
7. Upload a real client XER (~10-50 MB) to confirm the 400 MB body
   limit passes through the ALB.
8. `aws logs tail /ecs/delay-toolkit --follow --region $AWS_REGION` —
   watch one full analyst walk; there should be no tracebacks.

## Step 6 — Routine updates thereafter

```bash
AWS_REGION=$AWS_REGION ./deploy/aws/deploy.sh v1.0.1
```

That script builds, pushes, re-registers the task definition with the
new image and rolls the service with zero input. Tag with the git SHA
(default) or a release tag. Rollback = run it again with the previous
tag.

---

## Operations notes

**Sizing.** 1 vCPU / 4 GB handles a full Harbour Point walk plus
multi-XER client programmes comfortably. First lever if analysts load
10k-activity programmes: `TaskMemory=8192` (a stack parameter — no
rebuild). CPU spikes are short (CPM passes, PNG rasterising).

**Cost, monthly, eu-west-1 order of magnitude:** Fargate 1×(1 vCPU/4 GB)
≈ $36; ALB ≈ $20 + LCU; CloudWatch/ECR/Secrets ≈ $3-5. **≈ $60/month**,
plus Gemini usage billed by Google to the COAIR key.

**Logs.** Everything the app prints lands in CloudWatch
`/ecs/delay-toolkit` (30-day retention set in the template).

**No persistence to back up.** The app deliberately stores nothing
server-side between sessions — programmes are uploaded per session,
outputs are downloaded by the analyst. There is no database and no
volume. (The chain-of-custody register on the intake page downloads to
the analyst's machine.) If COAIR later wants uploads to persist, that
is an S3 + state-model feature, not a deployment setting.

**Scaling out (read before raising DesiredCount).** Sticky sessions pin
each browser to one task, so N tasks work — but there is no shared
session store; a deploy or task recycle ends the sessions on that task.
Deploy at quiet hours; the `deploy.sh` roll is graceful (new task
healthy before old drains, 60 s deregistration).

## Troubleshooting

| Symptom | Cause → fix |
| --- | --- |
| Task stops immediately, log says `FATAL: APP_PASSWORD is not set` | The secret isn't reaching the task: check the `SecretArn` parameter and that the secret's JSON has exactly the keys `APP_PASSWORD`, `GEMINI_API_KEY`. |
| `exec format error` in task logs | arm64 image from an Apple-Silicon build — rebuild with `--platform linux/amd64` (deploy.sh does this). |
| ALB target flapping unhealthy | Health path must be `/_stcore/health`; give `HealthCheckGracePeriodSeconds` its 120 s on cold start. |
| App loads, then "connection lost" toasts after inactivity | ALB idle timeout was lowered — the template sets 3600 s for the websocket; keep it. |
| Upload of a large XER fails at ~200 MB | The image's `config.toml` sets `maxUploadSize = 400`; if you fork the config, keep that line. |
| Gemini field empty in the provider panel | `GEMINI_API_KEY` missing from the secret, or the service wasn't rolled after a secret update (`--force-new-deployment`). |
| Analysts see the NVIDIA managed banner | Someone set `NVIDIA_API_KEY` in the secret — remove it; COAIR policy is Gemini-only. |
| Password page loops with wrong-password on the right password | Special characters mangled by shell quoting when the secret was created — re-create the secret string from a file: `--secret-string file://secret.json`. |

## Security checklist (sign off before go-live)

- [ ] `AllowedCidr` restricted to COAIR ranges, not `0.0.0.0/0`
- [ ] HTTPS via ACM certificate; HTTP redirects (automatic when
      `CertificateArn` is set)
- [ ] Secret exists only in Secrets Manager; `secrets.env` never
      committed (gitignored)
- [ ] `NVIDIA_API_KEY` absent everywhere (policy: Gemini only)
- [ ] ECR image scanning on (step 1 enabled it); review findings
- [ ] Analysts briefed: AI narratives send programme figures/activity
      names to Google's API under the COAIR key — the in-app privacy
      note states this; confirm it matches COAIR's data-processing
      position for each matter
- [ ] The repository is public on GitHub — confirm that remains
      acceptable, or mirror to a private COAIR repo and point Step 2's
      build at it (nothing else changes)

## Alternative: single EC2 instance (smallest possible footprint)

If ECS is more machinery than COAIR wants, the same container runs on
one `t3.large` with Docker:

```bash
# on the instance (Amazon Linux 2023), after installing docker + login to ECR:
sudo docker run -d --name delay-toolkit --restart unless-stopped \
  -p 443:8501 \
  -e APP_PASSWORD='...' -e GEMINI_API_KEY='AIza...' \
  $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/delay-toolkit:v1
```

Put the instance behind its own security group (COAIR CIDR only) and
terminate TLS with a Caddy/nginx sidecar or an ALB in front. You lose
health-managed restarts across AZs and the clean roll of `deploy.sh` —
acceptable for a pilot, not for production.

---

*Prepared as part of the toolkit repository (`deploy/aws/`). The
application itself is untouched by everything in this folder — delete
the folder and the app is exactly what it was.*
