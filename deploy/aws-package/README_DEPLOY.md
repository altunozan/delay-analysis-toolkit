# Deploying the Forensic Delay Analysis Toolkit to AWS
### The only document you need — read top to bottom, then follow the steps.

You have been given a **complete, self-contained package**: the full
application (every module, chart and gantt, unchanged) plus every file
needed to put it on AWS. You do not need access to any other
repository, and you must never need to edit application code — if a
step seems to require that, stop and ask the person who sent you this.

This build is **Gemini-only**: the AI features run on a Google Gemini
API key held server-side. There is no NVIDIA integration in this
package at all.

---

## 1. What you need before starting

| # | Item | Where it comes from |
| --- | --- | --- |
| 1 | **Gemini API key** | Provided by the sender (from aistudio.google.com). Treat like a password. |
| 2 | **Agreed access password** (`APP_PASSWORD`) | Agree it with the sender — analysts type it to enter the app. |
| 3 | AWS account + permissions | ECR, ECS, IAM, ELB, Secrets Manager, CloudWatch, CloudFormation. |
| 4 | On your machine | Docker Desktop and AWS CLI v2 (`aws configure` done). |
| 5 | Optional, recommended | A subdomain + ACM certificate in your region, for HTTPS. |

Golden rule: **the key and the password go into AWS Secrets Manager
(step 3) and nowhere else** — never into a file in this package, never
into git, chat, or a task definition.

## 2. Why Docker? (so you know what you're running)

The app is Python with ~15 pinned scientific libraries. It runs
correctly on exactly one combination of Python + library versions — the
one it is tested against. Docker seals the app **with** that exact
combination into one artefact (an "image"):

- The image you test on your laptop (step 0) is byte-for-byte what AWS
  runs — no "works on my machine".
- AWS (ECS Fargate) runs images natively: restarts, health checks and
  logs are managed; nobody patches a server.
- Rollback = redeploy the previous image tag, one command.

You never write Docker configuration — it's all here. You run the
commands below verbatim.

## 3. What the moving parts are

- **ECR** — AWS's registry where the built image is stored.
- **ECS Fargate** — runs the image as a managed task; restarts it if it
  dies. No servers.
- **ALB (load balancer)** — the public URL; HTTPS, health checks, and
  keeps each analyst's browser pinned to the task (analyst work lives
  in the task's memory during a session).
- **Secrets Manager** — the ONE place the password + Gemini key live.
- **CloudFormation** — one template (`cloudformation.yaml`) creates all
  of the above in a single command, and `delete-stack` removes it all.

## 4. The steps

Set these once in your shell:

```bash
export AWS_REGION=eu-west-1          # your region
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
```

### Step 0 — prove it on your laptop (10 min; catches 90 % of problems)

From this folder:

```bash
cp secrets.env.example secrets.env    # edit: set APP_PASSWORD + GEMINI_API_KEY
docker compose up --build
```

Open <http://localhost:8501> and check, in order:

1. The **password gate** appears; the agreed password gets you in.
2. **Data Intake** → toggle "Use bundled sample programmes" — the
   Harbour Point pair loads.
3. Any module's AI panel shows **"AI enabled — managed Google
   endpoint. No key needed."** — that line proves the Gemini layer
   works. Generate one narrative end-to-end. (The default model is
   `gemini-flash-latest`, which always points at Google's newest Flash
   model; a Pro option is in the dropdown.)
4. **As-Planned vs As-Built** → adopt a path → the interactive path
   gantt renders inside the "Review & adjust" expander.
5. Download one Excel export.

All five pass → continue. Any failure → fix here, not on AWS.
`Ctrl-C` stops the container.

### Step 1 — create the image registry (once)

```bash
aws ecr create-repository --repository-name delay-toolkit \
  --image-scanning-configuration scanOnPush=true --region $AWS_REGION
```

### Step 2 — build and push the image

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com

docker build --platform linux/amd64 \
  -t $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/delay-toolkit:v1 .

docker push $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/delay-toolkit:v1
```

(`--platform linux/amd64` matters on Apple-Silicon Macs — without it
Fargate refuses the image with `exec format error`.)

### Step 3 — create THE secret (the single configuration layer)

```bash
aws secretsmanager create-secret \
  --name delay-toolkit/app \
  --description "Delay toolkit: access password + Gemini key" \
  --secret-string '{
    "APP_PASSWORD": "the-agreed-passphrase",
    "GEMINI_API_KEY": "AIza...the-provided-key"
  }' \
  --region $AWS_REGION
```

Save the returned **ARN** — step 4 needs it. If the password or key
contains characters your shell mangles, put the JSON in a file and use
`--secret-string file://secret.json` (then delete the file).

### Step 4 — launch the stack

