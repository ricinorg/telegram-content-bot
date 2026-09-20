from openai import OpenAI


class AIService:
    def __init__(self, api_key: str, text_model: str, image_model: str):
        self.client = OpenAI(api_key=api_key)
        self.text_model = text_model
        self.image_model = image_model

    def generate_text(self, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.text_model,
            input=(
                "You are a professional Telegram content creator. "
                "Write a concise, engaging Telegram post in Persian. "
                "Return only the final post text.\n\n"
                f"User request: {prompt}"
            ),
        )
        return response.output_text.strip()

    def generate_image(self, prompt: str) -> bytes:
        result = self.client.images.generate(
            model=self.image_model,
            prompt=prompt,
            size="1024x1024",
        )
        import base64
        return base64.b64decode(result.data[0].b64_json)
