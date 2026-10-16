import json
from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import token_required

e2ee_bp = Blueprint("e2ee", __name__, url_prefix="/api/e2ee")

@e2ee_bp.route("/keys", methods=["POST"])
@token_required
def upload_keys():
    user_id = g.current_user["id"]
    data = request.get_json() or {}
    
    identity_public_key = data.get("identity_public_key", "").strip()
    signed_prekey = data.get("signed_prekey", "").strip()
    prekey_signature = data.get("prekey_signature", "").strip()

    if not identity_public_key:
        return jsonify({"error": "identity_public_key is required"}), 400

    with get_db() as cur:
        cur.execute("""
            INSERT INTO user_keys (user_id, identity_public_key, signed_prekey, prekey_signature, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                identity_public_key = EXCLUDED.identity_public_key,
                signed_prekey = EXCLUDED.signed_prekey,
                prekey_signature = EXCLUDED.prekey_signature,
                updated_at = CURRENT_TIMESTAMP;
        """, (user_id, identity_public_key, signed_prekey, prekey_signature))

    return jsonify({"message": "Public keys registered successfully"})

@e2ee_bp.route("/keys/<int:target_user_id>", methods=["GET"])
@token_required
def get_user_keys(target_user_id):
    with get_db() as cur:
        cur.execute("""
            SELECT user_id, identity_public_key, signed_prekey, prekey_signature, updated_at
            FROM user_keys
            WHERE user_id = %s;
        """, (target_user_id,))
        key_record = cur.fetchone()

    if not key_record:
        return jsonify({"error": "User has not published E2EE keys yet"}), 404

    return jsonify({
        "user_id": key_record["user_id"],
        "identity_public_key": key_record["identity_public_key"],
        "signed_prekey": key_record["signed_prekey"],
        "prekey_signature": key_record["prekey_signature"],
        "updated_at": key_record["updated_at"].isoformat() if key_record["updated_at"] else None
    })

@e2ee_bp.route("/keys/batch", methods=["POST"])
@token_required
def get_batch_user_keys():
    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])
    if not isinstance(user_ids, list):
        return jsonify({"error": "user_ids must be a list"}), 400

    if not user_ids:
        return jsonify({"keys": {}})

    with get_db() as cur:
        cur.execute("""
            SELECT user_id, identity_public_key, signed_prekey, prekey_signature
            FROM user_keys
            WHERE user_id = ANY(%s);
        """, (user_ids,))
        rows = cur.fetchall()

    result = {}
    for r in rows:
        result[str(r["user_id"])] = {
            "identity_public_key": r["identity_public_key"],
            "signed_prekey": r["signed_prekey"],
            "prekey_signature": r["prekey_signature"]
        }

    return jsonify({"keys": result})

@e2ee_bp.route("/group-keys/<int:group_id>", methods=["GET"])
@token_required
def get_group_keys(group_id):
    user_id = g.current_user["id"]
    with get_db() as cur:
        # Check membership
        cur.execute("SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s", (group_id, user_id))
        if not cur.fetchone():
            return jsonify({"error": "You are not a member of this group"}), 403

        # Get latest key version
        cur.execute("""
            SELECT key_version, encrypted_keys, created_by, created_at
            FROM group_e2ee_keys
            WHERE group_id = %s
            ORDER BY key_version DESC LIMIT 1;
        """, (group_id,))
        key_row = cur.fetchone()

    if not key_row:
        return jsonify({"has_key": False}), 200

    encrypted_keys = key_row["encrypted_keys"]
    # Provide the user's specific encrypted payload
    user_key_data = encrypted_keys.get(str(user_id)) if isinstance(encrypted_keys, dict) else None

    return jsonify({
        "has_key": True,
        "key_version": key_row["key_version"],
        "created_by": key_row["created_by"],
        "user_key_data": user_key_data,
        "all_keys": encrypted_keys
    })

@e2ee_bp.route("/group-keys/<int:group_id>", methods=["POST"])
@token_required
def set_group_keys(group_id):
    user_id = g.current_user["id"]
    data = request.get_json() or {}
    encrypted_keys = data.get("encrypted_keys")
    key_version = data.get("key_version", 1)

    if not encrypted_keys or not isinstance(encrypted_keys, dict):
        return jsonify({"error": "encrypted_keys object required"}), 400

    with get_db() as cur:
        # Check membership
        cur.execute("SELECT role FROM group_members WHERE group_id = %s AND user_id = %s", (group_id, user_id))
        mem = cur.fetchone()
        if not mem:
            return jsonify({"error": "You are not a member of this group"}), 403

        cur.execute("""
            INSERT INTO group_e2ee_keys (group_id, key_version, encrypted_keys, created_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (group_id, key_version)
            DO UPDATE SET encrypted_keys = EXCLUDED.encrypted_keys;
        """, (group_id, key_version, json.dumps(encrypted_keys), user_id))

    return jsonify({"message": "Group E2EE keys published successfully", "key_version": key_version})
