
import socket
import wave
import sounddevice as sd
import requests
from ollama import chat

# from faster_whisper import WhisperModel

# whisper = WhisperModel(
#     "base",
#     device="cpu",
#     compute_type="int8"
# )

def transcrever():
    segmentos, _ = whisper.transcribe(
        "pergunta.wav",
        beam_size=3
    )
    return " ".join(s.text for s in segmentos)

NAO_IP = "192.168.2.121"  # Substitua pelo IP real do NAO
PORTA = 6001
FS = 16000
DURACAO = 6

ultima_resposta_id = None

def gravar():
    print("Estou ouvindo...")
    audio = sd.rec(
        int(DURACAO * FS),
        samplerate=FS,
        channels=1,
        dtype="int16"
    )
    sd.wait()

    with wave.open("pergunta.wav", "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(FS)
        f.writeframes(audio.tobytes())

def transcrever():
    with open("pergunta.wav", "rb") as f:
        resultado = client.audio.transcriptions.create(
            model="gpt-transcribe",
            file=f
        )
    return resultado.text

from ollama import chat

historico = []


historico = []


def get_weather(city: str, day: str = "today") -> str:
    """Get the real weather for a city.

    Args:
        city: Name of the city.
        day: "today" or "tomorrow".
    """
    if not city.strip():
        return "Please ask the user which city."

    day = day.lower().strip()
    if day not in ("today", "tomorrow"):
        return "Only today and tomorrow are supported."

    # Encontrar a cidade
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=10
    )
    geo.raise_for_status()

    locais = geo.json().get("results", [])

    if not locais:
        return "City not found."

    local = locais[0]

    # Consultar dados meteorologicos
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": local["latitude"],
            "longitude": local["longitude"],
            "current": "temperature_2m,weather_code",
            "daily": (
                "temperature_2m_max,"
                "temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "timezone": "auto",
            "forecast_days": 2
        },
        timeout=10
    )
    resp.raise_for_status()

    dados = resp.json()
    i = 0 if day == "today" else 1
    diario = dados["daily"]

    resultado = (
        "City: %s. Date: %s. "
        "Minimum temperature: %s Celsius. "
        "Maximum temperature: %s Celsius. "
        "Maximum rain probability: %s percent."
    ) % (
        local["name"],
        diario["time"][i],
        diario["temperature_2m_min"][i],
        diario["temperature_2m_max"][i],
        diario["precipitation_probability_max"][i]
    )

    if day == "today":
        resultado += (
            " Current temperature: %s Celsius."
            % dados["current"]["temperature_2m"]
        )

    return resultado


def perguntar_llm(pergunta):
    historico.append({
        "role": "user",
        "content": pergunta
    })

    mensagens = [
        {
            "role": "system",
            "content": (
                "You are NAO, a friendly humanoid robot. "
                "Speak natural English, using short answers. "
                "You have access to a real weather tool. "
                "ALWAYS call get_weather when someone asks "
                "about current weather, temperature, rain "
                "or tomorrow's forecast. "
                "Never invent live weather information. "
                "If the city is unknown, ask for the city. "
                "Speak naturally, without markdown."
                "Answer other questions not related to weather, but keep answers short."
            )
        }
    ] + historico[-12:]

    resposta = chat(
        model="qwen3:4b",
        messages=mensagens,
        tools=[get_weather],
        think=False
    )

    if resposta.message.tool_calls:
        mensagens.append(resposta.message)

        for chamada in resposta.message.tool_calls:
            if chamada.function.name == "get_weather":
                try:
                    resultado = get_weather(
                        **chamada.function.arguments
                    )
                except Exception as e:
                    resultado = (
                        "Weather service unavailable: " + str(e)
                    )

                print("Open-Meteo:", resultado)

                mensagens.append({
                    "role": "tool",
                    "tool_name": "get_weather",
                    "content": resultado
                })

        resposta = chat(
            model="qwen3:4b",
            messages=mensagens,
            think=False
        )

    texto = (resposta.message.content or "").strip()

    # Remove o raciocinio interno caso apareca
    if "</think>" in texto:
        texto = texto.rsplit("</think>", 1)[-1].strip()

    historico.append({
        "role": "assistant",
        "content": texto
    })

    return texto


def falar_no_nao(texto):
    with socket.create_connection(
        (NAO_IP, PORTA), timeout=10
    ) as sock:
        sock.settimeout(120)
        sock.sendall(texto.encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        confirmacao = sock.recv(16)

        if confirmacao != b"OK":
            raise RuntimeError("NAO nao confirmou a fala")

print("Assistente NAO iniciado!")

while True:
    comando = input(
        "\nEnter para perguntar, ou 'sair': "
    ).strip().lower()

    if comando == "sair":
        break

    try:
        pergunta = input("Você: ").strip()
        print("Voce:", pergunta)

        if not pergunta.strip():
            continue

        resposta = perguntar_llm(pergunta)
        print("NAO:", resposta)

        falar_no_nao(resposta)

    except Exception as e:
        print("Erro:", e)



def descricao_tempo(codigo):
    if codigo == 0:
        return "clear sky"
    if codigo in (1, 2):
        return "partly cloudy"
    if codigo == 3:
        return "overcast"
    if codigo in (45, 48):
        return "foggy"
    if codigo in (51, 53, 55, 56, 57):
        return "drizzle"
    if codigo in (61, 63, 65, 66, 67):
        return "rainy"
    if codigo in (71, 73, 75, 77, 85, 86):
        return "snowy"
    if codigo in (80, 81, 82):
        return "rain showers"
    if codigo in (95, 96, 99):
        return "thunderstorms"
    return "unknown conditions"


def get_weather(city: str, day: str = "today") -> str:
    """Get live weather or forecast for a city.

    Args:
        city: City name, optionally with country.
        day: Either today or tomorrow.
    """
    day = day.lower().strip()

    if day not in ("today", "tomorrow"):
        return "Only today and tomorrow are supported."

    # Encontrar coordenadas da cidade
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": city,
            "count": 1,
            "language": "en"
        },
        timeout=10
    )
    geo.raise_for_status()

    locais = geo.json().get("results", [])

    if not locais:
        return "City not found. Ask the user to clarify."

    local = locais[0]

    # Consultar previsao
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": local["latitude"],
            "longitude": local["longitude"],
            "current": (
                "temperature_2m,apparent_temperature,"
                "weather_code"
            ),
            "daily": (
                "temperature_2m_max,"
                "temperature_2m_min,"
                "precipitation_probability_max,"
                "weather_code"
            ),
            "timezone": "auto",
            "forecast_days": 2
        },
        timeout=10
    )
    resp.raise_for_status()
    dados = resp.json()

    indice = 0 if day == "today" else 1
    diario = dados["daily"]

    resultado = {
        "city": local["name"],
        "country": local.get("country", ""),
        "date": diario["time"][indice],
        "condition": descricao_tempo(
            diario["weather_code"][indice]
        ),
        "min_temperature_c": diario[
            "temperature_2m_min"
        ][indice],
        "max_temperature_c": diario[
            "temperature_2m_max"
        ][indice],
        "rain_probability_percent": diario[
            "precipitation_probability_max"
        ][indice]
    }

    if day == "today":
        atual = dados["current"]
        resultado["current_temperature_c"] = (
            atual["temperature_2m"]
        )
        resultado["feels_like_c"] = (
            atual["apparent_temperature"]
        )
        resultado["current_condition"] = descricao_tempo(
            atual["weather_code"]
        )

    return str(resultado)
