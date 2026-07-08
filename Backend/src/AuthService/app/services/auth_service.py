from datetime import datetime, timezone

from app.database import users_collection
from app.utils.security import hash_password, verify_password
from app.utils.jwt_handler import create_access_token

from app.services.otp_service import generate_otp, otp_expiry
from app.services.email_service import send_email
from app.services.otp_service import is_otp_expired
from datetime import datetime, timezone


def register_user(user):

    existing = users_collection.find_one({"email": user.email})

    if existing:
        return {
            "success": False,
            "message": "Email already registered."
        }

    otp = generate_otp()
    expire = otp_expiry()

    new_user = {
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "password": hash_password(user.password),

        "role": "customer",

        "is_active": True,
        "is_verified": False,

        "verification_otp": otp,
        "verification_expire": expire,

        "reset_otp": None,
        "reset_expire": None,
        "created_at": datetime.utcnow()
    }

    users_collection.insert_one(new_user)

    body = f"""
Hello {user.full_name},

Welcome to Smart Karawala.

Your account verification code is:

{otp}

This OTP is valid for 5 minutes.

Regards,
Smart Karawala Team
"""

    send_email(
        receiver_email=user.email,
        subject="Smart Karawala - Account Verification",
        body=body
    )

    return {
        "success": True,
        "message": "Registration successful. Verification OTP has been sent to your email."
    }


def login_user(user):

    db_user = users_collection.find_one({"email": user.email})

    if db_user is None:
        return {
            "success": False,
            "message": "Invalid email or password."
        }

    if not verify_password(user.password, db_user["password"]):
        return {
            "success": False,
            "message": "Invalid email or password."
        }

    if not db_user.get("is_verified", False):
        return {
            "success": False,
            "message": "Please verify your email before logging in."
        }

    token = create_access_token({
        "user_id": str(db_user["_id"]),
        "email": db_user["email"],
        "role": db_user["role"]
    })

    return {
        "success": True,
        "access_token": token,
        "token_type": "Bearer",
        "user": {
            "id": str(db_user["_id"]),
            "name": db_user["full_name"],
            "email": db_user["email"],
            "role": db_user["role"]
        }
    }



def verify_account(data):

    user = users_collection.find_one({"email": data.email})

    if user is None:
        return {
            "success": False,
            "message": "User not found."
        }

    if user.get("is_verified"):
        return {
            "success": False,
            "message": "Account already verified."
        }

    if user["verification_otp"] != data.otp:
        return {
            "success": False,
            "message": "Invalid OTP."
        }

    if is_otp_expired(user["verification_expire"]):
        return {
            "success": False,
            "message": "OTP expired."
        }

    users_collection.update_one(
        {"email": data.email},
        {
            "$set": {
                "is_verified": True
            },
            "$unset": {
                "verification_otp": "",
                "verification_expire": ""
            }
        }
    )

    return {
        "success": True,
        "message": "Account verified successfully."
    }


def forgot_password(data):

    user = users_collection.find_one({"email": data.email})

    if user is None:
        return {
            "success": False,
            "message": "Email not found."
        }

    otp = generate_otp()
    expire = otp_expiry()

    users_collection.update_one(
        {"email": data.email},
        {
            "$set": {
                "reset_otp": otp,
                "reset_expire": expire
            }
        }
    )

    body = f"""
Hello {user['full_name']},

You requested to reset your password.

Your OTP is:

{otp}

This OTP is valid for 5 minutes.

Regards,
Smart Karawala Team
"""

    send_email(
        receiver_email=data.email,
        subject="Smart Karawala - Reset Password",
        body=body
    )

    return {
        "success": True,
        "message": "Reset OTP sent successfully."
    }


def reset_password(data):

    user = users_collection.find_one({"email": data.email})

    if user is None:
        return {
            "success": False,
            "message": "User not found."
        }

    if user["reset_otp"] != data.otp:
        return {
            "success": False,
            "message": "Invalid OTP."
        }

    if is_otp_expired(user["reset_expire"]):
        return {
            "success": False,
            "message": "OTP expired."
        }

    users_collection.update_one(
        {"email": data.email},
        {
            "$set": {
                "password": hash_password(data.new_password)
            },
            "$unset": {
                "reset_otp": "",
                "reset_expire": ""
            }
        }
    )

    return {
        "success": True,
        "message": "Password reset successfully."
    }

def resend_verification_otp(data):

    user = users_collection.find_one({"email": data.email})

    if user is None:
        return {
            "success": False,
            "message": "User not found."
        }

    if user.get("is_verified"):
        return {
            "success": False,
            "message": "Account already verified."
        }

    otp = generate_otp()
    expire = otp_expiry()

    users_collection.update_one(
        {"email": data.email},
        {
            "$set": {
                "verification_otp": otp,
                "verification_expire": expire
            }
        }
    )

    body = f"""
Hello {user['full_name']},

Your new verification code is:

{otp}

This OTP is valid for 5 minutes.

Regards,
Smart Karawala Team
"""

    send_email(
        receiver_email=data.email,
        subject="Smart Karawala - New Verification OTP",
        body=body
    )

    return {
        "success": True,
        "message": "Verification OTP sent successfully."
    }