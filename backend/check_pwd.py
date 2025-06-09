from auth import verify_password

hashed = "$2b$12$h2yPbBDGoeT66iGyhAfL6OlLMJVA4s3huXoKoJGnKjApzwhqWzQ/q"
print("verify admin123:", verify_password("admin123", hashed))
print("verify wrongpw:", verify_password("wrongpw", hashed))
