import requests
import json
import time
import base64
import os
import sys

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from db import get_db

BASE_URL = "http://127.0.0.1:5001/api"

print("="*65)
print("MINI-IM END-TO-END ENCRYPTION (E2EE) CRYPTOGRAPHIC TEST")
print("Primitives: ECDH (NIST P-256) + HKDF-SHA256 + AES-256-GCM")
print("Target: Zero-Knowledge Server & Client-Side Confidentiality")
print("="*65)

# Step 1: Register User A (Alice) & User B (Bob)
ts = int(time.time())
uname_a = f"e2ee_alice_{ts}"
uname_b = f"e2ee_bob_{ts}"

res_a = requests.post(f"{BASE_URL}/auth/register", json={"username": uname_a, "password": "password123", "nickname": "Alice E2EE"})
assert res_a.status_code == 201, res_a.text
token_a = res_a.json()["token"]
user_a = res_a.json()["user"]
headers_a = {"Authorization": f"Bearer {token_a}"}

res_b = requests.post(f"{BASE_URL}/auth/register", json={"username": uname_b, "password": "password123", "nickname": "Bob E2EE"})
assert res_b.status_code == 201, res_b.text
token_b = res_b.json()["token"]
user_b = res_b.json()["user"]
headers_b = {"Authorization": f"Bearer {token_b}"}

print(f"1. Registered Users: Alice (ID {user_a['id']}) and Bob (ID {user_b['id']})")

# Step 2: Bob generates ECDH Identity Key pair and publishes Public Key
bob_priv_key = ec.generate_private_key(ec.SECP256R1())
bob_pub_key = bob_priv_key.public_key()

# Convert Bob's public key to JWK-like JSON format
bob_pub_numbers = bob_pub_key.public_numbers()
x_bytes = bob_pub_numbers.x.to_bytes(32, 'big')
y_bytes = bob_pub_numbers.y.to_bytes(32, 'big')

bob_pub_jwk = {
    "kty": "EC",
    "crv": "P-256",
    "x": base64.urlsafe_b64encode(x_bytes).decode('utf-8').rstrip('='),
    "y": base64.urlsafe_b64encode(y_bytes).decode('utf-8').rstrip('=')
}

res = requests.post(f"{BASE_URL}/e2ee/keys", headers=headers_b, json={
    "identity_public_key": json.dumps(bob_pub_jwk),
    "signed_prekey": "",
    "prekey_signature": ""
})
assert res.status_code == 200, res.text
print("2. Bob published Identity Public Key to /api/e2ee/keys successfully.")

# Step 3: Alice fetches Bob's Public Key from server
res = requests.get(f"{BASE_URL}/e2ee/keys/{user_b['id']}", headers=headers_a)
assert res.status_code == 200, res.text
retrieved_bob_jwk = json.loads(res.json()["identity_public_key"])
print("3. Alice retrieved Bob's Public Key bundle from server.")

# Step 4: Alice generates Ephemeral ECDH Key Pair & computes shared AES-GCM key
alice_ephemeral_priv = ec.generate_private_key(ec.SECP256R1())
alice_ephemeral_pub = alice_ephemeral_priv.public_key()
alice_eph_numbers = alice_ephemeral_pub.public_numbers()
alice_eph_jwk = {
    "kty": "EC",
    "crv": "P-256",
    "x": base64.urlsafe_b64encode(alice_eph_numbers.x.to_bytes(32, 'big')).decode('utf-8').rstrip('='),
    "y": base64.urlsafe_b64encode(alice_eph_numbers.y.to_bytes(32, 'big')).decode('utf-8').rstrip('=')
}

# Alice performs ECDH key exchange with Bob's public key
shared_secret_alice = alice_ephemeral_priv.exchange(ec.ECDH(), bob_pub_key)
# Web Crypto deriveKey (AES-GCM from ECDH directly uses SHA-256 HKDF or truncation)
# In WebCrypto ECDH -> AES-GCM: derived key uses first 256 bits of shared secret / HKDF
hkdf = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=None,
    info=b"mini_im_e2ee_direct",
)
aes_key_alice = hkdf.derive(shared_secret_alice)

# Step 5: Alice encrypts plaintext message using AES-256-GCM
plaintext = "TOP-SECRET-FINANCIAL-OR-PRIVATE-DATA: The server CANNOT see this text!"
iv = os.urandom(12)
aesgcm_alice = AESGCM(aes_key_alice)
ciphertext_bytes = aesgcm_alice.encrypt(iv, plaintext.encode('utf-8'), None)

