import uuid

# Fixed forever: this id must never vary across environments, since the same
# value is used as both the Postgres chunk id and the Qdrant point id.
# Deliberately not a Settings field (see docs/decisions) - an env-specific
# override here would silently desync Postgres and Qdrant ids.
CHUNK_NAMESPACE = uuid.UUID("5a3f6e8e-2b1a-4b8d-9b8e-5b1b7b9f9a3e")


def chunk_id(document_id: uuid.UUID, chunk_index: int) -> uuid.UUID:
    return uuid.uuid5(CHUNK_NAMESPACE, f"{document_id}:{chunk_index}")
