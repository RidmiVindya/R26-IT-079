import random
from datetime import datetime, timedelta, timezone


import random
from datetime import datetime, timedelta


def generate_otp():
    return str(random.randint(100000, 999999))


def otp_expiry():
    # OTP valid for 5 minutes
    return datetime.utcnow() + timedelta(minutes=5)


def is_otp_expired(expire_time):
    if expire_time is None:
        return True

    # Compare naive UTC datetimes
    return datetime.utcnow() > expire_time