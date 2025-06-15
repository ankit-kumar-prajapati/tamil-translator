import streamlit as st
import os
import time
from google.cloud import speech, translate_v2 as translate, texttospeech, storage
import io
from pydub import AudioSegment
import json
from google.oauth2 import service_account

# --- Configuration ---
st.set_page_config(page_title="Speech-to-Speech Translator", page_icon="🎙️", layout="centered")

# --- Securely Load Google Cloud Credentials ---
# This function handles loading credentials from Streamlit Secrets (for cloud)
# or a local file (for development).
def load_gcp_credentials():
    # Try to load from Streamlit Secrets first (for deployment)
    if 'gcp_credentials' in st.secrets:
        creds_json = st.secrets["gcp_credentials"]
        creds = service_account.Credentials.from_service_account_info(creds_json)
        return creds
    # Fallback to local file for development
    elif os.path.exists("gcp-key.json"):
        return service_account.Credentials.from_service_account_file(
            "gcp-key.json",
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    else:
        st.error("GCP credentials not found. Please set them up in Streamlit Secrets or add a gcp-key.json file.")
        st.stop()

# --- Initialize Google Cloud Clients ---
try:
    credentials = load_gcp_credentials()
    speech_client = speech.SpeechClient(credentials=credentials)
    translate_client = translate.Client(credentials=credentials)
    tts_client = texttospeech.TextToSpeechClient(credentials=credentials)
    storage_client = storage.Client(credentials=credentials)
    BUCKET_NAME = "bucket-for-translator-462605"
except Exception as e:
    st.error(f"Error initializing Google Cloud clients: {e}")
    st.stop()

# --- Helper Functions ---
def upload_to_gcs(audio_content, destination_blob_name):
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(audio_content, content_type='audio/wav')
    return f"gs://{BUCKET_NAME}/{destination_blob_name}"

def process_and_translate(audio_bytes, source_lang_code):
    # This is our core, working logic
    try:
        st.write("1. Processing audio...")
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio_segment = audio_segment.set_channels(1).set_frame_rate(16000)
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        processed_audio_content = wav_io.getvalue()
        
        duration_seconds = len(audio_segment) / 1000.0
        st.info(f"Audio duration: {duration_seconds:.2f} seconds.")

        st.write("2. Transcribing audio...")
        if duration_seconds < 60:
            audio = speech.RecognitionAudio(content=processed_audio_content)
            config = speech.RecognitionConfig(encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, sample_rate_hertz=16000, language_code=source_lang_code)
            response = speech_client.recognize(config=config, audio=audio)
        else:
            st.info("Long audio detected. Uploading to Cloud Storage...")
            gcs_uri = upload_to_gcs(processed_audio_content, f"audio-uploads/temp-{int(time.time())}.wav")
            audio = speech.RecognitionAudio(uri=gcs_uri)
            config = speech.RecognitionConfig(encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, sample_rate_hertz=16000, language_code=source_lang_code, enable_automatic_punctuation=True)
            operation = speech_client.long_running_recognize(config=config, audio=audio)
            response = operation.result(timeout=900)
        
        transcript = "".join(result.alternatives[0].transcript for result in response.results)

        if not transcript:
            st.warning("Could not recognize speech. Please try again.")
            return None, None, None

        st.write("3. Translating and synthesizing speech...")
        translation_result = translate_client.translate(transcript, target_language="ta")
        translated_text = translation_result["translatedText"]
        synthesis_input = texttospeech.SynthesisInput(text=translated_text)
        voice_params = texttospeech.VoiceSelectionParams(language_code="ta-IN", ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        tts_response = tts_client.synthesize_speech(input=synthesis_input, voice=voice_params, audio_config=audio_config)
        
        return transcript, translated_text, tts_response.audio_content
    except Exception as e:
        st.error(f"An error occurred during processing: {e}")
        return None, None, None

# --- Streamlit UI ---
st.title("Speech-to-Speech Translator")
st.markdown("Translate **English** or **Hindi** into audible **Tamil** by uploading an audio file.")
st.divider()

input_lang_options = {"English": "en-US", "Hindi": "hi-IN"}
selected_lang_name = st.radio("1. Select the language of the uploaded audio:", list(input_lang_options.keys()), horizontal=True)
source_lang_code = input_lang_options[selected_lang_name]

uploaded_file = st.file_uploader("2. Upload your audio file (WAV or MP3):", type=["wav", "mp3"])

if uploaded_file is not None:
    st.audio(uploaded_file, format='audio/wav')
    
    if st.button("🚀 Translate Now", type="primary"):
        with st.spinner('Translation in progress... This may take a moment.'):
            audio_bytes = uploaded_file.getvalue()
            original_text, translated_text, translated_audio = process_and_translate(audio_bytes, source_lang_code)
        
        if translated_audio:
            st.success("Translation Complete!")
            st.text_area("Recognized Text", original_text, height=100)
            st.text_area("Translated Text (Tamil)", translated_text, height=100)
            st.subheader("Translated Audio (Tamil)")
            st.audio(translated_audio, format="audio/mp3")
            st.balloons()

