import base64
from openai import OpenAI

class AIService:
    def __init__(self,key,text_model,image_model):
        self.client=OpenAI(api_key=key); self.text_model=text_model; self.image_model=image_model
    def generate_text(self,topic):
        prompt=f'''برای کانال تلگرامی فارسی @nova_ip درباره موضوع زیر یک پست خلاقانه بنویس:
{topic}
قوانین قطعی:
- لحن دوستانه، صمیمی و انسانی.
- شروع با قلاب ذهنی قوی و کنجکاوکننده.
- متن نسبتاً طولانی، ارزشمند و خوانا، با پاراگراف‌های مناسب و ایموجی متعادل.
- حتماً @nova_ip داخل متن باشد.
- حتماً یک سؤال مشخص از اعضای کانال بپرس.
- در پایان 5 تا 10 هشتگ مرتبط با موضوع قرار بده.
- متن اختصاصی و خلاقانه باشد و کلیشه‌ای نباشد.
فقط متن نهایی را برگردان.'''
        r=self.client.responses.create(model=self.text_model,input=prompt)
        return r.output_text.strip()
    def generate_image(self,topic,text):
        prompt=f'''Create a creative, striking square social-media image for a Persian Telegram post.
Topic: {topic}
Context: {text[:2500]}
Use an original modern editorial composition, strong visual hook, cinematic lighting and rich detail.
Communicate the topic visually. No readable text, logos, usernames, watermarks or UI.'''
        r=self.client.images.generate(model=self.image_model,prompt=prompt,size="1024x1024")
        return base64.b64decode(r.data[0].b64_json)
