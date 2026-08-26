"""Import all models here so Base.metadata / Alembic autogenerate can discover them."""
from app.models.chunk import Chunk  # noqa: F401
from app.models.file import File  # noqa: F401
from app.models.job import Job  # noqa: F401
