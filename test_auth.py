from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_ANON_KEY"),
)

response = client.auth.sign_in_with_password(
    {
        "email": "YOUR_EMAIL",
        "password": "YOUR_PASSWORD",
    }
)

print(response)