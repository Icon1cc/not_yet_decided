from openai import OpenAI


def embed_texts(texts: list[str], model: str, api_key: str) -> list[list[float]]:
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    results: list[list[float]] = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(model=model, input=batch)
        assert len(response.data) == len(batch), f"Expected {len(batch)} embeddings, got {len(response.data)}"
        results.extend(item.embedding for item in response.data)
    return results
