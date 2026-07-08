from fastapi import APIRouter
from fastapi import Depends
from app.utils.dependencies import get_current_user

from app.models.user_model import (
    UserRegister,
    UserLogin,
    VerifyOTP,
    ForgotPassword,
    ResetPassword,
    ResendOTP
)
from app.services.auth_service import (
    register_user,
    login_user,
    verify_account,
    forgot_password,
    reset_password,
    resend_verification_otp
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# ---------------- Register ----------------

@router.post("/register")
def register(user: UserRegister):
    return register_user(user)


# ---------------- Login ----------------

@router.post("/login")
def login(user: UserLogin):
    return login_user(user)


# ---------------- Verify Email ----------------

@router.post("/verify-account")
def verify(otp: VerifyOTP):
    return verify_account(otp)


# ---------------- Forgot Password ----------------

@router.post("/forgot-password")
def forgot(data: ForgotPassword):
    return forgot_password(data)


# ---------------- Reset Password ----------------

@router.post("/reset-password")
def reset(data: ResetPassword):
    return reset_password(data)


@router.post("/resend-verification-otp")
def resend(data: ResendOTP):
    return resend_verification_otp(data)


@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return {
        "success": True,
        "user": current_user
    }