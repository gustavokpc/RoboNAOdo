# -*- coding: utf-8 -*-
"""NAO voice bridge: browser speech recognition -> local Qwen3 -> robot TTS.

Use Chrome/Edge at http://127.0.0.1:8765. This is separate from the
existing TESTE emotion box. Nothing in this file uses the OpenAI API.
"""
import json
import re
import socket
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
from ollama import chat

# IMPORTANT: use your robot's actual IP from Choregraphe
NAO_IP = "192.168.2.121"  # <-- CHANGE THIS
NAO_PORT = 6001
MODEL = "qwen3:4b"
WEB_PORT = 8765
HERE = Path(__file__).resolve().parent

history = []
last_topic_weather = False
request_lock = threading.Lock()
emotion_mode = False


def describe_weather(code):
    if code == 0:
        return "clear sky"
    if code in (1, 2):
        return "partly cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "foggy"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (80, 81, 82):
        return "rain showers"
    if code in (95, 96, 99):
        return "thunderstorms"
    return "unknown conditions"


def get_weather(city: str, day: str = "today") -> str:
    """Look up real weather for the specified city.

    Args:
        city: The city name, optionally including the country. Ask for
              the city first if the user has not identified one.
        day: The requested date: today or tomorrow.
    """
    if not city or not city.strip():
        return "City unspecified. Please ask the user which city."
    day = day.strip().lower()
    if day not in ("today", "tomorrow"):
        return "Only today and tomorrow are supported by this tool."

    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en"},
        timeout=12,
    )
    geo.raise_for_status()
    places = geo.json().get("results", [])
    if not places:
        return "City not found. Please ask the user to specify another city."
    place = places[0]

    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "timezone": "auto",
            "forecast_days": 2,
        },
        timeout=12,
    )
    weather.raise_for_status()
    data = weather.json()
    i = 0 if day == "today" else 1
    daily = data["daily"]
    result = {
        "city": place["name"],
        "country": place.get("country"),
        "date": daily["time"][i],
        "condition": describe_weather(daily["weather_code"][i]),
        "min_C": daily["temperature_2m_min"][i],
        "max_C": daily["temperature_2m_max"][i],
        "max_rain_probability_percent": daily["precipitation_probability_max"][i],
    }
    if day == "today":
        result["current_C"] = data["current"]["temperature_2m"]
        result["feels_like_C"] = data["current"]["apparent_temperature"]
        result["current_condition"] = describe_weather(data["current"]["weather_code"])
    return json.dumps(result)


def is_weather_question(question, previous_weather):
    q = question.lower()
    weather_patterns = (
        r"\bweather\b", r"\bforecast\b", r"\btemperature\b",
        r"\brain(?:ing|y)?\b", r"\bsnow(?:ing|y)?\b",
        r"\bumbrella\b", r"\bdrizzle\b", r"\bcloudy\b",
        r"\bsunny\b", r"\bwindy\b", r"\bprecipitation\b",
    )
    if any(re.search(p, q) for p in weather_patterns):
        return True
    # Short follow-up like "and tomorrow?" after a weather response.
    return previous_weather and len(q.split()) <= 7 and any(
        term in q for term in ("tomorrow", "today", "same city", "what about", "and then")
    )


def clean_answer(raw):
    text = (raw or "").strip()
    # Defensive fallback for models that accidentally include thinking in content
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1].strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    # Keep the default English NAO TTS comfortable to speak.
    text = text.replace("°C", " degrees Celsius")
    return text


ACTION_WORDS = re.compile(
    r"\b(danc\w*|choreograph\w*|moves?|emotions?|expressions?|"
    r"recogniz\w*|detect\w*|face|faces|feelings?|moods?)\b", re.I
)


