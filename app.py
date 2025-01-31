import requests
import re
import openai
import os
import threading
import time
import tempfile
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions, Microphone
import pygame
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

def google_search(query):
    query+=query+""
    api_key='AIzaSyD7Bv7RjhiYkLNUWEYB0al03W6ef_kAw70'
    cx = 'd6dea6904f8c64a2b'
    url = f'https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={query}'
    
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        data = response.json()
        sresult=''
        if 'items' in data:
            sresult+='\n'.join(item['snippet'] for item in data['items'])
            return sresult
        else:
            return 'No relevant results found.'

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")  # Python 3.6+
        return f"Error: {http_err}"
    except Exception as err:
        print(f"An error occurred: {err}")
        return f"Error: {err}"

# Initialize clients
dg_client = DeepgramClient(api_key=DEEPGRAM_API_KEY)
openai.api_key = OPENAI_API_KEY
client = openai.OpenAI()

DEEPGRAM_TTS_URL = 'https://api.deepgram.com/v1/speak?model=aura-helios-en'
headers = {
    "Authorization": f"Token {DEEPGRAM_API_KEY}",
    "Content-Type": "application/json"
}

conversation_memory = []

# Global flag to control microphone state
mute_microphone = threading.Event()

prompt = """ You re a voice support agent. Keep all answers less than two lines. Three lines at maximum if needed. Also remebember previous chat if asked questions based on it
"""

def segment_text_by_sentence(text):
    sentence_boundaries = re.finditer(r'(?<=[.!?])\s+', text)
    boundaries_indices = [boundary.start() for boundary in sentence_boundaries]

    segments = []
    start = 0
    for boundary_index in boundaries_indices:
        segments.append(text[start:boundary_index + 1].strip())
        start = boundary_index + 1
    segments.append(text[start:].strip())

    return segments

def synthesize_audio(text):
    payload = {"text": text}
    with requests.post(DEEPGRAM_TTS_URL, stream=True, headers=headers, json=payload) as r:
        return r.content


def play_audio(file_path):
    pygame.mixer.init()
    pygame.mixer.music.load(file_path)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

    # Stop the mixer and release resources
    pygame.mixer.music.stop()
    pygame.mixer.quit()

    # Signal that playback is finished
    mute_microphone.clear()


def main():
    try:
        deepgram = DeepgramClient(DEEPGRAM_API_KEY)
        dg_connection = deepgram.listen.live.v("1")

        is_finals = []

        def on_open(self, open, **kwargs):
            print("Connection Open")

        def on_message(self, result, **kwargs):
            nonlocal is_finals
            if mute_microphone.is_set():
                return  # Ignore messages while microphone is muted
            
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            if result.is_final:
                is_finals.append(sentence)
                if result.speech_final:
                    utterance = " ".join(is_finals)
                    print(f"Speech Final: {utterance}")
                    is_finals = []
                    conversation_memory.append({"role": "user", "content": sentence.strip()})

                    google_results = google_search(sentence.strip())
                    print(google_results)
                    messages = [{"role": "system", "content": prompt + "\n\nGoogle Search Results use only is needed, otherwise answer only related to prompt and previous messages from user:\n" + google_results}]
                    messages.extend(conversation_memory)
                    chat_completion = client.chat.completions.create(
                        model="gpt-4",
                        messages=messages
                    )
                    print(chat_completion)
                    processed_text = chat_completion.choices[0].message.content.strip()
                    text_segments = segment_text_by_sentence(processed_text)
                    with open(output_audio_file, "wb") as output_file:
                        for segment_text in text_segments:
                            audio_data = synthesize_audio(segment_text)
                            output_file.write(audio_data)
                    
                    # Mute the microphone and play the audio
                    mute_microphone.set()
                    microphone.mute()
                    play_audio(output_audio_file)
                    time.sleep(0.5)
                    microphone.unmute()
                    # Delete the audio file after playing
                    if os.path.exists(output_audio_file):
                        os.remove(output_audio_file)
            else:
                print(f"Interim Results: {sentence}")

        def on_metadata(self, metadata, **kwargs):
            print(f"Metadata: {metadata}")

        def on_speech_started(self, speech_started, **kwargs):
            print("Speech Started")

        def on_utterance_end(self, utterance_end, **kwargs):
            print("Utterance End")
            nonlocal is_finals
            if len(is_finals) > 0:
                utterance = " ".join(is_finals)
                print(f"Utterance End: {utterance}")
                is_finals = []

        def on_close(self, close, **kwargs):
            print("Connection Closed")

        def on_error(self, error, **kwargs):
            print(f"Handled Error: {error}")

        def on_unhandled(self, unhandled, **kwargs):
            print(f"Unhandled Websocket Message: {unhandled}")

        dg_connection.on(LiveTranscriptionEvents.Open, on_open)
        dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
        dg_connection.on(LiveTranscriptionEvents.Metadata, on_metadata)
        dg_connection.on(LiveTranscriptionEvents.SpeechStarted, on_speech_started)
        dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
        dg_connection.on(LiveTranscriptionEvents.Close, on_close)
        dg_connection.on(LiveTranscriptionEvents.Error, on_error)
        dg_connection.on(LiveTranscriptionEvents.Unhandled, on_unhandled)

        options = LiveOptions(
            model="nova-2",
            language="en-US",
            smart_format=True,
            encoding="linear16",
            channels=1,
            sample_rate=16000,
            interim_results=True,
            utterance_end_ms="1000",
            vad_events=True,
            endpointing=500,
        )

        addons = {
            "no_delay": "true"
        }

        print("\n\nPress Enter to stop recording...\n\n")
        if not dg_connection.start(options, addons=addons):
            print("Failed to connect to Deepgram")
            return

        microphone = Microphone(dg_connection.send)
        microphone.start()

        input("")
        microphone.finish()
        dg_connection.finish()

        print("Finished")

    except Exception as e:
        print(f"Could not open socket: {e}")

if __name__ == "__main__":
    output_audio_file = 'output_audio.mp3'
    main()
