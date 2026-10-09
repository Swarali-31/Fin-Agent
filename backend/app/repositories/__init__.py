"""Repository interfaces and runtime implementations."""

from backend.app.repositories.base import PersistenceNotConfigured, Repository
from backend.app.repositories.postgres import PostgresRepository, get_repository

__all__ = [
    "PersistenceNotConfigured",
    "PostgresRepository",
    "Repository",
    "get_repository",
]
