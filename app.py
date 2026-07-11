from flask import Flask, send_from_directory

app = Flask(__name__)


@app.route("/healthz")
def healthz():
    """Simple health check most hosting platforms can ping."""
    return {"status": "ok"}


@app.route("/gc.html")
def serve_gc():
    return send_from_directory(".", "gc.html")


@app.route("/")
def index():
    # Serves the exam app itself at the root URL so the deployed link
    # can be handed straight to students and teachers.
    return send_from_directory(".", "gc.html")


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
