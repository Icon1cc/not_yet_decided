"""
Health check endpoint for Vercel.
"""

import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler

# Add project root to path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            from backend.app.services.catalog import get_matcher
            from backend.app.services.agent import get_agent

            matcher = get_matcher()
            agent = get_agent()

            response = {
                "status": "ok" if agent.is_configured else "ok (basic mode)",
                "version": "1.0.0",
                "sources": len(matcher.default_sources),
                "targets": len(matcher.targets),
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
