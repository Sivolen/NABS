#!/bin/bash

set -e

echo "=== 🛠 Starting NABS installation ==="

# 1. Install system dependencies
echo "[1/11] Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql git nginx openssl

# 2. Create Python virtual environment
echo "[2/11] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
echo "[3/11] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Generate secrets and prepare configs
echo "[4/11] Copying config files and generating secrets..."
DB_PASSWORD=$(openssl rand -base64 14)
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
CREDENTIALS_ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

cp config_example.py config.py
cp config_example.yaml config.yaml

sed -i "s|DBPassword *= *\".*\"|DBPassword = \"$DB_PASSWORD\"|g" config.py
# TOKEN is Flask's session/CSRF secret key. CREDENTIALS_ENCRYPTION_KEY encrypts
# saved device SSH passwords - it must stay DIFFERENT from TOKEN, so rotating
# one doesn't make the other's data unreadable. Both are required - the app
# refuses to start if either is empty or too short.
sed -i "s|TOKEN *= *\".*\"|TOKEN = \"$TOKEN\"|g" config.py
sed -i "s|CREDENTIALS_ENCRYPTION_KEY *= *\".*\"|CREDENTIALS_ENCRYPTION_KEY = \"$CREDENTIALS_ENCRYPTION_KEY\"|g" config.py

echo "[+] Generated DB password, TOKEN and CREDENTIALS_ENCRYPTION_KEY in config.py"

# 5. Create PostgreSQL database and user
echo "[5/11] Creating PostgreSQL database and user..."
sudo -u postgres psql -c "CREATE DATABASE nabs_db;"
sudo -u postgres psql -c "CREATE USER nabs_user WITH PASSWORD '$DB_PASSWORD';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE nabs_db TO nabs_user;"

# 6. Create working directories
echo "[6/11] Creating logs, backups, user_uploads, and certs directories..."
mkdir -p logs backups user_uploads certs

# 7. Run database migrations
echo "[7/11] Running Flask DB migrations..."
# export FLASK_APP=app.py
# export FLASK_ENV=production
flask db init || true
flask db migrate -m "Initial migration" || true
flask db upgrade

# 8. Generate self-signed SSL certificate
echo "[8/11] Generating self-signed SSL certificate..."
openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/C=RU/ST=RU/L=City/O=NABS/OU=IT/CN=localhost"

# 9. Install and start systemd service
echo "[9/11] Installing systemd service for NABS..."
sudo cp supervisor/nabs.service /etc/systemd/system/nabs.service
sudo systemctl daemon-reload
sudo systemctl enable nabs
sudo systemctl start nabs
sudo systemctl status nabs --no-pager

# 10. Configure nginx
echo "[10/11] Configuring nginx..."
sudo rm -f /etc/nginx/sites-enabled/default
sudo cp supervisor/nabs /etc/nginx/sites-available/nabs
sudo ln -sf /etc/nginx/sites-available/nabs /etc/nginx/sites-enabled/nabs
sudo systemctl restart nginx

# 11. Info output + default admin credentials
echo "[11/11] ✅ Web server is up at: https://localhost"
echo "         If browser complains, confirm the self-signed certificate."
echo ""
echo "=== Default admin account ==="
echo "NABS auto-created a default admin (admin@admin.local) on first start."
echo "Its randomly generated password was printed ONCE to the service log"
echo "at that moment - grab it now with:"
echo ""
echo "  journalctl -u nabs --since \"5 minutes ago\" | grep -A 5 'Default admin user created'"
echo ""
echo "Log in and change the password immediately. If you need to create"
echo "additional users later, use: python3 create_user.py -a <email>"

echo "=== ✅ NABS installation complete ==="
