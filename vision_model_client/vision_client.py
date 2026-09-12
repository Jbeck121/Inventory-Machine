import asyncio
import time
from ollama import AsyncClient

async def call_vision_model(image_path, prompt):

    client = AsyncClient()

    message = {
        'role':'user',
        'content': prompt,
        'images': [image_path],
               }
    #creates dictionary with each key/value pair as data to be submitted
    #role = who model is speaking to, content = message text, images = image paths

    response = await client.chat(model='minicpm-v4.6', messages=[message])
    #uses the chat function to call on the model we are using and messages via the message

    return response.message.content

start = time.perf_counter()
end = time.perf_counter()
total_time = end-start
#timer to check how long it takes, the first time, it took longer

print(asyncio.run(call_vision_model('test_image/golf_club.jpg', "Tell me what this is")))
print(f'Prompt to ollama took {total_time:.2f} seconds')