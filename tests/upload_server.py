# SPDX-License-Identifier: MIT
"""A package index upload endpoint for tests/interactive.sh.

It accepts the legacy upload API that `pdm publish` uses (a multipart POST
with the file in the `content` field), saves each uploaded file into the
directory given as the second argument, and answers 200.

    python3 upload_server.py PORT DIRECTORY
"""

import email
import email.policy
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

directory = Path(sys.argv[2])
directory.mkdir(parents=True, exist_ok=True)


class Upload(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        header = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
        message = email.message_from_bytes(header + body, policy=email.policy.HTTP)
        for part in message.iter_parts():
            if part.get_param("name", header="content-disposition") == "content":
                (directory / part.get_filename()).write_bytes(part.get_payload(decode=True))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        print(format % args, file=sys.stderr)


server = HTTPServer(("127.0.0.1", int(sys.argv[1])), Upload)
if len(sys.argv) > 3:
    Path(sys.argv[3]).write_text(str(server.server_port))
server.serve_forever()
