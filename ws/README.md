# Basic Express WEB Server for Logging Text and Raw Data

## This code DOES NOT promote or encourage any illegal activities! The content in this document is provided solely for educational purposes and to create awareness!

## This is a proof of concept and could be improved on in a lot of ways.

1. Clone this code with `git clone https://github.com/vyahello/keylog.git`
2. Run the command `cd keylog/ws`
3. Run the command `python3 setup.py`. This will do the basic setup on the Ubuntu server. It installs NodeJS, Node Package Manager (NPM) and the Express web framework used by the server.
4. Run the command `node server.js` (or `npm start`) to start the server on port ***8080***.
   The port is configurable via the `PORT` environment variable, e.g. `PORT=3000 node server.js`.
5. To run it in the background instead:
   - Start: `nohup node server.js > server.log 2>&1 &`
   - Follow the output: `tail -f server.log`
   - Stop: `pkill -f 'node server.js'`


Endpoints:
- `GET /` shows the contents of both log files, refreshed on every page load.
- `POST /text` overwrites `logs/text_logs.txt` with a string `textData` field.
- `POST /raw` overwrites `logs/raw_logs.txt` with a string `rawData` field.

Each POST replaces the file with the latest value, so a log holds only the most recent data.

Example JSON bodies:
```json
{ "textData": "<text to log>" }
{ "rawData": "<raw data to log>" }
```

Sending from Python with `requests` (the server accepts the body regardless of
content-type header):
```python
import json
import requests

requests.post("http://localhost:8080/text", data=json.dumps({"textData": "hello world"}))
requests.post("http://localhost:8080/raw", data=json.dumps({"rawData": "some raw data"}))
```

Or with curl:
```bash
curl -X POST http://localhost:8080/text \
  -H "Content-Type: application/json" \
  -d '{"textData": "hello world"}'
```

## Files in this repo

- `server.js` — the Express server (the whole app).
- `package.json` / `package-lock.json` — project metadata and the pinned dependency (Express).
- `setup.py` — set up a fresh Ubuntu server.

## Notes

This is a bare-bones project that shows how much a few lines of server-side JavaScript on Node can do. It could be extended with a database such as MongoDB paired with Mongoose (to validate and structure API input), and adding update and remove operations would be straightforward. This version uses non-blocking file I/O, validates the POST body, escapes stored data before rendering it, and handles read/write errors explicitly.
