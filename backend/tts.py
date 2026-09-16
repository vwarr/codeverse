from google.cloud import texttospeech
import sounddevice as sd
import numpy as np
import threading

client = texttospeech.TextToSpeechClient(client_options={"api_endpoint": "us-central1-texttospeech.googleapis.com"})

def synthesize_speech(text):
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code="en-US", name="en-US-Chirp-HD-O")
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16, 
        sample_rate_hertz=24000
    )
    response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
    return np.frombuffer(response.audio_content, dtype=np.int16)

def split_text(text, max_chars=200):
    words = text.split()
    chunks, current_chunk = [], ""
    for word in words:
        if len(current_chunk) + len(word) + 1 < max_chars:
            current_chunk += word + " "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = word + " "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def worker(text_chunk, index, results, lock):
    audio_data = synthesize_speech(text_chunk)
    with lock:
        results[index] = audio_data

def apply_fade_in(audio, sample_rate, fade_duration_ms=50):
    fade_samples = int(sample_rate * fade_duration_ms / 1000)
    # If the audio is shorter than the fade duration, adjust accordingly.
    if len(audio) < fade_samples:
        fade_samples = len(audio)
    fade_curve = np.linspace(0.0, 1.0, fade_samples)
    # Convert to float for the multiplication, then back to int16.
    audio_float = audio.astype(np.float32)
    audio_float[:fade_samples] *= fade_curve
    return audio_float.astype(np.int16)

def text_to_speech(text):
    text_chunks = split_text(text)
    results = [None] * len(text_chunks)
    lock = threading.Lock()
    threads = []

    for i, chunk in enumerate(text_chunks):
        thread = threading.Thread(target=worker, args=(chunk, i, results, lock))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    full_audio = np.concatenate([audio for audio in results if audio is not None])
    # Apply a fade-in to the beginning of the concatenated audio
    full_audio = apply_fade_in(full_audio, sample_rate=24000, fade_duration_ms=50)

    with sd.OutputStream(samplerate=24000, channels=1, dtype='int16') as stream:
        stream.write(full_audio)
