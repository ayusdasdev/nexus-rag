import pytest

from app.providers.embeddings import BgeEmbedder, Bm25Embedder, is_cached

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_cached(), reason="embedding models not cached; run make fetch-models"
    ),
]


def test_bge_embedder_returns_768_dimensional_vectors() -> None:
    vectors = BgeEmbedder().embed_documents(
        ["Nexus Widgets are battery-powered sensors."]
    )

    assert len(vectors) == 1
    assert len(vectors[0]) == BgeEmbedder.dim == 768


def test_bm25_embedder_returns_sparse_terms_for_text() -> None:
    embedding = Bm25Embedder().embed_documents(
        ["battery powered sensors report readings"]
    )[0]

    assert embedding.indices
    assert len(embedding.indices) == len(embedding.values)
    assert all(value > 0 for value in embedding.values)
