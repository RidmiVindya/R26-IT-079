import os
from pathlib import Path
import smtplib
import ssl
from email.utils import formataddr
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

MAIL_EMAIL = os.getenv("MAIL_EMAIL")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))


def send_email(receiver_email: str, subject: str, body: str, html_body: str | None = None):
    try:
        if not all([MAIL_EMAIL, MAIL_PASSWORD, MAIL_SERVER, MAIL_PORT]):
            raise ValueError("Mail configuration is incomplete.")

        message = MIMEMultipart("alternative")
        message["From"] = formataddr(("Smart Karawala", MAIL_EMAIL))
        message["To"] = receiver_email
        message["Subject"] = subject

        message.attach(MIMEText(body, "plain"))

        if html_body:
            message.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()

        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(MAIL_EMAIL, MAIL_PASSWORD)
            server.sendmail(MAIL_EMAIL, receiver_email, message.as_string())

        return True

    except Exception as e:
        print("Email Error:", e)
        return False