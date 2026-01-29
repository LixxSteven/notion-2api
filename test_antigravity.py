from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8045/v1",
    api_key="sk-54f6ba68821941189473960c2f340a9e"  # 截图里的 key
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",  # 或 gemini-3-flash
    messages=[{"role": "user", "content": "说一个字"}]
)

print(response.choices[0].message.content)