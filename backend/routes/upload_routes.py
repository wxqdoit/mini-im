from flask import Blueprint, request, jsonify, Response, send_file
import mimetypes
from minio_service import upload_file_to_minio, get_file_from_minio
from auth import token_required

upload_bp = Blueprint("upload", __name__, url_prefix="/api")

@upload_bp.route("/upload", methods=["POST"])
@token_required
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    folder = request.form.get("folder", "chat")
    if folder not in ["chat", "avatars"]:
        folder = "chat"

    file_bytes = file.read()
    content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    try:
        object_name, public_url, file_size = upload_file_to_minio(
            file_bytes, file.filename, content_type, folder=folder
        )
        # Also provide internal proxy URL as alternative
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
            for chunk in minio_response.stream(32 * 1024):
                yield chunk
            minio_response.close()
            minio_response.release_conn()

        headers = {
            "Content-Type": content_type,
            "Content-Length": minio_response.headers.get("content-length", ""),
            "Cache-Control": "public, max-age=86400"
        }
        return Response(generate(), headers=headers)
    except Exception as e:
        return jsonify({"error": f"File not found: {str(e)}"}), 404
