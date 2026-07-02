import os
import shutil
import subprocess
import threading
from pathlib import Path

from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk


# =========================
# SETTINGS
# =========================

LANGUAGE = "hy-AM"

DATA_DIR = Path("data")
CONVERTED_DIR = Path("converted_wav")
TRANSCRIPTIONS_DIR = Path("transcriptions")

# Recommended: use default microphone.
# If you really need your old exact microphone device, paste it here.
MIC_DEVICE_NAME = None
# MIC_DEVICE_NAME = "{0.0.1.00000000}.{24C6D384-BF5B-49FC-9B16-35AF66689C33}"


# =========================
# AZURE CONFIG
# =========================

def create_speech_config(api_key, region):
    speech_config = speechsdk.SpeechConfig(
        subscription=api_key,
        region=region
    )

    speech_config.speech_recognition_language = LANGUAGE

    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
        "40000"
    )

    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
        "20000"
    )

    return speech_config


# =========================
# MP3 TO WAV CONVERSION
# =========================

def convert_mp3_to_wav(mp3_path):
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is not installed or not added to PATH. "
            "Install ffmpeg first, then run this script again."
        )

    CONVERTED_DIR.mkdir(exist_ok=True)

    wav_path = CONVERTED_DIR / f"{mp3_path.stem}.wav"

    command = [
        "ffmpeg",
        "-y",
        "-i", str(mp3_path),
        "-ar", "16000",
        "-ac", "1",
        "-sample_fmt", "s16",
        str(wav_path)
    ]

    print(f"Converting MP3 to WAV: {mp3_path.name}")

    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed while converting {mp3_path.name}\n\n"
            f"{result.stderr}"
        )

    return wav_path


def prepare_audio_file(audio_path):
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if audio_path.suffix.lower() == ".wav":
        return audio_path

    if audio_path.suffix.lower() == ".mp3":
        return convert_mp3_to_wav(audio_path)

    raise ValueError(
        f"Unsupported audio format: {audio_path.suffix}. "
        "Use MP3 or WAV."
    )


# =========================
# TRANSCRIBE RECORDING
# =========================

def transcribe_recording(api_key, region, audio_path):
    speech_config = create_speech_config(api_key, region)

    wav_path = prepare_audio_file(audio_path)

    audio_config = speechsdk.audio.AudioConfig(
        filename=str(wav_path)
    )

    speech_recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    done = threading.Event()
    recognized_parts = []

    def recognized_handler(evt):
        result = evt.result

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = result.text.strip()

            if text:
                print(f"Recognized: {text}")
                recognized_parts.append(text)

        elif result.reason == speechsdk.ResultReason.NoMatch:
            print(f"No speech recognized: {result.no_match_details}")

    def canceled_handler(evt):
        print("Recognition canceled.")

        reason = getattr(evt, "reason", None)
        error_details = getattr(evt, "error_details", None)

        if reason:
            print(f"Reason: {reason}")

        if error_details:
            print(f"Error details: {error_details}")

        done.set()

    def session_stopped_handler(evt):
        print("Recording transcription finished.")
        done.set()

    speech_recognizer.recognized.connect(recognized_handler)
    speech_recognizer.canceled.connect(canceled_handler)
    speech_recognizer.session_stopped.connect(session_stopped_handler)

    print(f"\nTranscribing recording: {audio_path.name}")

    speech_recognizer.start_continuous_recognition_async().get()
    done.wait()
    speech_recognizer.stop_continuous_recognition_async().get()

    final_text = " ".join(recognized_parts).strip()

    TRANSCRIPTIONS_DIR.mkdir(exist_ok=True)

    output_file = TRANSCRIPTIONS_DIR / f"{audio_path.stem}.txt"

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(final_text)

    print("\nFULL TRANSCRIPTION:")
    print(final_text)
    print(f"\nSaved to: {output_file}")

    return final_text


# =========================
# TRANSCRIBE MICROPHONE
# =========================

