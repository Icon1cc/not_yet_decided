from dotenv import load_dotenv
import requests
import json
import os
load_dotenv()

response = requests.post(
  url="https://openrouter.ai/api/v1/chat/completions",
  headers={
    "Authorization": "Bearer " + os.getenv("OPENROUTER_API_KEY"),
    "HTTP-Referer": os.getenv("YOUR_SITE_URL"), # Optional. Site URL for rankings on openrouter.ai.
    "X-OpenRouter-Title": os.getenv("YOUR_SITE_NAME"), # Optional. Site title for rankings on openrouter.ai.
  },
  data=json.dumps({
    "model": "anthropic/claude-sonnet-4.5", # Optional
    "messages": [
      {
        "role": "user",
        "content": "What is the meaning of life?"
      }
    ]
  })
)

print(response.json()["choices"][0]["message"]["content"])                                                                                     