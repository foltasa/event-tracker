from unittest.mock import MagicMock, patch

from app.rag.embeddings import embed_texts


@patch("app.rag.embeddings._client")
def test_embed_texts_returns_one_vector_per_input(mock_client):
    mock_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 1536), MagicMock(embedding=[0.2] * 1536)],
    )

    vectors = embed_texts(["hello", "world"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 1536
    mock_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input=["hello", "world"],
    )


@patch("app.rag.embeddings._client")
def test_embed_texts_empty_returns_empty(mock_client):
    assert embed_texts([]) == []
    mock_client.embeddings.create.assert_not_called()
