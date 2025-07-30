from flask import Flask, request, jsonify
import hmac
import hashlib
import os
from datetime import datetime, timedelta
from main import logger, TRAKTEER_PACKAGE_MAPPING, update_vip_status

app = Flask(__name__)

@app.route('/trakteer_webhook', methods=['POST'])
def handle_webhook():
    try:
        signature = request.headers.get('X-Trakteer-Signature')
        payload = request.get_data(as_text=True)
        secret = os.getenv('TRAKTEER_WEBHOOK_SECRET').encode()
        
        expected_signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return jsonify({"status": "error", "message": "Invalid signature"}), 403
            
        data = request.json
    
        if data['status'] == 'PAID':
            package_id = data['trakteer_id']
            email = data['customer']['email']
            
            if "@vipbot.com" in email:
                user_id = email.split("@")[0]
                
                if package_id in TRAKTEER_PACKAGE_MAPPING:
                    if update_vip_status(user_id, package_id):
                        logger.info(f"VIP updated for user {user_id} with package {package_id}")
                        return jsonify({"status": "success"})
        
        return jsonify({"status": "ignored"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000)