"""Import all models here so Base.metadata / Alembic autogenerate can discover them."""
from app.models.job import Job  # noqa: F401
from app.models.kb_chunk import KBChunk  # noqa: F401
from app.models.kb_source import KBSource  # noqa: F401
from app.models.knowledge_base import KnowledgeBase  # noqa: F401
