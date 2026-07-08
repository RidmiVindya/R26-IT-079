from app.services.email_service import send_email

success = send_email(
    receiver_email="sanjaya2170@gmail.com",
    subject="Smart Karawala Test",
    body="""
Hello,

This is a test email from Smart Karawala Authentication System.

If you received this email, Gmail SMTP is working successfully.

Regards,
Smart Karawala Team
"""
)

print("Success:", success)