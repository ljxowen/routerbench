import mongomock

from embedding.cache import EmbeddingCache


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_embedding_cache():
    cache = EmbeddingCache("server.example.com")
    # Must be a tuple: batch_get_embedding is memoized with lru_cache.
    prompts = ("test1", "test2", "test3")
    embedding_model = "all-MiniLM-L12-v2"
    embeddings = cache.batch_get_embedding(prompts, embedding_model)
    assert len(embeddings) == len(prompts)

    # Drop the in-process memoization so the second call exercises the Mongo
    # read path (the embeddings should already be persisted there).
    cache.batch_get_embedding.cache_clear()
    cached = cache.batch_get_embedding(prompts, embedding_model)
    assert len(cached) == len(prompts)
