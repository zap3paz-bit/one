from flask import Flask, request, jsonify, send_from_directory
import os
import json
import base64
import urllib.parse
import urllib.request

app = Flask(__name__)

ENV_FILE = ".env"


def load_env_file(path=ENV_FILE):
    """Loads KEY=VALUE pairs from a local .env file for local development.
    On a real host (Render/Railway/etc.) you'll set these as dashboard
    environment variables instead, and this file won't exist — that's fine."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


load_env_file()

# Restrict which site(s) may call this API. Set ALLOWED_ORIGIN to your
# gc.html's exact origin in production (e.g. https://myschool.example.com).
# Defaults to "*" (any origin) so it keeps working out of the box.
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response


@app.route("/healthz")
def healthz():
    """Simple health check most hosting platforms can ping."""
    return jsonify({"status": "ok"})


@app.route("/api/send-sms", methods=["POST", "OPTIONS"])
def send_sms():
    if request.method == "OPTIONS":
        response = jsonify({})
        response.status_code = 204
        return response

    data = request.get_json(silent=True) or {}
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")

    if not account_sid or not auth_token or not from_number:
        return jsonify({"error": "Twilio configuration missing. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER."}), 503

    to_number = data.get("to")
    body = data.get("body")
    if not to_number or not body:
        return jsonify({"error": "Missing 'to' or 'body' in request."}), 400

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    payload = urllib.parse.urlencode({"To": to_number, "From": from_number, "Body": body}).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    auth_header = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("utf-8")
    req.add_header("Authorization", f"Basic {auth_header}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.load(resp)
            response = jsonify(result)
            response.status_code = resp.getcode()
            return response
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8")
        try:
            payload = json.loads(err_body)
            error_message = payload.get("message") or payload
        except Exception:
            error_message = err_body
        response = jsonify({"error": str(error_message)})
        response.status_code = err.code
        return response


@app.route("/gc.html")
def serve_gc():
    return send_from_directory(".", "gc.html")


@app.route("/")
def index():
    # Serves the exam app itself at the root URL so the deployed link
    # can be handed straight to students and teachers.
    return send_from_directory(".", "gc.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
