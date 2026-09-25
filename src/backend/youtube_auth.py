"""
youtube_auth.py — YouTube OAuth2 Authentication Handler
Supports both 'web' and 'installed' (desktop) OAuth client types.
"""
import os
import json
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from google.oauth2.credentials import Credentials
from src.database import store_youtube_credentials, get_youtube_credentials

CLIENT_SECRETS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "client_secret.json"
)
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
]


def _get_client_type():
    """Read the client_secret.json and return the app type: 'web' or 'installed'."""
    with open(CLIENT_SECRETS_FILE) as f:
        data = json.load(f)
    return 'web' if 'web' in data else 'installed'


def get_auth_url(redirect_uri):
    """
    Returns (authorization_url, state) for the OAuth2 flow.
    Works for both 'web' and 'installed' app types.
    """
    client_type = _get_client_type()

    if client_type == 'web':
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        return authorization_url, state, getattr(flow, 'code_verifier', None)
    else:
        # 'installed' app — generate URL manually but handle the redirect ourselves
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        # Force the redirect_uri even for installed apps
        flow.redirect_uri = redirect_uri
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        return authorization_url, state, getattr(flow, 'code_verifier', None)


def handle_oauth2callback(redirect_uri, state, authorization_response, user_id, code_verifier=None):
    """
    Exchanges the authorization code for tokens and stores them in the DB.
    """
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri
    )
    if code_verifier:
        # google-auth-oauthlib reads flow.code_verifier when fetching tokens
        flow.code_verifier = code_verifier
        
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials

    creds_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': list(credentials.scopes) if credentials.scopes else SCOPES
    }
    store_youtube_credentials(user_id, json.dumps(creds_data))
    print(f"[YouTube Auth] Credentials stored for user {user_id}")
    return creds_data


def get_user_credentials(user_id):
    """
    Retrieve stored credentials for a user. Returns None if not connected.
    """
    creds_json = get_youtube_credentials(user_id)
    if not creds_json:
        return None
    try:
        creds_data = json.loads(creds_json)
        creds = Credentials(
            token=creds_data.get('token'),
            refresh_token=creds_data.get('refresh_token'),
            token_uri=creds_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=creds_data.get('client_id'),
            client_secret=creds_data.get('client_secret'),
            scopes=creds_data.get('scopes', SCOPES)
        )
        return creds
    except Exception as e:
        print(f"[YouTube Auth] Error loading credentials for user {user_id}: {e}")
        return None


def is_connected(user_id) -> bool:
    """Check if a user has YouTube credentials stored."""
    return get_user_credentials(user_id) is not None
