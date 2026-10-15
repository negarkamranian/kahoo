from cryptography.fernet import Fernet

from backend.instagram.oauth import login_configured


def generate_key(_args):
    return {"key": Fernet.generate_key().decode("ascii")}


def status(_args):
    return {"configured": login_configured()}