def transcribe_microphone(api_key, region):
    speech_config = create_speech_config(api_key, region)

    if MIC_DEVICE_NAME:
        audio_config = speechsdk.audio.AudioConfig(
            device_name=MIC_DEVICE_NAME
        )
    else:
        audio_config = speechsdk.audio.AudioConfig(
            use_default_microphone=True
        )

    speech_recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    done = threading.Event()
    recognized_parts = []

    stop_phrases = [
        "stop session",
        "stop",
        "ստոպ",
        "կանգնիր",
        "վերջ"
    ]

    def recognized_handler(evt):
        result = evt.result

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = result.text.strip()

            if text:
                print(f"Recognized: {text}")
                recognized_parts.append(text)

                lower_text = text.lower()

                for phrase in stop_phrases:
                    if phrase in lower_text:
                        print("Session ended by user.")
                        done.set()
                        break

        elif result.reason == speechsdk.ResultReason.NoMatch:
            print(f"No speech recognized: {result.no_match_details}")

    def canceled_handler(evt):
        print("Recognition canceled.")

        reason = getattr(evt, "reason", None)
        error_details = getattr(evt, "error_details", None)

        if reason:
            print(f"Reason: {reason}")

        if error_details:
            print(f"Error details: {error_details}")

        done.set()

    def session_stopped_handler(evt):
        print("Microphone session stopped.")
        done.set()

    speech_recognizer.recognized.connect(recognized_handler)
    speech_recognizer.canceled.connect(canceled_handler)
    speech_recognizer.session_stopped.connect(session_stopped_handler)

    print("\nMicrophone mode started.")
    print("Speak Armenian into your microphone.")
    print("To stop: press CTRL + C, or say 'stop session' / 'վերջ'.")

    speech_recognizer.start_continuous_recognition_async().get()

    try:
        done.wait()
    except KeyboardInterrupt:
        print("\nStopped manually.")

    speech_recognizer.stop_continuous_recognition_async().get()

    final_text = " ".join(recognized_parts).strip()

    print("\nFULL MICROPHONE TRANSCRIPTION:")
    print(final_text)

    return final_text


# =========================
# DATA FOLDER FUNCTIONS
# =========================

def get_audio_files_from_data_folder():
    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"Folder not found: {DATA_DIR}. "
            "Create a folder named 'data' next to this Python file."
        )

    audio_files = []

    for file in DATA_DIR.iterdir():
        if file.is_file() and file.suffix.lower() in [".mp3", ".wav"]:
            audio_files.append(file)

    audio_files.sort(key=lambda path: path.name.lower())

    return audio_files


def transcribe_all_recordings(api_key, region):
    audio_files = get_audio_files_from_data_folder()

    if not audio_files:
        print("No MP3 or WAV files found inside the data folder.")
        return

    print("\nFound audio files:")

    for index, file in enumerate(audio_files, start=1):
        print(f"{index}. {file.name}")

    print("\nStarting transcription of all files...")

    for file in audio_files:
        try:
            transcribe_recording(api_key, region, file)
        except Exception as error:
            print(f"\nERROR while processing {file.name}:")
            print(error)


def choose_one_recording(api_key, region):
    audio_files = get_audio_files_from_data_folder()

    if not audio_files:
        print("No MP3 or WAV files found inside the data folder.")
        return

    print("\nAvailable recordings:")

    for index, file in enumerate(audio_files, start=1):
        print(f"{index}. {file.name}")

    choice = input("\nEnter file number: ").strip()

    if not choice.isdigit():
        print("Invalid choice.")
        return

    choice = int(choice)

    if choice < 1 or choice > len(audio_files):
        print("Invalid file number.")
        return

    selected_file = audio_files[choice - 1]

    transcribe_recording(api_key, region, selected_file)


# =========================
# MAIN MENU
# =========================

def main():
    load_dotenv()

    api_key = os.getenv("api_key")
    region = os.getenv("region")

    if not api_key:
        raise ValueError("Missing api_key in .env file.")

    if not region:
        raise ValueError("Missing region in .env file.")

    while True:
        print("\n==============================")
        print("Azure Armenian Speech to Text")
        print("==============================")
        print("1. Live microphone transcription")
        print("2. Transcribe one recording from data folder")
        print("3. Transcribe all recordings from data folder")
        print("4. Exit")

        choice = input("\nChoose mode: ").strip()

        if choice == "1":
            transcribe_microphone(api_key, region)

        elif choice == "2":
            choose_one_recording(api_key, region)

        elif choice == "3":
            transcribe_all_recordings(api_key, region)

        elif choice == "4":
            print("Exiting.")
            break

        else:
            print("Invalid choice. Choose 1, 2, 3, or 4.")


if __name__ == "__main__":
    main()
