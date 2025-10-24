from flask import Flask, render_template, request, jsonify
import os
from solana.rpc.api import Client

app = Flask(__name__)

# Connect to Solana mainnet RPC
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
solana_client = Client(SOLANA_RPC_URL)

# Example wallet public key (replace with your own)
USER_PUBLIC_KEY = "YOUR_WALLET_PUBLIC_KEY_HERE"

@app.route("/")
def index():
    try:
        balance_response = solana_client.get_balance(USER_PUBLIC_KEY)
        balance_sol = balance_response['result']['value'] / 1e9
    except Exception:
        balance_sol = "N/A"
    return render_template("index.html", balance=balance_sol)

@app.route("/trade", methods=["POST"])
def trade():
    token = request.form.get("token").upper()
    action = request.form.get("action")
    amount = request.form.get("amount")

    # Placeholder — here’s where you’d connect wallet & send real transaction
    tx_message = f"Simulated {action} of {amount} {token} on Solana mainnet."

    print(tx_message)
    return jsonify({"message": tx_message})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))  # default port 7860
    try:
        app.run(host="0.0.0.0", port=port)
    except OSError:
        # If port is busy, try next
        app.run(host="0.0.0.0", port=port + 1)
