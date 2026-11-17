"""Initialize the local database through Flask-Migrate, preserving existing data."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
os.chdir(root)
(root / '.local').mkdir(exist_ok=True)
(root / 'logs').mkdir(exist_ok=True)
env = dict(os.environ, FLASK_ENV='testing')  # Skip automatic admin until schema exists.

def migrate(*args):
    subprocess.run([sys.executable, '-m', 'flask', '--app', 'app', 'db', *args],
                   cwd=root, env=env, check=True)

if not (root / 'migrations/alembic.ini').exists():
    migrate('init')
    migrate('migrate', '-m', 'Initial local schema')
migrate('upgrade')

# The first startup prints the generated admin password once. Keep it in a
# git-excluded local file; never overwrite it on subsequent initialization.
login_file = root / '.local/admin-login.txt'
if not login_file.exists():
    with login_file.open('x', encoding='utf-8') as output:
        subprocess.run([sys.executable, '-c', 'from app import app'],
                       cwd=root, env={k: v for k, v in os.environ.items() if k != 'FLASK_ENV'},
                       stdout=output, check=True)
print('Local database ready. First-login details: .local/admin-login.txt')
