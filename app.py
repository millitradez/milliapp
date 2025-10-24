# app.py
import os
import json
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# Solana imports
from solana.rpc.api import Client
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.rpc.types import TxOpts
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_ACCOUNT_PROGRAM_ID
from spl.token.client import Token
from spl.token.instructions import get_associated_token_address, create_associated_token_account

load_dotenv()

APP_SECRET = os.environ.get("SECRET_KEY", "dev-secret")
RPC_URL = os.environ.get("RPC_URL", "https://api.devnet.solana.com")
PRIVATE_KEY_B58 = os.environ.get("PRIVATE_KEY", None)  # base58 or JSON of secret_key
PUBLIC_KEY_STR = os.environ.get("PUBLIC_KEY", None)

if PRIVATE_KEY_B58 is None or PUBLIC_KEY_STR is None:
    print("Warning: PRIVATE_KEY or PUBLIC_KEY env var is missing. The app won't be able to sign transactions.")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = APP_SECRET

client = Client(RPC_URL)

def load_keypair_from_env():
    """
    Accept either:
      - a base58-encoded secret key (one-string) OR
      - a JSON array string with 64 ints (like solana CLI exported file)
    Returns Keypair or None
    """
    if PRIVATE_KEY_B58 is None:
        return None
    try:
        # Try JSON array first
        if PRIVATE_KEY_B58.strip().startswith("["):
            import ast
            arr = ast.literal_eval(PRIVATE_KEY_B58)
            return Keypair.from_secret_key(bytes(arr))
        # Else assume base58: solana-py Keypair.from_secret_key expects bytes; user may provide base58 decode
        from base58 import b58decode
        sk = b58decode(PRIVATE_KEY_B58)
        return Keypair.from_secret_key(sk)
    except Exception as e:
        print("Failed to load keypair:", e)
        return None

SIGNER = load_keypair_from_env()
if SIGNER:
    SIGNER_PUBKEY = SIGNER.public_key
else:
    SIGNER_PUBKEY = PublicKey(PUBLIC_KEY_STR) if PUBLIC_KEY_STR else None

@app.route("/")
def index():
    return render_template("index.html", public_key=str(SIGNER_PUBKEY) if SIGNER_PUBKEY else "")

@app.route("/balance", methods=["GET"])
def get_balance():
    """
    Returns SOL balance (lamports -> SOL).
    """
    pub = request.args.get("pub") or (str(SIGNER_PUBKEY) if SIGNER_PUBKEY else None)
    if not pub:
        return jsonify({"error": "No public key provided"}), 400
    try:
        bal_resp = client.get_balance(PublicKey(pub))
        lamports = bal_resp["result"]["value"]
        sol = lamports / 1_000_000_000
        return jsonify({"balance_sol": sol, "lamports": lamports})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/send_sol", methods=["POST"])
def send_sol():
    """
    Send SOL from the configured signer to a recipient.
    Body JSON: {"to": "<recipient_pubkey>", "amount_sol": 0.01}
    """
    if SIGNER is None:
        return jsonify({"error": "Server signer not configured"}), 500
    data = request.get_json() or {}
    to = data.get("to")
    amount = float(data.get("amount_sol", 0))
    if not to or amount <= 0:
        return jsonify({"error": "invalid params"}), 400

    try:
        to_pub = PublicKey(to)
        lamports = int(amount * 1_000_000_000)
        txn = Transaction()
        txn.add(
            transfer(
                TransferParams(
                    from_pubkey=SIGNER.public_key,
                    to_pubkey=to_pub,
                    lamports=lamports,
                )
            )
        )
        resp = client.send_transaction(txn, SIGNER, opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed"))
        return jsonify({"txid": resp["result"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/send_token", methods=["POST"])
def send_token():
    """
    Transfer an SPL token from the signer to recipient.
    Body JSON: {
      "to": "<recipient_pubkey>",
      "mint": "<token_mint_address>",
      "amount": 1.23,        # human amount
      "decimals": 6          # token decimals
    }
    Notes:
      - The signer must hold the token in an associated token account for the mint.
      - If the recipient lacks an associated token account, this endpoint will attempt to create it.
    """
    if SIGNER is None:
        return jsonify({"error": "Server signer not configured"}), 500

    data = request.get_json() or {}
    to = data.get("to")
    mint = data.get("mint")
    amount = float(data.get("amount", 0))
    decimals = int(data.get("decimals", 0))

    if not to or not mint or amount <= 0:
        return jsonify({"error": "invalid params"}), 400

    try:
        mint_pub = PublicKey(mint)
        to_pub = PublicKey(to)
        token_client = Token(client, mint_pub, TOKEN_PROGRAM_ID, SIGNER)

        # Determine associated token accounts
        sender_ata = get_associated_token_address(SIGNER.public_key, mint_pub)
        recipient_ata = get_associated_token_address(to_pub, mint_pub)

        # If recipient ATA doesn't exist, create it in a transaction
        resp = client.get_account_info(recipient_ata)
        txn = Transaction()
        if resp["result"]["value"] is None:
            # add create associated token account instruction
            txn.add(
                create_associated_token_account(
                    payer=SIGNER.public_key,
                    owner=to_pub,
                    mint=mint_pub,
                )
            )

        # Transfer amount in smallest units
        ui_amount = int(amount * (10 ** decimals))
        # Use token_client.transfer to build instruction
        # token_client.transfer requires source, dest, owner, amount
        transfer_ix = token_client.transfer(
            source=sender_ata,
            dest=recipient_ata,
            owner=SIGNER.public_key,
            amount=ui_amount,
            opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed"),
        )
        # NOTE: token_client.transfer sends the transaction itself and returns result.
        # But since we might have created an ATA in txn, better to combine create ATA + transfer in a single transaction.
        # So we'll craft the transfer instruction using spl.token instructions instead:
        # Simpler: if we created ATA above, send create ATA transaction first, then call token_client.transfer.

        if resp["result"]["value"] is None:
            # send create ATA first
            create_resp = client.send_transaction(txn, SIGNER, opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed"))
            # now perform transfer
        # perform transfer using token_client.transfer (this will sign+send)
        tx_resp = token_client.transfer(
            source=sender_ata,
            dest=recipient_ata,
            owner=SIGNER.public_key,
            amount=ui_amount,
        )
        return jsonify({"txid": tx_resp["result"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "rpc": RPC_URL})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 7860))  # default port 7860
    try:
        app.run(host="0.0.0.0", port=port)
    except OSError:
        # If the port is busy, try a new one automatically
        app.run(host="0.0.0.0", port=port + 1)
