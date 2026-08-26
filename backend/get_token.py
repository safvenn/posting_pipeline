import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CLIENT_ID = os.getenv("YT_CLIENT_ID") or input("Enter Google OAuth Client ID: ").strip()
CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET") or input("Enter Google OAuth Client Secret: ").strip()

if not CLIENT_ID or not CLIENT_SECRET:
    print("Error: Client ID and Client Secret are required.")
    sys.exit(1)

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0)

print("\n" + "="*50)
print("REFRESH TOKEN:")
print(creds.refresh_token)
print("="*50 + "\n")
