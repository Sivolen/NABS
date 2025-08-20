#!/bin/bash

set -e

echo "=== 🛠 Starting NABS installation ==="

# 1. Install system dependencies
echo "[1/12] Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql git nginx openssl

# 2. Create Python virtual environment
echo "[2/12] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
echo "[3/12] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Generate DB password and prepare configs
echo "[4/12] Copying config files and generating DB password..."
DB_PASSWORD=$(openssl rand -base64 14)
cp config_example.py config.py
cp config_example.yaml config.yaml
sed -i "s|DBPassword *= *\".*\"|DBPassword = \"$DB_PASSWORD\"|g" config.py
echo "[+] Generated DB password: $DB_PASSWORD"

# 5. Create PostgreSQL database and user
echo "[5/12] Creating PostgreSQL database and user..."
sudo -u postgres psql -c "CREATE DATABASE nabs_db;"
sudo -u postgres psql -c "CREATE USER nabs_user WITH PASSWORD '$DB_PASSWORD';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE nabs_db TO nabs_user;"

# 6. Create working directories
echo "[6/12] Creating logs, backups, user_uploads, and certs directories..."
mkdir -p logs backups user_uploads certs

# 7. Run database migrations
echo "[7/12] Running Flask DB migrations..."
# export FLASK_APP=app.py
# export FLASK_ENV=production
flask db init || true
flask db migrate -m "Initial migration" || true
flask db upgrade

# Генерируем SECRET_KEY для Flask
SECRET_KEY=$(openssl rand -base64 14)
sed -i "s|SECRET_KEY *= *\".*\"|SECRET_KEY = \"SECRET_KEY\"|g" config.py
echo "✅ Сгенерирован SECRET_KEY для Flask"

# 8. Generate self-signed SSL certificate
echo "[8/12] Generating self-signed SSL certificate..."
openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/C=RU/ST=RU/L=City/O=NABS/OU=IT/CN=localhost"

# 9. Install and start systemd service
echo "[9/12] Installing systemd service for NABS..."
sudo cp supervisor/nabs.service /etc/systemd/system/nabs.service
sudo systemctl daemon-reload
sudo systemctl enable nabs
sudo systemctl start nabs
sudo systemctl status nabs --no-pager

# 10. Configure nginx
echo "[10/12] Configuring nginx..."
sudo rm -f /etc/nginx/sites-enabled/default
sudo cp supervisor/nabs /etc/nginx/sites-available/nabs
sudo ln -sf /etc/nginx/sites-available/nabs /etc/nginx/sites-enabled/nabs
sudo systemctl restart nginx

# 11. Info output
echo "[11/12] ✅ Web server is up at: https://localhost"
echo "         If browser complains, confirm the self-signed certificate."

# 12. Create superuser account
echo "[12/12] Creating initial admin user..."
python3 users_helper.py

echo "=== ✅ NABS installation complete ==="