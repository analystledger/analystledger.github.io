"""TikTok token storage.

The refresh token rotates, and GitHub Actions cannot rewrite its own secrets, so we keep the
current refresh token encrypted in data/tiktok_token.enc. The encryption key is derived from the
TIKTOK_CLIENT_SECRET secret, so the file is useless without it.

Usage:  python scripts/tiktok_auth.py exchange <one-time-code>   # first connection
"""
import base64
import hashlib
import json
import os
import sys

import requests
from cryptography.fernet import Fernet

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(ROOT, "data", "tiktok_token.enc")
REDIRECT_URI = "https://analystledger.github.io/tiktok-callback.html"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def _fernet():
    secret = os.environ["TIKTOK_CLIENT_SECRET"].encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"analystledger-tiktok|" + secret).digest()))


def save(token_json):
    blob = _fernet().encrypt(json.dumps({"refresh_token": token_json["refresh_token"],
                                         "open_id": token_json.get("open_id")}).encode())
    with open(TOKEN_FILE, "wb") as f:
        f.write(blob)


def load_refresh_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            return json.loads(_fernet().decrypt(f.read()))["refresh_token"]
    return os.environ.get("TIKTOK_REFRESH_TOKEN")


def _token_request(data):
    data.update(client_key=os.environ["TIKTOK_CLIENT_KEY"], client_secret=os.environ["TIKTOK_CLIENT_SECRET"])
    r = requests.post(TOKEN_URL, data=data, timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    j = r.json()
    if r.status_code != 200 or "access_token" not in j:
        raise RuntimeError(f"TikTok token error: {j.get('error')} {j.get('error_description')}")
    return j


def access_token():
    """Return a fresh access token and persist the (possibly rotated) refresh token."""
    j = _token_request({"grant_type": "refresh_token", "refresh_token": load_refresh_token()})
    save(j)
    return j["access_token"]


def exchange(code):
    j = _token_request({"grant_type": "authorization_code", "code": code.strip(), "redirect_uri": REDIRECT_URI})
    save(j)
    print("TikTok connected. Granted scopes:", j.get("scope"))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "exchange":
        exchange(sys.argv[2])
    else:
        print(__doc__)
