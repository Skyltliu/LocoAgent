import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.environ["LLM_OPENAI_API_KEY"], base_url=os.environ["LLM_OPENAI_API_BASE"],)

model = os.environ["LLM_OPENAI_MODEL"]

def ask_model(message:str) -> str:
    response = client.responses.create(model=model, input=message,)
    return response.output_text