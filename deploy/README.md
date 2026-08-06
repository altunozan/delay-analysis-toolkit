# Deployment

The application is a standard Streamlit app and runs anywhere a
container runs. Each target environment gets its own subfolder with a
complete, self-contained kit — the app code is never modified by
anything in here.

| Folder | Target | Status |
| --- | --- | --- |
| [`aws/`](aws/DEPLOYMENT_GUIDE.md) | AWS — ECS Fargate + ALB, Secrets Manager, Gemini single-layer credential (COAIR) | Ready |

Streamlit Community Cloud (the original pilot host) needs no kit: push
to `main`, set `APP_PASSWORD` in the app's Secrets.
