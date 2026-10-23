# NAO Voice Assistant

I built this project to make a NAO V6 robot hold spoken conversations, recognize facial expressions, and perform a few actions on request. The language model runs on a Windows PC, while NAO handles speech and movement through Choregraphe.

The project uses **Qwen3 4B** through **Ollama**, so there is no paid LLM API involved. Weather questions are handled with Open-Meteo. Everything else goes to the local model.

This is a prototype built around my NAO/Choregraphe setup, not a one-click installation. In particular, the emotion-recognition model and its inference server must already be installed on the robot.

## What it does

- Answers questions in English using a local LLM and speaks the answers through NAO's speakers.
- Listens through a browser on the PC (Edge or Chrome). The browser converts speech to text.
- Checks current weather and forecasts for today or tomorrow using Open-Meteo.
- Starts a Choregraphe animation when asked to dance, then returns to the conversation.
- Switches between conversation and emotion recognition by voice.
- Detects **neutral, happiness, sadness, surprise, and anger** in emotion mode and triggers the corresponding reactions.

For example, you can ask *“What's the weather in Paris?”*, *“Can you explain how robots work?”*, *“Can you dance for me?”*, or *“Let's detect my emotions.”*

## Setup used

| | |
| --- | --- |
| Robot | NAO V6, NAOqi 2.8 |
| Robot software | Choregraphe Suite 2.8 |
| PC | Windows, Python 3 |
| Language model | [Qwen3 4B](https://ollama.com/library/qwen3:4b) via [Ollama](https://ollama.com/) |
| Speech input | Browser Web Speech API (Edge/Chrome) |
| Speech output | NAOqi `ALTextToSpeech` |
| Weather | [Open-Meteo](https://open-meteo.com/) |
| Emotion recognition | Logitech C930e USB camera, OpenCV, CNN inference server on NAO |

The Choregraphe code runs in **Python 2.7** on the robot. The PC scripts use **Python 3**. They are separate environments.

## Files

```text
LLM_NAO/
├── README.md
├── voice_nao.py           # PC server, Qwen3, Open-Meteo, commands sent to NAO
├── mic.html               # Browser interface for the microphone
├── teste.py               # Earlier standalone test script (not needed to run the app)
├── requirements.txt
└── LNN_working/
    ├── LNN_working.pml    # Open this in Choregraphe
    ├── manifest.xml
    ├── behavior_1/
    │   ├── behavior.xar
    │   ├── sounds/
    │   └── epicsax.ogg
    └── translations/
```

Most robot-side Python code is stored **inside the Choregraphe project**, rather than in separate `.py` files.

## Installation

### 1. Install Ollama

Download and install [Ollama for Windows](https://ollama.com/download/windows). Open a new PowerShell window and run:

```powershell
ollama pull qwen3:4b
ollama list
```

You can test the model with `ollama run qwen3:4b`. Type `/bye` to exit the interactive chat. You don't need to leave that chat open when running this project; the Ollama app runs the model service in the background.

If Windows doesn't recognize `ollama`, reopen PowerShell. If it still fails, try:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" --version
```

### 2. Set up Python

I used [uv](https://docs.astral.sh/uv/) to manage the Python environment. From the project directory:

```powershell
uv python install 3.11
uv venv --python 3.11 .venv
.\.venv\Scripts\Activate.ps1
uv pip install ollama requests
```

If you already have a working `.venv`, just activate it instead of creating another one. The browser-based voice version does **not** need Faster-Whisper.

On my Windows setup, the native `ctranslate2` module used by Faster-Whisper was blocked by an application-control policy. Using the browser for speech recognition avoids that dependency.

### 3. Configure the NAO connection

Connect the PC and robot to the same reachable local network. In `voice_nao.py`, set the robot's actual IP address:

```python
NAO_IP = "192.168.1.100"  # Replace with your NAO's IP
NAO_PORT = 6001
MODEL = "qwen3:4b"
WEB_PORT = 8765
```

Use the same IP shown in Choregraphe's robot connection settings. **Port 9559 is for NAOqi/Choregraphe; port 6001 is for the conversation bridge.** They are not interchangeable.

### 4. Open the Choregraphe project

Open `LNN_working/LNN_working.pml` in Choregraphe, connect to the physical NAO on **port 9559**, and check that these boxes are present:

- `SELECT_MODE` — asks whether to start emotion recognition.
- `LLM_CHAT` — receives messages and action commands from the PC.
- `TESTE` — runs the emotion detector and its reactions.
- Animation boxes for dancing, high-five, Tai Chi, saxophone, etc.

The main links should be:

```text
Project start -> SELECT_MODE
SELECT_MODE.onLLM -> LLM_CHAT.onStart
SELECT_MODE.onTESTE -> TESTE.onStart

LLM_CHAT.onDance -> Dance.onStart
Dance.onStopped -> LLM_CHAT.onResume
LLM_CHAT.onEmotion -> TESTE.onStart
TESTE.onLLM -> LLM_CHAT.onStart
```

`Dance` means the animation box you chose for LLM requests (called `Guitar` in one version of my project). Its completion output must be connected to `LLM_CHAT.onResume`; otherwise the chat can remain stuck in dance mode. The animations triggered by `TESTE` keep their existing connections.

**Note about emotion recognition:** the `TESTE` box expects `/home/nao/servidor_emocao.py`, CNN weights/dependencies and a Logitech C930e connected to the robot. Those are separate from the PC voice server and need to be deployed on NAO. Cloning this repository alone doesn't install them.

## Running it

Start things in this order:

1. Make sure the **Ollama** app is running on the PC.
2. Open **Choregraphe**, connect to NAO and press **Play**.
3. NAO asks: *“Would you like me to recognize your emotions?”* Say **“No”** to start the conversation, or **“Yes”** for emotion recognition.
4. In PowerShell, from the repository folder, run:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python voice_nao.py
   ```

5. Open **http://127.0.0.1:8765** in Edge or Chrome, allow microphone access, and click **Speak to NAO**.
6. Ask a question in English. The browser transcribes it, Qwen3 generates a reply, and NAO speaks it.

There is also a text box on the page, which is useful when testing the LLM without the microphone.

**Don't run `teste.py` at the same time.** The normal voice interface uses `voice_nao.py`; emotion detection is started by the `TESTE` box in Choregraphe.

### Switching modes

In conversation mode, saying *“Let's detect my emotions”* switches to `TESTE`. The PC stops sending chat questions while emotion mode is active.

In emotion mode, NAO reacts to the facial expression detected by the CNN. After about **10 seconds of neutral expression**, it asks whether you want to have a conversation. Say **“Yes”** to return to `LLM_CHAT`, or **“No”** to keep detecting emotions. NAO uses its own microphones for these short yes/no answers; regular LLM questions still use the PC/browser microphone.

For dance requests, the LLM sends a command to `LLM_CHAT`, which starts the chosen Choregraphe animation. When the animation finishes, its `onStopped` signal lets the conversation resume.

## Ports

| Port | Runs on | Used for |
| --- | --- | --- |
| `9559` | NAO | Choregraphe / NAOqi connection |
| `6001` (TCP) | NAO | LLM text and action commands |
| `6000` (UDP) | NAO, local | CNN inference server used by `TESTE` |
| `8765` | PC | Voice interface at `127.0.0.1` |
| `11434` | PC | Ollama API |

## If something doesn't work

- **`ollama` not recognized:** reopen the terminal or use the full executable path from the installation section.
- **Browser says “Waiting for LLM_CHAT”:** make sure the robot is in LLM mode, the IP in `voice_nao.py` is correct, and Choregraphe logs `LLM_CHAT ready on TCP port 6001`.
- **NAO generates an answer but doesn't speak:** check the Choregraphe logs. In NAOqi/Python 2.7, I had to pass a UTF-8 byte string to `ALTextToSpeech.say()` rather than a Python `unicode` value.
- **Dance doesn't return to the chat:** check the animation's `onStopped -> LLM_CHAT.onResume` connection.
- **The mic doesn't become available after emotions:** check that `TESTE.onLLM` really starts `LLM_CHAT` again and that the PC can reach port 6001.
- **No camera/CNN output:** check the USB camera, `/home/nao/servidor_emocao.py`, model files and the robot log.

To check the NAO connection from PowerShell (replace the IP):

```powershell
Test-NetConnection -ComputerName 192.168.1.100 -Port 6001
Invoke-RestMethod http://127.0.0.1:8765/status
```

## A few notes

- The **LLM runs locally**, with no per-message API fee. The browser's speech recognition may use an online service, and Open-Meteo requires internet access. This is not a fully offline voice assistant.
- The robot's TCP port 6001 has no authentication in this prototype. Use it on a trusted local network, not on the public internet.
- A small model like Qwen3 4B can make mistakes. Weather is the only live-data tool currently integrated.
- Robot movements should be tested on a stable surface with enough room around NAO.

The remaining work is to package the CNN server and model alongside the project, so the emotion mode can be reproduced on a second robot without manually copying files.
