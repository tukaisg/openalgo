import os
from dotenv import load_dotenv
from openalgo import api

# Load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

api_key = os.getenv("OPENALGO_API_KEY")
host = "http://127.0.0.1:5000"

try:
    client = api(api_key=api_key, host=host)
    response = client.funds()
    
    if response.get('status') == 'success':
        data = response.get('data', {})
        print(f"💰 Available Cash: ₹{data.get('availablecash', '0')}")
        print(f"🔒 Collateral:     ₹{data.get('collateral', '0')}")
        print(f"📉 Utilised:       ₹{data.get('utiliseddebits', '0')}")
    else:
        print(f"❌ Error: {response.get('message')}")
        
except Exception as e:
    print(f"❌ Error: {str(e)}")
