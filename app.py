import os
import json
import urllib.request
import urllib.error
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

ENV_FILE = ".env"


def load_env_file(path=ENV_FILE):
    """Loads KEY=VALUE pairs from a local .env file for local development.
    On a real host (Render/Railway/etc.) set these as dashboard environment
    variables instead — this file won't exist there, and that's fine."""
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


@app.route("/healthz")
def healthz():
    """Simple health check most hosting platforms can ping."""
    return jsonify({"status": "ok"})


@app.route("/api/extract-questions", methods=["POST", "OPTIONS"])
def extract_questions():
    """Server-side proxy to the Gemini API (free tier) for interpreting
    uploaded question papers (image/PDF/text) into structured question JSON.
    Runs on the backend, using a real API key, so the browser never needs
    direct access to the AI provider itself."""
    if request.method == "OPTIONS":
        return ("", 204)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the server. Add it as an environment variable on your host."}), 503

    data = request.get_json(silent=True) or {}
    content_blocks = data.get("content")
    if not content_blocks:
        return jsonify({"error": "No content provided."}), 400

    # Convert the frontend's Anthropic-style content blocks into Gemini's
    # "parts" format, so gc.html doesn't need to know which provider is used.
    parts = []
    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            parts.append({"text": block.get("text", "")})
        elif btype in ("image", "document"):
            source = block.get("source", {})
            parts.append({
                "inline_data": {
                    "mime_type": source.get("media_type", "application/octet-stream"),
                    "data": source.get("data", "")
                }
            })

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": parts}]
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8")
        try:
            parsed = json.loads(err_body)
            error_message = parsed.get("error", {}).get("message") or parsed
        except Exception:
            error_message = err_body
        return jsonify({"error": str(error_message)}), err.code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Re-shape Gemini's response into the {content:[{type:'text', text:...}]}
    # form gc.html already expects, so the frontend needed no changes.
    try:
        candidate_parts = result["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in candidate_parts)
    except (KeyError, IndexError):
        text = ""
    return jsonify({"content": [{"type": "text", "text": text}]})


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