ciphertext_b64 = base64.b64encode(ciphertext_bytes).decode('utf-8')
iv_b64 = base64.b64encode(iv).decode('utf-8')
ephemeral_key_json = json.dumps(alice_eph_jwk)

print(f"4. Alice encrypted plaintext ({len(plaintext)} chars) -> Ciphertext: {ciphertext_b64[:30]}...")

# Step 6: Alice dispatches E2EE message through Kafka & WebSocket pipeline
res = requests.post(f"{BASE_URL}/messages/send", headers=headers_a, json={
    "conversation_type": "direct",
    "recipient_id": user_b["id"],
    "msg_type": "text",
    "content": ciphertext_b64,
    "is_encrypted": True,
    "iv": iv_b64,
    "ephemeral_key": ephemeral_key_json
})
assert res.status_code == 200, res.text
print("5. Encrypted payload dispatched into Kafka pipeline.")

# Step 7: Wait 1s and inspect database directly (PostgreSQL Zero-Knowledge Audit)
time.sleep(1.2)
with get_db() as cur:
    cur.execute("""
        SELECT id, conversation_type, sender_id, recipient_id, content, is_encrypted, iv, ephemeral_key
        FROM messages
        WHERE sender_id = %s AND recipient_id = %s
        ORDER BY id DESC LIMIT 1;
    """, (user_a["id"], user_b["id"]))
    row = cur.fetchone()

assert row is not None
assert row["is_encrypted"] is True
assert plaintext not in row["content"], "SECURITY BREACH: Plaintext found in database!"
assert row["content"] == ciphertext_b64
print("\n--- ZERO-KNOWLEDGE SERVER AUDIT ---")
print(f"PostgreSQL Row ID: {row['id']}")
print(f"Stored is_encrypted: {row['is_encrypted']}")
print(f"Stored Raw Content: {row['content']}")
print("Audit Result: PASSED! Database stores ONLY encrypted ciphertext bytes.")
print("------------------------------------\n")

# Step 8: Bob queries history from /api/messages/history
res = requests.get(f"{BASE_URL}/messages/history?type=direct&target_id={user_a['id']}", headers=headers_b)
assert res.status_code == 200
history_msgs = res.json()["messages"]
assert len(history_msgs) >= 1
received_msg = history_msgs[-1]
assert received_msg["is_encrypted"] is True

# Step 9: Bob reconstructs Alice's ephemeral public key & decrypts with Bob's private key
eph_data = json.loads(received_msg["ephemeral_key"])
# Decode base64url numbers
def b64url_decode(s):
    rem = len(s) % 4
    if rem > 0:
        s += '=' * (4 - rem)
    return base64.urlsafe_b64decode(s)

x_int = int.from_bytes(b64url_decode(eph_data["x"]), 'big')
y_int = int.from_bytes(b64url_decode(eph_data["y"]), 'big')
alice_ephemeral_pub_recon = ec.EllipticCurvePublicNumbers(x_int, y_int, ec.SECP256R1()).public_key()

# Bob computes shared secret
shared_secret_bob = bob_priv_key.exchange(ec.ECDH(), alice_ephemeral_pub_recon)
hkdf_bob = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=None,
    info=b"mini_im_e2ee_direct",
)
aes_key_bob = hkdf_bob.derive(shared_secret_bob)
assert aes_key_alice == aes_key_bob, "Key derivation mismatch between Alice and Bob!"

# Bob decrypts ciphertext using AES-256-GCM
aesgcm_bob = AESGCM(aes_key_bob)
rx_iv = base64.b64decode(received_msg["iv"])
rx_ciphertext = base64.b64decode(received_msg["content"])
decrypted_bytes = aesgcm_bob.decrypt(rx_iv, rx_ciphertext, None)
decrypted_plaintext = decrypted_bytes.decode('utf-8')

print("6. Bob decrypted received message with private key:")
print(f"   Decrypted Plaintext: '{decrypted_plaintext}'")
assert decrypted_plaintext == plaintext
print("7. Cryptographic Plaintext Match: 100% IDENTICAL!")

print("\n" + "="*65)
print("SUCCESS: END-TO-END ENCRYPTION (E2EE) FULLY VERIFIED!")
print("="*65)
