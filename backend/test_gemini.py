import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def test_gemini():
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        # Fallback to the one you pasted in ai_service.py if .env isn't set
        api_key = os.environ.get("GEMINI_API_KEY")
        print("GEMINI_API_KEY not found in .env, using fallback key.")
    
    print(f"Using API Key starting with: {api_key[:10]}...")
    
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-flash-lite-latest',
            contents="Say 'Hello, the API key is working!'"
        )
        print("\n[OK] Success! Gemini responded:")
        print(response.text)
    except Exception as e:
        print("\n[ERROR] Error connecting to Gemini:")
        print(e)

if __name__ == "__main__":
    test_gemini()