def detect_robot_action(question):
    """Classify actual physical commands, not questions *about* dancing."""
    if not ACTION_WORDS.search(question):
        return None
    response = chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": (
                "Classify the user's intention towards a humanoid NAO robot. "
                "Return ONLY a JSON object with an action field. "
                "Allowed actions: 'dance', 'emotion', 'chat'. "
                "Use 'dance' ONLY if the user is asking the physical robot to "
                "dance or show dance moves now (including 'can you dance?'). "
                "Use 'emotion' ONLY if the user is asking to START the robot's "
                "facial expression/emotion recognition MODE now. "
                "Use 'chat' if the user wants information, an explanation or a "
                "conversation ABOUT dancing, facial expressions or emotions. "
                "Examples: 'Dance for me' -> dance; 'Show me your moves' -> dance; "
                "'Let's detect my emotions' -> emotion; 'Switch to emotion recognition' -> emotion; "
                "'How do you recognize faces?' -> chat; 'Explain dancing' -> chat."
            )},
            {"role": "user", "content": question},
        ],
        format="json",
        think=False,
        options={"temperature": 0},
    )
    try:
        action = json.loads(clean_answer(response.message.content))["action"].lower()
    except (ValueError, KeyError, AttributeError, TypeError):
        return None
    return action if action in ("dance", "emotion") else None


def ask_qwen(question):
    global last_topic_weather
    weather_request = is_weather_question(question, last_topic_weather)
    system_message = (
        "You are NAO, a friendly humanoid robot and GENERAL-PURPOSE conversational assistant. "
        "You can answer questions about programming, robotics, geography, science, everyday life, "
        "mathematics, and many other subjects. You are NOT exclusively a weather assistant. "
        "Always answer in natural English using 1 to 3 brief spoken sentences, unless a longer answer "
        "is truly needed. No markdown, emojis, step-by-step private reasoning, or XML tags. "
        "For CURRENT weather only, use the get_weather tool when available. "
        "If location is missing, ask which city; do not guess the user's location. "
        "If asked for other up-to-date facts, say you lack live access rather than fabricate. "
        "Today's date is " + datetime.now().date().isoformat() + "."
    )
    messages = [{"role": "system", "content": system_message}] + history[-12:] + [
        {"role": "user", "content": question}
    ]
    args = {"model": MODEL, "messages": messages, "think": False}
    # Gating the tool prevents unrelated questions from being treated as weather requests.
    if weather_request:
        args["tools"] = [get_weather]
    response = chat(**args)
    if weather_request and response.message.tool_calls:
        messages.append(response.message)
        for call in response.message.tool_calls:
            if call.function.name == "get_weather":
                try:
                    result = get_weather(**call.function.arguments)
                except Exception as ex:
                    result = "Weather service unavailable: " + str(ex)
                print("[Open-Meteo]", result)
                messages.append({
                    "role": "tool", "tool_name": "get_weather", "content": result
                })
        response = chat(model=MODEL, messages=messages, think=False)

    answer = clean_answer(response.message.content)
    if not answer:
        answer = "Sorry, I couldn't generate an answer. Could you repeat your question?"
    history.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ])
    # Retain only recent turns, not an ever-growing transcript.
    if len(history) > 20:
        del history[:-20]
    last_topic_weather = weather_request
    return answer


def llm_state():
    """Check actual robot mode: READY, DANCING, DANCE_TIMEOUT or OFFLINE."""
    try:
        with socket.create_connection((NAO_IP, NAO_PORT), timeout=1.2) as sock:
            sock.settimeout(2.0)
            sock.sendall(b"CMD:STATUS")
            sock.shutdown(socket.SHUT_WR)
            state = sock.recv(32).decode("ascii", errors="replace").strip()
            if state in ("READY", "DANCING", "DANCE_TIMEOUT"):
                return state
    except (OSError, socket.timeout):
        pass
    return "OFFLINE"


def llm_is_ready():
    return llm_state() == "READY"


