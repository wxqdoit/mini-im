import os
import mimetypes
from flask import Blueprint, request, jsonify, Response, current_app
from minio_service import upload_file_to_minio, get_file_from_minio
from auth import token_required
from config import Config
from rate_limiter import rate_limit

upload_bp = Blueprint("upload", __name__, url_prefix="/api")

DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".py", ".php", 
    ".jsp", ".asp", ".aspx", ".cgi", ".pl", ".html", ".htm", ".js"
}

@upload_bp.route("/upload", methods=["POST"])
@token_required
@rate_limit("upload", limit=30, window_seconds=60, by_user=True)
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Validate file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext in DANGEROUS_EXTENSIONS:
        return jsonify({"error": f"File extension '{ext}' is not permitted for security reasons."}), 400

    folder = request.form.get("folder", "chat")
    if folder not in ["chat", "avatars"]:
        folder = "chat"

    # Enforce streaming read with size limit check to prevent OOM
    file_bytes = file.read(Config.MAX_CONTENT_LENGTH + 1)
    if len(file_bytes) > Config.MAX_CONTENT_LENGTH:
        return jsonify({"error": f"File size exceeds maximum allowed limit ({Config.MAX_CONTENT_LENGTH // (1024 * 1024)}MB)"}), 413

    content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    try:
        object_name, public_url, file_size = upload_file_to_minio(
            file_bytes, file.filename, content_type, folder=folder
        )
        proxy_url = f"/api/media/{object_name}"
        
        return jsonify({
            "message": "File uploaded successfully to MinIO",
            "url": public_url,
            "proxy_url": proxy_url,
            "file_name": file.filename,
            "file_size": file_size,
            "content_type": content_type
        }), 201
    except Exception as e:
        return jsonify({"error": f"MinIO upload failed: {str(e)}"}), 500

@upload_bp.route("/media/<path:filename>", methods=["GET"])
def stream_media(filename):
    """
    Proxy endpoint streaming file from MinIO to client browser.
    """
    try:
        minio_response = get_file_from_minio(filename)
        content_type = minio_response.headers.get("content-type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        
        def generate():
            for chunk in minio_response.stream(64 * 1024):
                yield chunk
            minio_response.close()
            minio_response.release_conn()

        headers = {
            "Content-Type": content_type,
            "Content-Length": minio_response.headers.get("content-length", ""),
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff"
        }
        return Response(generate(), headers=headers)
    except Exception as e:
        return jsonify({"error": f"File not found: {str(e)}"}), 404
