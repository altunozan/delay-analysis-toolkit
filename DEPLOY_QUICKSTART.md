# 🚀 Deploy to Streamlit Cloud — 3 Steps (10 minutes)

Everything is prepared. You just need to do 3 things:

---

## Step 1: Create a GitHub Account (if you don't have one)

1. Go to https://github.com/signup
2. Enter your email, password, username
3. Verify your email
4. **Done!**

---

## Step 2: Create & Push Code to GitHub

Replace `YOUR_USERNAME` with your actual GitHub username in the commands below, then run them in your terminal:

```bash
# Navigate to your project directory
cd /Users/ozanaltun/Desktop/Claude

# Set your remote (use YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/delay-analysis-toolkit.git

# Push to GitHub
git branch -M main
git push -u origin main
```

**If you get an error:**
- First time? GitHub will ask for a login. Use your GitHub username + a Personal Access Token (PAT):
  - Go to https://github.com/settings/tokens
  - Click "Generate new token (classic)"
  - Check `repo` and `gist`
  - Copy the token
  - Paste it when GitHub asks for a password

**Verify it worked:**
- Go to https://github.com/YOUR_USERNAME/delay-analysis-toolkit
- You should see all your files there

---

## Step 3: Deploy on Streamlit Cloud

1. Go to https://share.streamlit.io (open in browser)
2. Click **"New app"** (top-right)
3. **Sign in with GitHub** and authorize
4. Fill in the form:
   - **Repository:** `YOUR_USERNAME/delay-analysis-toolkit`
   - **Branch:** `main`
   - **Main file path:** `app.py`
5. Click **"Deploy"**

**Wait:** Streamlit will build your app (2-3 minutes). You'll see a loading spinner.

**Done!** When it's ready, you'll get a live URL:
```
https://YOUR_USERNAME-delay-analysis-toolkit.streamlit.app
```

---

## How to Use It

**Upload XER files:**
1. Open the app
2. Go to **"📥 Data Intake & Inventory"** tab
3. Upload your Primavera P6 exports
4. Toggle **"Use bundled sample"** to test with sample data

**Run analyses:**
- Each tab = one module (DCMA, Critical Path, Milestones, Variance)

**Download reports:**
- Each module has an Excel export button

---

## Add API Keys (Optional — for AI Narratives)

If you want Claude/OpenAI to write narratives:

1. Go to your app: https://your-username-delay-analysis-toolkit.streamlit.app
2. Click the **⋯** (three dots, top-right)
3. Click **"Settings"**
4. Click **"Secrets"**
5. Paste this (add your actual API keys):
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   OPENAI_API_KEY = "sk-..."
   GOOGLE_API_KEY = "AIzaSy..."
   ```
6. Save

---

## Commands Quick Reference

```bash
# Check if git is set up
git remote -v

# Push updates after making changes
git add -A
git commit -m "Your message"
git push

# Check git status
git status
```

---

## Troubleshooting

**"fatal: not a git repository"**  
→ Run: `cd /Users/ozanaltun/Desktop/Claude` first

**"Repository not found"**  
→ Create the repo on GitHub first: https://github.com/new

**"Streamlit deploy fails"**  
→ Check that `requirements.txt` exists (it does ✅)  
→ Check that `app.py` is in the root directory (it is ✅)

**App won't load**  
→ Wait 3-5 minutes (first deploy can be slow)  
→ Click the "Rerun" button in the app  
→ Check the browser console (F12) for errors

---

## Next Steps

- **Update the code?** → Make changes locally, `git push origin main`, Streamlit auto-redeploys
- **Share the link?** → Just send the Streamlit URL to anyone (no login needed)
- **Custom domain?** → Upgrade to Streamlit Cloud Pro ($25/month)

---

**Questions?** See `DEPLOYMENT.md` for alternative hosting options.
