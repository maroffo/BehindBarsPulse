# ABOUTME: Diagnostic script to test SMTP authentication with AWS SES.
# ABOUTME: Validates .env configuration and logs detailed protocol steps.

"""
SMTP/SES Diagnostic Tool

This script connects to the configured SMTP host, establishes a TLS connection,
attempts to login with the SES SMTP credentials loaded from .env, and optionally
sends a test email.

Usage:
    # Run a simple diagnostic check
    uv run python scripts/test_smtp.py

    # Run and send a test email to a specific address
    uv run python scripts/test_smtp.py --send-to test@example.com
"""

import argparse
import socket
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

# Add src folder to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behind_bars_pulse.config import get_settings


def run_diagnostics(recipient: str | None = None) -> bool:
    """Run step-by-step SMTP connection and authentication diagnostics."""
    print("=== AWS SES SMTP DIAGNOSTICS ===")
    
    # 1. Load Settings
    print("[1/5] Loading settings from configuration...")
    try:
        settings = get_settings()
        host = settings.smtp_host
        port = settings.smtp_port
        sender = settings.sender_email
        
        # Access SecretStr safely
        usr = settings.ses_usr.get_secret_value() if settings.ses_usr else None
        pwd = settings.ses_pwd.get_secret_value() if settings.ses_pwd else None
        
        print(f"  SMTP Host: {host}")
        print(f"  SMTP Port: {port}")
        print(f"  Sender: {sender}")
        print(f"  Username configured: {'YES' if usr else 'NO'}")
        print(f"  Password configured: {'YES' if pwd else 'NO'}")
        
        if not usr or not pwd:
            print("\n❌ ERROR: SES credentials (ses_usr/ses_pwd) are missing from your configuration or .env file.")
            return False
    except Exception as e:
        print(f"\n❌ ERROR: Failed to load settings: {e}")
        return False

    # 2. DNS and Network Connection
    print("\n[2/5] Testing network connection to SMTP host...")
    try:
        # Resolve hostname first
        print(f"  Resolving {host}...")
        ip = socket.gethostbyname(host)
        print(f"  Resolved to IP: {ip}")
        
        # Attempt TCP socket connection
        print(f"  Connecting socket to {host}:{port}...")
        with socket.create_connection((host, port), timeout=10) as sock:
            print("  Socket connection successful!")
    except socket.gaierror:
        print(f"\n❌ ERROR: DNS resolution failed for {host}. Are you connected to the internet?")
        return False
    except socket.timeout:
        print(f"\n❌ ERROR: Connection timed out to {host}:{port}. Is the port blocked or host unreachable?")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: Failed to establish network socket: {e}")
        return False

    # 3. SMTP Protocol & TLS Negotiation
    print("\n[3/5] Starting SMTP handshake and TLS negotiation...")
    server = None
    try:
        print(f"  Initializing SMTP connection to {host}:{port}...")
        server = smtplib.SMTP(host, port, timeout=15)
        
        print("  Sending EHLO...")
        ehlo_code, ehlo_msg = server.ehlo()
        print(f"  EHLO Response: {ehlo_code} - {ehlo_msg.decode('utf-8', errors='ignore').strip().replace(chr(10), ' | ')}")
        
        # Check TLS capability
        if not server.has_extn("starttls"):
            print("  ⚠️ WARNING: Server does not announce STARTTLS extension.")
            
        print("  Negotiating TLS encryption (STARTTLS)...")
        tls_code, tls_msg = server.starttls()
        print(f"  STARTTLS Response: {tls_code} - {tls_msg.decode('utf-8', errors='ignore').strip()}")
        
        print("  Sending second EHLO post-TLS...")
        ehlo_code, ehlo_msg = server.ehlo()
        print(f"  Post-TLS EHLO Response: {ehlo_code} - {ehlo_msg.decode('utf-8', errors='ignore').strip().replace(chr(10), ' | ')}")
        
    except Exception as e:
        print(f"\n❌ ERROR: SMTP protocol / TLS negotiation failed: {e}")
        if server:
            try:
                server.close()
            except Exception:
                pass
        return False

    # 4. Authentication
    print("\n[4/5] Attempting authentication with credentials...")
    try:
        print("  Authenticating...")
        auth_code, auth_msg = server.login(usr, pwd)
        print(f"  ✅ SUCCESS: Authentication accepted! Response: {auth_code} - {auth_msg.decode('utf-8', errors='ignore').strip()}")
    except smtplib.SMTPAuthenticationError as e:
        print("\n❌ ERROR: SMTP Authentication Failed.")
        print("  This means your AWS SES SMTP username or password is incorrect, expired, or has been revoked.")
        print(f"  Details: {e}")
        try:
            server.close()
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"\n❌ ERROR: Authentication process failed unexpectedly: {e}")
        try:
            server.close()
        except Exception:
            pass
        return False

    # 5. Send Test Email (Optional)
    if recipient:
        print(f"\n[5/5] Attempting to send a test email to {recipient}...")
        try:
            msg = EmailMessage()
            msg["Subject"] = "BehindBars SES SMTP Diagnostic Test Email"
            msg["From"] = f"{settings.sender_name} <{sender}>"
            msg["To"] = recipient
            msg.set_content(
                "This is a diagnostic test email from your BehindBarsPulse installation.\n\n"
                "If you receive this message, your AWS SES SMTP credentials are valid, and the "
                "EmailSender service can send emails successfully!\n\n"
                "Best,\n"
                "BehindBarsPulse Diagnostics"
            )
            
            print(f"  Sending test email from {sender} to {recipient}...")
            server.sendmail(sender, [recipient], msg.as_string())
            print("  ✅ SUCCESS: Test email sent successfully!")
        except smtplib.SMTPRecipientsRefused as e:
            print(f"\n❌ ERROR: Recipient refused: {recipient}.")
            print("  This usually happens if your AWS SES account is in sandbox mode and the recipient address has not been verified.")
            print(f"  Details: {e}")
        except smtplib.SMTPSenderRefused as e:
            print(f"\n❌ ERROR: Sender refused: {sender}.")
            print("  This usually happens if the sender email address has not been verified in AWS SES.")
            print(f"  Details: {e}")
        except Exception as e:
            print(f"\n❌ ERROR: Failed to send test email: {e}")
    else:
        print("\n[5/5] Skipping test email send (no recipient specified).")
        print("  To send a test email, run with: --send-to your-email@example.com")

    # Clean close
    try:
        print("\nClosing connection gracefully...")
        server.quit()
        print("Connection closed.")
    except Exception:
        pass

    print("\n🎉 DIAGNOSTICS COMPLETE: All connection and authentication steps passed!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AWS SES SMTP Diagnostic Utility")
    parser.add_argument(
        "--send-to",
        help="Email address to send a test email to (triggers full sending verification)",
        default=None
    )
    
    args = parser.parse_args()
    
    success = run_diagnostics(args.send_to)
    sys.exit(0 if success else 1)