Find a VPC and two public subnets (the account's default VPC is fine):

```bash
aws ec2 describe-vpcs   --query "Vpcs[?IsDefault].VpcId" --output text
aws ec2 describe-subnets --filters Name=default-for-az,Values=true \
  --query "Subnets[].SubnetId" --output text
```

Then:

```bash
aws cloudformation deploy \
  --stack-name delay-toolkit \
  --template-file cloudformation.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    VpcId=vpc-xxxxxxxx \
    "SubnetIds=subnet-aaaa,subnet-bbbb" \
    ImageUri=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/delay-toolkit:v1 \
    SecretArn=arn:aws:secretsmanager:...:secret:delay-toolkit/app-XXXXXX \
    AllowedCidr=203.0.113.0/24 \
    CertificateArn=arn:aws:acm:...        # omit this line for an HTTP-only pilot
```

Set these two consciously, not by default:

- **`AllowedCidr`** — restrict to the organisation's office/VPN range.
  The password is the second lock, not the first.
- **`CertificateArn`** — without it the app is plain HTTP and the
  password crosses the wire unencrypted. Acceptable only inside a
  private network.

Get the URL (first boot takes ~2 minutes):

```bash
aws cloudformation describe-stacks --stack-name delay-toolkit \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" --output text
```

If you used a certificate, add a DNS CNAME from your subdomain to the
ALB DNS name.

### Step 5 — acceptance on AWS

Repeat the five checks from step 0 against the real URL, plus:

```bash
aws logs tail /ecs/delay-toolkit --follow --region $AWS_REGION
```

— walk through a couple of modules and confirm no tracebacks appear.

### Step 6 — every update after that

```bash
AWS_REGION=$AWS_REGION ./deploy.sh v1.0.1
```

builds, pushes and rolls with zero downtime. Rollback = run it with the
previous tag.

## 5. Things you must NOT do

- **Do not skip `APP_PASSWORD`.** The container refuses to start
  without it — deliberately (client schedule data is commercially
  sensitive). Do not "fix" it with `ALLOW_PUBLIC=true`; that switch is
  for demos only.
- **Do not edit application files.** Every deployment concern is a
  parameter, an env var, or a file listed below.
- **Do not widen `AllowedCidr` to `0.0.0.0/0` "temporarily".**
- **Do not commit or send a filled `secrets.env`.**

## 6. Troubleshooting (the failures that actually happen)

| Symptom | Cause → fix |
| --- | --- |
| Task stops at once; log says `FATAL: APP_PASSWORD is not set` | The secret isn't reaching the task — check `SecretArn` and that the secret JSON has exactly `APP_PASSWORD` and `GEMINI_API_KEY`. |
| `exec format error` in task logs | arm64 image — rebuild with `--platform linux/amd64`. |
| ALB target flapping unhealthy | Health path must be `/_stcore/health` (the template sets it); allow the 120 s grace on cold start. |
| "Connection lost" toasts after idle | ALB idle timeout lowered — the template sets 3600 s for the websocket; keep it. |
| Large XER upload fails ~200 MB | `config.toml` sets `maxUploadSize = 400`; keep that line. |
| AI panel asks for a key instead of showing "managed Google endpoint" | `GEMINI_API_KEY` missing from the secret, or the service wasn't rolled after a secret change (`aws ecs update-service ... --force-new-deployment`). |
| Password rejected though correct | Shell quoting mangled the secret — recreate with `--secret-string file://secret.json`. |
| App state vanished | A page reload or task restart ends the browser session — inherent to the app (it warns on the intake page), not an AWS fault. |

## 7. What "done" looks like

The stack URL loads over HTTPS; the password admits; the sample pair
loads; an AI narrative generates with "managed Google endpoint" shown;
an Excel export downloads; the logs are clean. Send the URL and
confirm to the person who gave you this package.

## 8. Costs & operations

≈ **$60/month** (Fargate 1 vCPU/4 GB ≈ $36, ALB ≈ $20, logs/registry
≈ $4) plus Gemini usage billed to the Google key. Logs live in
CloudWatch `/ecs/delay-toolkit` (30-day retention). There is **no
database and nothing to back up** — programmes are uploaded per
session and outputs download to the analyst's machine. Rotating the
Gemini key = `aws secretsmanager update-secret` + one
`--force-new-deployment`. Deleting everything =
`aws cloudformation delete-stack --stack-name delay-toolkit` (plus the
ECR repo and secret if desired).

## 9. Package contents

| File / folder | What it is |
| --- | --- |
| `app.py`, `state.py`, `buildinfo.py`, `views/`, `programme/`, `dcma/`, `path_studio/`, `rlpa_apvab_v2/`, `sample/`, `requirements.txt` | The application, complete and unchanged. Not yours to edit. |
| `README_DEPLOY.md` | This document. |
| `Dockerfile`, `.dockerignore`, `entrypoint.sh`, `config.toml` | The container: build recipe, secrets materialisation, server settings. |
| `docker-compose.yml`, `secrets.env.example` | The step-0 local proof. |
| `cloudformation.yaml` | The whole AWS environment as one template. |
| `deploy.sh` | Routine build-push-roll after first setup. |
