from app.utils.jwt_handler import create_access_token, verify_token

token = create_access_token({
    "email": "admin@gmail.com",
    "role": "admin"
})

print("TOKEN:\n")
print(token)

print("\nDecoded:\n")

print(verify_token(token))