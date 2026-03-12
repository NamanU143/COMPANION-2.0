import edge_tts

async def generate_audio(text: str, output_filepath: str):
    """
    Uses edge-tts to generate an audio file from the provided text.
    Uses a standard female/male voice.
    """
    # We can use a preferred voice, e.g., 'en-US-AriaNeural'
    VOICE = "en-US-AriaNeural"
    
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_filepath)