def speak_on_nao(text):
    # The Choregraphe LLM_CHAT box must be running on port 6001.
    with socket.create_connection((NAO_IP, NAO_PORT), timeout=8) as sock:
        sock.settimeout(165)
        sock.sendall(text.encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        ack = sock.recv(64).strip()
        if ack != b"OK":
            raise RuntimeError("NAO didn't confirm its speech (reply: %r)" % ack)


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/status":
            global emotion_mode
            state = llm_state()
            if state == "READY":
                emotion_mode = False  # TESTE -> LLM_CHAT automatic return.
            mode = {
                "READY": "llm", "DANCING": "dance",
                "DANCE_TIMEOUT": "dance_timeout",
            }.get(state, "emotion" if emotion_mode else "offline")
            return self._respond(200, {"ready": state == "READY", "mode": mode})
        if self.path not in ("/", "/index.html"):
            return self._respond(404, {"error": "Not found"})
        page = (HERE / "mic.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        if self.path != "/ask":
            return self._respond(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16000:
                return self._respond(400, {"error": "Invalid message length"})
            body = json.loads(self.rfile.read(length))
            question = str(body.get("question", "")).strip()
            if not question or len(question) > 1000:
                return self._respond(400, {"error": "Question must contain 1-1000 characters"})
            with request_lock:
                global emotion_mode
                print("[YOU]", question, flush=True)
                current_state = llm_state()
                if current_state == "READY":
                    if emotion_mode:
                        print("[MODE] LLM_CHAT reconnected", flush=True)
                    emotion_mode = False
                elif current_state in ("DANCING", "DANCE_TIMEOUT"):
                    return self._respond(409, {
                        "error": ("NAO is still dancing. Wait for the animation to finish."
                                  if current_state == "DANCING" else
                                  "Dance completion signal missing. Check onStopped -> onResume in Choregraphe.")
                    })
                else:
                    return self._respond(409, {
                        "error": ("NAO is detecting emotions. Waiting for TESTE to return to LLM_CHAT."
                                  if emotion_mode else
                                  "LLM_CHAT is offline. Start it in Choregraphe.")
                    })

                action = detect_robot_action(question)
                if action == "dance":
                    print("[ACTION] DANCE", flush=True)
                    try:
                        # OK means the robot ACCEPTED the dance command, not finished.
                        speak_on_nao("CMD:DANCE")
                        return self._respond(200, {
                            "answer": "Dance started. NAO will let you know when it finishes.",
                            "spoken": True, "action": "dance"
                        })
                    except Exception as ex:
                        return self._respond(200, {
                            "answer": "I couldn't complete the dance.",
                            "spoken": False, "speech_error": str(ex)
                        })

                if action == "emotion":
                    print("[ACTION] EMOTION", flush=True)
                    try:
                        speak_on_nao("CMD:EMOTION")
                        emotion_mode = True
                        return self._respond(200, {
                            "answer": "Emotion recognition started on NAO.",
                            "spoken": True, "action": "emotion"
                        })
                    except Exception as ex:
                        return self._respond(200, {
                            "answer": "I couldn't switch to emotion recognition.",
                            "spoken": False, "speech_error": str(ex)
                        })

                answer = ask_qwen(question)
                print("[NAO]", answer, flush=True)
                try:
                    speak_on_nao("SAY:" + answer)
                    return self._respond(200, {"answer": answer, "spoken": True})
                except Exception as ex:
                    return self._respond(200, {
                        "answer": answer, "spoken": False,
                        "speech_error": str(ex)
                    })
        except Exception as ex:
            print("[ERROR]", ex, flush=True)
            self._respond(500, {"error": str(ex)})


if __name__ == "__main__":
    if NAO_IP == "192.168.1.100":
        print("IMPORTANT: set NAO_IP to your NAO's actual IP in voice_nao.py")
    server = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), Handler)
    print("NAO voice page: http://127.0.0.1:%s" % WEB_PORT)
    print("Open this URL in Microsoft Edge or Google Chrome.")
    print("Use Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
