import cryptocode


def encrypt(ssh_pass: str, key: str) -> str:
    """Encrypt ssh password, use cryptocode and custom token"""
    return cryptocode.encrypt(ssh_pass, key)


def decrypt(ssh_pass: str, key: str) -> str:
    """Decrypt ssh password, use cryptocode and custom token"""
    return cryptocode.decrypt(ssh_pass, key)
