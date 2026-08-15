import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

MAIL_EMAIL = os.getenv("MAIL_EMAIL")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))


def send_email(receiver_email: str, subject: str, body: str):
    # If SMTP is not configured, skip sending instead of blocking the caller.
    # Registration/OTP flows must not hang or fail just because email is down.
    if not MAIL_SERVER or not MAIL_EMAIL or not MAIL_PASSWORD:
        print(
            "Email skipped: SMTP not configured "
            "(MAIL_SERVER/MAIL_EMAIL/MAIL_PASSWORD missing)."
        )
        return False

    try:
        message = MIMEMultipart()
        message["From"] = MAIL_EMAIL
        message["To"] = receiver_email
        message["Subject"] = subject

        message.attach(MIMEText(body, "plain"))

        # timeout so a slow/unreachable SMTP server fails fast instead of
        # hanging the HTTP request (which surfaces as a CORS error in browsers).
        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=10)
        server.starttls()
        server.login(MAIL_EMAIL, MAIL_PASSWORD)
        server.sendmail(MAIL_EMAIL, receiver_email, message.as_string())
        server.quit()

        return True

    except Exception as e:
        print("Email Error:", e)
        return False