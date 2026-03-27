"""Test GitHub Models API directly."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GITHUB_COPILOT_TOKEN") or os.getenv("GITHUB_COPILOT_API_KEY")

if not api_key:
    print("❌ No API key found")
    exit(1)

print(f"API Key: {api_key[:20]}...")

# Test different API endpoints
endpoints = [
    ("https://models.inference.ai.azure.com", "gpt-4o"),
    ("https://api.github.com", "gpt-4o"),
    ("https://models.github.ai", "gpt-4o"),
]

for api_url, model in endpoints:
    print(f"\n{'='*70}")
    print(f"Testing: {api_url}")
    print(f"Model: {model}")
    print('='*70)
    
    # Simple test request
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Hello"}
        ],
        "max_tokens": 10
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Test-Client/1.0"
    }
    
    # Try different paths
    paths = [
        "/v1/chat/completions",
        "/chat/completions",
        "/models/chat/completions",
        "/inference/chat/completions"
    ]
    
    for path in paths:
        full_url = f"{api_url}{path}"
        print(f"\nTrying: {full_url}")
        
        try:
            response = requests.post(
                full_url,
                json=payload,
                headers=headers,
                timeout=10
            )
            
            print(f"  Status: {response.status_code}")
            
            if response.status_code == 200:
                print(f"  SUCCESS!")
                data = response.json()
                print(f"  Response: {data}")
                break
            elif response.status_code == 404:
                print(f"  Not Found (404)")
            else:
                print(f"  Error {response.status_code}: {response.text[:200]}")
                
        except requests.exceptions.Timeout:
            print(f"  ⏱️  Timeout")
        except requests.exceptions.ConnectionError as e:
            print(f"  ❌ Connection Error: {str(e)[:100]}")
        except Exception as e:
            print(f"  ❌ Error: {str(e)[:100]}")
