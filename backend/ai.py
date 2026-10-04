"""Lazy provider initialization: dashboard works without API credentials."""
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

def generate_text(prompt: str) -> str:
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        raise HTTPException(503, 'AI is not configured. Add OPENAI_API_KEY to .env or create a manual draft.')
    try:
        with OpenAI(api_key=key, timeout=45, max_retries=1) as client:
            response = client.responses.create(model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'), input=prompt)
        text = response.output_text.strip()
        if not text:
            raise HTTPException(502, 'AI returned no content. Please try again.')
        return text
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, 'AI service is unavailable. Check the model, API key and billing configuration.')
