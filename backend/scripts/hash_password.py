from getpass import getpass

from pwdlib import PasswordHash


def main() -> None:
    password = getpass()
    password_hash = PasswordHash.recommended().hash(password)
    print(password_hash)


if __name__ == "__main__":
    main()
