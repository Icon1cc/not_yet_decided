"""
Vercel serverless function entry point.
"""

from backend.app.main import app

# Vercel expects a handler
handler = app
