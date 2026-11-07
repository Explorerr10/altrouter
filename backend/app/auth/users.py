import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .passwords import hash_password, verify_password

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"


@dataclass
class User:
    username: str
    password_hash: str
    role: str = "admin"


class UsersStore:
    def __init__(self, config_dir: Path):
        config_dir.mkdir(parents=True, exist_ok=True)
        self.path = config_dir / "config.json"

    def load(self) -> list[User]:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            users = [
                User(
                    username=item["username"],
                    password_hash=item["password_hash"],
                    role=item.get("role", "admin"),
                )
                for item in data.get("users", [])
            ]
            if users:
                return users
        users = [User(username=DEFAULT_USERNAME, password_hash=hash_password(DEFAULT_PASSWORD))]
        self.save(users)
        return users

    def save(self, users: list[User]) -> None:
        data = {
            "users": [
                {"username": u.username, "password_hash": u.password_hash, "role": u.role}
                for u in users
            ]
        }
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def verify(self, username: str, password: str) -> User | None:
        for user in self.load():
            if user.username == username and verify_password(password, user.password_hash):
                return user
        return None

    def set_password(self, username: str, password: str) -> bool:
        users = self.load()
        for user in users:
            if user.username == username:
                user.password_hash = hash_password(password)
                self.save(users)
                return True
        return False

    def create(self, username: str, password: str, role: str) -> User:
        users = self.load()
        if any(u.username == username for u in users):
            raise ValueError("Пользователь уже существует")
        user = User(username=username, password_hash=hash_password(password), role=role)
        users.append(user)
        self.save(users)
        return user

    def remove(self, username: str) -> bool:
        users = self.load()
        rest = [u for u in users if u.username != username]
        if len(rest) == len(users):
            return False
        self.save(rest)
        return True

    def set_role(self, username: str, role: str) -> bool:
        users = self.load()
        for u in users:
            if u.username == username:
                u.role = role
                self.save(users)
                return True
        return False

    def count_admins(self) -> int:
        return sum(1 for u in self.load() if u.role == "admin")

    def has_default_password(self, username: str) -> bool:
        for user in self.load():
            if user.username == username:
                return verify_password(DEFAULT_PASSWORD, user.password_hash)
        return False
