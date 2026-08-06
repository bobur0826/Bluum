# Deploying Bluum

Assumes a fresh Ubuntu-ish VM (e.g. UZCLOUD) with a domain pointed at it.

```bash
# 1. System packages
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx postgresql

# 2. App
sudo mkdir -p /opt/bluum && sudo chown $USER /opt/bluum
git clone https://github.com/bobur0826/Bluum.git /opt/bluum
cd /opt/bluum/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY, SECRET_KEY, DATABASE_URL, set FLASK_DEBUG=0

# 3. Postgres (skip if using a managed DATABASE_URL instead)
sudo -u postgres createuser bluum
sudo -u postgres createdb bluum -O bluum
sudo -u postgres psql -c "ALTER USER bluum PASSWORD 'set-a-real-password';"
# put that same user/password/db name into DATABASE_URL in .env

# 4. Run as a service
sudo cp deploy/bluum.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now bluum

# 5. Nginx + HTTPS
sudo cp deploy/nginx.conf /etc/nginx/sites-available/bluum
sudo sed -i "s/YOUR_DOMAIN_HERE/yourdomain.uz/" /etc/nginx/sites-available/bluum
sudo ln -s /etc/nginx/sites-available/bluum /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.uz   # gets the cert, rewrites the config for HTTPS
```

## After deploying

- `sudo systemctl status bluum` / `journalctl -u bluum -f` — check it's running / see logs
- `sudo systemctl restart bluum` — after a `git pull` + code change
- Certbot auto-renews via its own systemd timer — nothing to do there
- `.env` never gets committed (gitignored) — copy it to the server by hand, not via git

## Before going live with real patients

- [ ] Real `SECRET_KEY` set (`.env.example` has the generator command)
- [ ] `FLASK_DEBUG=0` — confirms the app refuses to boot without the above
- [ ] `DATABASE_URL` pointing at Postgres, not SQLite
- [ ] Domain's DNS actually points at the VM before running certbot
- [ ] Volume/disk encryption enabled on the UZCLOUD VM (ask them how — provider-side setting, not app code)
- [ ] `ESKIZ_EMAIL`/`ESKIZ_PASSWORD` set if you want real SMS instead of on-screen dev codes
