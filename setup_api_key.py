from database.auth_db import upsert_api_key
from database.user_db import User, db_session
import secrets

try:
    # Find a user first
    user = User.query.first()
    if user:
        print(f"Found user: {user.username}")
        # Generate a new API key
        new_api_key = secrets.token_hex(32)
        
        # Upsert the key for this user
        # We use username as user_id for API keys typically in this system, 
        # based on auth logic usually keying off username.
        # Let's double check if upsert_api_key expects int or str. 
        # The ApiKeys model has user_id as String. So username is likely correct.
        upsert_api_key(user.username, new_api_key)
        
        print("API Key created successfully.")
        print(f"API_KEY: {new_api_key}")
    else:
        print("No user found in database. Please run setup first (or wait for app to init).")
        # If no user, we might need to create one? 
        # But app usually prompts for setup. 
        
except Exception as e:
    print(f"Error creating API key: {e}")
