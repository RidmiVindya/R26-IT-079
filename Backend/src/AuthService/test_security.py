from app.utils.security import hash_password, verify_password

password = "123456"

hashed = hash_password(password)

print("Original :", password)
print("Hash :", hashed)

print(verify_password("123456", hashed))
print(verify_password("111111", hashed))