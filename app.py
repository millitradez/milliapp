from flask import Flask, render_template, request, jsonify
from solders.keypair import Keypair
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from spl.token.constants import TOKEN_PROGRAM_ID
from solana.rpc.types import TxOpts
import base58
import os

app = Flask(__name__)

# Connect to Solana Mainnet
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
client = Client(SOLANA_RPC)

# 🔐 Load your private key from environment variable
# Set it locally before running: export PRIVATE_KEY="..."
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

if not PRIVATE_KEY:
    print("⚠️ No PRIVATE_KEY found in environment. Set it before trading.")
    TRADING_ENABLED = False
else:
    wallet = Keypair.from_secret_key(base58.b58decode(PRIVATE_KEY))
    print(f"✅ Wallet loaded: {wallet.pubkey()}")
    TRADING_ENABLED = True


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/trade", methods=["POST"])
def trade():
    if not TRADING_ENABLED:
        return jsonify({"message": "Trading not enabled. Missing private key."}), 400

    data = request.get_json()
    from_token = data.get("from_token", "").upper()
    to_token = data.get("to_token", "").upper()
    amount = float(data.get("amount", 0))

    if amount <= 0:
        return jsonify({"message": "Invalid amount"}), 400

    try:
        # 💸 For now, we'll just simulate a SOL transfer (upgradeable to swaps)
        # Replace this with Jupiter or Orca swap API later
        recipient = wallet.pubkey()  # self-transfer for testing
        lamports = int(amount * 1_000_000_000)

        txn = Transaction()
        txn.add(
            transfer(
                TransferParams(
                    from_pubkey=wallet.pubkey(),
                    to_pubkey=recipient,
                    lamports=lamports
                )
            )
        )

        result = client.send_transaction(txn, wallet, opts=TxOpts(skip_preflight=True))
        sig = result.value
        explorer_url = f"https://explorer.solana.com/tx/{sig}?cluster=mainnet-beta"

        return jsonify({
            "message": f"✅ Transaction sent!",
            "signature": sig,
            "explorer": explorer_url
        })
    except Exception as e:
        return jsonify({"message": f"❌ Error: {str(e)}"}), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 7860))  # default for HF Spaces
    try:
        app.run(host="0.0.0.0", port=port)
    except OSError:
        app.run(host="0.0.0.0", port=port + 1)
