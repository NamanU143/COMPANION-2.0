import os
import subprocess
import sys
from dotenv import load_dotenv

load_dotenv()

def main():
    print("===============================================")
    print("🤖 Welcome to Desktop AI Companion Backend 🤖")
    print("===============================================")
    print("\nWhich AI Provider would you like to use?")
    print("1) Hosted OpenAI (GPT-4o or selected model)")
    print("2) Hosted Gemini (Google API)")
    print("3) Local Mistral (via Ollama)")
    print("4) Hosted Anthropic (Claude 3 Haiku)")
    
    choice = input("\nEnter your choice [1, 2, 3, 4] (Default: 1): ").strip()
    
    if choice == '2':
        print("\n--> Starting with Hosted Gemini API...\n")
        os.environ["LLM_PROVIDER"] = "gemini"
    elif choice == '3':
        print("\n--> Starting with Local Ollama (Mistral)...\n")
        os.environ["LLM_PROVIDER"] = "ollama"
    elif choice == '4':
        print("\n--> Starting with Hosted Anthropic API...\n")
        os.environ["LLM_PROVIDER"] = "anthropic"
    else:
        print("\n--> Starting with Hosted OpenAI API...\n")
        os.environ["LLM_PROVIDER"] = "openai"
        
    print("Starting FastAPI Server on http://127.0.0.1:8000 ...")
    
    # Run uvicorn programmatically inheriting the current terminal
    subprocess.run([sys.executable, "-m", "uvicorn", "app:app", "--reload"])

if __name__ == "__main__":
    main()
