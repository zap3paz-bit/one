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

# Which AI provider handles question-paper extraction.
# "anthropic" (default) — reliable, small per-use cost, requires ANTHROPIC_API_KEY.
# "gemini" — free tier, but Google currently has an unresolved bug rejecting
#            new-format AQ. keys with ACCESS_TOKEN_TYPE_UNSUPPORTED for many
#            accounts (as of July 2026). Flip AI_PROVIDER=gemini once that's
#            fixed on Google's end, or if your key happens to work.
# "openrouter" — genuinely free, no credit card, working today (July 2026).
#                Uses a free vision-capable model. Requires OPENROUTER_API_KEY.
AI_PROVIDER = os.environ.get("AI_PROVIDER", "openrouter").strip().lower()


@app.route("/healthz")
def healthz():
    """Simple health check most hosting platforms can ping."""
    return jsonify({"status": "ok", "ai_provider": AI_PROVIDER})


@app.route("/api/extract-questions", methods=["POST", "OPTIONS"])
def extract_questions():
    """Server-side proxy for interpreting uploaded question papers
    (image/PDF/text) into structured question JSON. Runs on the backend,
    using a real API key, so the browser never needs direct provider access."""
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    content_blocks = data.get("content")
    if not content_blocks:
        return jsonify({"error": "No content provided."}), 400

    if AI_PROVIDER == "gemini":
        return _extract_with_gemini(content_blocks)
    if AI_PROVIDER == "openrouter":
        return _extract_with_openrouter(content_blocks)
    return _extract_with_anthropic(content_blocks)


def _extract_with_openrouter(content_blocks):
    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        return jsonify({"error": "OPENROUTER_API_KEY is not configured on the server. Add it as an environment variable on your host."}), 503

    # Convert the frontend's Anthropic-style content blocks into OpenAI-style
    # content parts, which OpenRouter's chat completions endpoint expects.
    parts = []
    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            parts.append({"type": "text", "text": block.get("text", "")})
        elif btype in ("image", "document"):
            source = block.get("source", {})
            media_type = source.get("media_type", "application/octet-stream")
            data_b64 = source.get("data", "")
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{data_b64}"}
            })

    model = os.environ.get("OPENROUTER_MODEL", "qwen/qwen2.5-vl-72b-instruct:free")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": parts}]
    }).encode("utf-8")

    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=payload)
    req.add_header("Authorization", f"Bearer {api_key}")
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

    # Re-shape into the {content:[{type:'text', text:...}]} form gc.html expects.
    try:
        text = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        text = ""
    return jsonify({"content": [{"type": "text", "text": text}]})


def _extract_with_anthropic(content_blocks):
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured on the server. Add it as an environment variable on your host."}), 503

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": content_blocks}]
    }).encode("utf-8")

    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload)
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.load(resp)
            return jsonify(result)
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


def _extract_with_gemini(content_blocks):
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the server. Add it as an environment variable on your host."}), 503

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
