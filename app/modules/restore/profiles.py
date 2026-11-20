"""
Where restore profiles come from.

Built-in profiles are YAML files shipped in ./profiles (always available, no network).
User profiles live in the database (see db_store.DbUserProfileRepo). A job stores a
SNAPSHOT of the YAML it was created with, so neither a later edit of a user profile
nor an application update of a built-in one changes a job that already exists.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from app.modules.restore.schema import parse_profile_yaml

log = logging.getLogger("nabs.restore")

BUILTIN = "builtin"
USER = "user"
SOURCES = (BUILTIN, USER)
BUILTIN_DIR = Path(__file__).parent / "profiles"


@dataclass(frozen=True)
class ProfileText:
    source: str
    key: str
    version: int
    content: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class ProfileProvider(Protocol):
    def get(self, source: str, key: str) -> Optional[ProfileText]:
        ...


class BuiltinProfileProvider:
    """
    Loads and validates every *.yaml of the directory once. A file that is invalid,
    is not marked `builtin: true`, or whose id differs from its file name is skipped
    and listed in `errors`; it can never be selected.
    """

    def __init__(self, directory: Path = BUILTIN_DIR) -> None:
        self._profiles: Dict[str, ProfileText] = {}
        self.errors: List[str] = []
        if not Path(directory).is_dir():
            return
        for path in sorted(Path(directory).glob("*.yaml")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                self.errors.append(f"{path.name}: cannot read ({type(error).__name__})")
                continue
            result = parse_profile_yaml(text, allow_builtin=True)
            if not result.ok:
                self.errors.append(f"{path.name}: {result.errors[0]}")
            elif not result.profile.builtin:
                self.errors.append(f"{path.name}: 'builtin: true' is required")
            elif result.profile.id != path.stem:
                self.errors.append(
                    f"{path.name}: id {result.profile.id!r} != file name"
                )
            else:
                self._profiles[result.profile.id] = ProfileText(
                    BUILTIN, result.profile.id, result.profile.profile_version, text
                )
        for message in self.errors:
            log.error("built-in restore profile rejected: %s", message)

    def get(self, source: str, key: str) -> Optional[ProfileText]:
        return self._profiles.get(key) if source == BUILTIN else None

    def keys(self) -> List[str]:
        return sorted(self._profiles)


class CompositeProfileProvider:
    def __init__(self, builtin: ProfileProvider, user: ProfileProvider) -> None:
        self._by_source = {BUILTIN: builtin, USER: user}

    def get(self, source: str, key: str) -> Optional[ProfileText]:
        provider = self._by_source.get(source)
        return provider.get(source, key) if provider else None
