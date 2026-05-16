import json
import os

TOKENS_DIR = "tokens"
TOKEN_FILE = os.path.join(TOKENS_DIR, "user_token.json")

def save_token(token_data):
    """Save token - handles both dict and Credentials object"""
    os.makedirs(TOKENS_DIR, exist_ok=True)
    
    if isinstance(token_data, dict):
        token_dict = token_data
    else:
        token_dict = {
            'access_token': getattr(token_data, 'token', None),
            'refresh_token': getattr(token_data, 'refresh_token', None),
            'token_uri': getattr(token_data, 'token_uri', None),
            'client_id': getattr(token_data, 'client_id', None),
            'client_secret': getattr(token_data, 'client_secret', None),
            'scopes': getattr(token_data, 'scopes', None),
        }
    
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_dict, f, indent=2)

def load_token():
    """Load token from file"""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, 'r') as f:
        return json.load(f)

def delete_token():
    """Delete token"""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
