# Deployment

Two copies of the toolkit exist on purpose:

1. **The repository root** — the DEVELOPMENT copy. Runs on Streamlit
   Community Cloud (push to `main` = instant redeploy) with the managed
   NVIDIA default. Keep developing here; nothing in `deploy/` affects
   it.
2. **[`aws-package/`](aws-package/README_DEPLOY.md)** — a complete,
   SELF-CONTAINED copy for AWS hand-off: full application plus Docker,
   CloudFormation and one instruction document (`README_DEPLOY.md`).
   **NVIDIA is removed entirely in this copy — Gemini is the only
   managed AI credential.** Zip the folder and send it; the deployer
   needs nothing else:

   ```bash
   cd deploy && zip -r delay-toolkit-aws.zip aws-package -x "*/__pycache__/*" -x "*/secrets.env"
   ```

The AWS package is a SNAPSHOT (copied 2026-08-06). After significant
development on the root copy, regenerate it rather than patching both.
