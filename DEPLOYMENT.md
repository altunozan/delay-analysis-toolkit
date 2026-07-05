# Deployment Guide

## Option 1: Streamlit Cloud (Recommended — Free)

**Pros:** Free tier available, automatic GitHub sync, 1-click deploy, HTTPS included  
**Cons:** Limited to 1 free app, free tier auto-sleeps after 7 days of inactivity

### Steps

1. **Create a GitHub account** (if you don't have one) at https://github.com/signup
2. **Create a new repository:**
   - Go to https://github.com/new
   - Name: `delay-analysis-toolkit`
   - Public or Private (your choice)
   - Click "Create repository"

3. **Push your code to GitHub** (run these commands in your project directory):
   ```bash
   git init
   git add -A
   git commit -m "Initial commit: forensic delay analysis toolkit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/delay-analysis-toolkit.git
   git push -u origin main
   ```

4. **Deploy on Streamlit Cloud:**
   - Go to https://share.streamlit.io
   - Click "New app"
   - Sign in with your GitHub account
   - Select your repo: `delay-analysis-toolkit`
   - Branch: `main`
   - Main file: `app.py`
   - Click "Deploy"

5. **Done!** Your app will be live at:
   ```
   https://your-username-delay-analysis-toolkit.streamlit.app
   ```

### Adding API Keys (for narratives)

1. Deploy the app first
2. Click the three dots (⋯) in the top-right
3. Select "Settings"
4. Go to "Secrets"
5. Add:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   OPENAI_API_KEY = "sk-..."
   GOOGLE_API_KEY = "AIzaSy..."
   ```
6. Redeploy (push to GitHub)

---

## Option 2: Railway (Free $5/month credit, then pay-as-you-go)

**Pros:** Simple, fast, good UI, persistent storage  
**Cons:** Credit runs out, not as integrated as Streamlit Cloud

### Steps

1. Go to https://railway.app
2. Sign up with GitHub
3. Create a new project → Empty Project
4. Connect your GitHub repo
5. Add environment variables under "Variables"
6. Deploy

---

## Option 3: Render (Free + $7/month)

**Pros:** Free tier with auto-sleep (no charges), simple setup  
**Cons:** Auto-sleeps free tier, slower wake-up

### Steps

1. Go to https://render.com
2. Sign up with GitHub
3. New → Web Service
4. Connect your GitHub repo
5. Build command: `pip install -r requirements.txt`
6. Start command: `streamlit run app.py --server.port 10000`
7. Add environment variables
8. Deploy

---

## Option 4: Self-Hosted on Your Server

Best for full control and custom domains.

### Linux/Ubuntu

```bash
# Install dependencies
sudo apt update
sudo apt install python3.11 python3.11-venv git nginx

# Clone repo
cd /opt
sudo git clone https://github.com/YOUR_USERNAME/delay-analysis-toolkit.git
cd delay-analysis-toolkit

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create systemd service
sudo tee /etc/systemd/system/streamlit-app.service > /dev/null <<EOF
[Unit]
Description=Streamlit Delay Analysis App
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/delay-analysis-toolkit
Environment="PATH=/opt/delay-analysis-toolkit/venv/bin"
ExecStart=/opt/delay-analysis-toolkit/venv/bin/streamlit run app.py --server.port 8501 --server.headless true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable streamlit-app
sudo systemctl start streamlit-app

# Check status
sudo systemctl status streamlit-app
```

### Nginx Reverse Proxy

```bash
sudo tee /etc/nginx/sites-available/delay-analysis > /dev/null <<EOF
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /_stcore/stream {
        proxy_pass http://localhost:8501/_stcore/stream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/delay-analysis /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Then set up HTTPS with Let's Encrypt:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

## Comparison Table

| Feature | Streamlit Cloud | Railway | Render | Self-Hosted |
|---------|-----------------|---------|--------|-------------|
| **Cost** | Free | Free + $5 credit | Free | Variable |
| **Setup Time** | 5 min | 10 min | 10 min | 30+ min |
| **HTTPS** | ✅ Auto | ✅ Auto | ✅ Auto | ⚠️ Manual |
| **Custom Domain** | ❌ | ✅ | ✅ | ✅ |
| **Auto-deploy** | ✅ (GitHub push) | ✅ | ✅ | ❌ |
| **Uptime** | ⚠️ Sleeps free tier | ✅ | ⚠️ Sleeps free | ✅ |

---

## Recommended Path

**Start:** Streamlit Cloud (easiest, works today)  
**Scale:** Move to Railway or Render as needs grow  
**Enterprise:** Self-host if you need custom domain + guaranteed uptime
