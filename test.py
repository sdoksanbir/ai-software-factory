from factory.models import ModelClient

client = ModelClient("config.yaml")

result = client.complete(
    model_role="fast_local",
    system_prompt="Sen deneyimli bir Python geliştiricisisin.",
    user_prompt="Sadece 'AI Factory hazır' yaz."
)

print(result.content)