# NAO V5 — Multimodal AI Integration

Turn a [SoftBank Robotics NAO V5](https://www.aldebaran.com/en/nao) into a
voice-driven, vision-aware conversational assistant powered by OpenAI.

The robot records what you say and takes a photo, sends both to a lightweight
bridge server, and speaks back the answer. Transcription is handled by Whisper,
reasoning and image understanding by GPT-4o, and domain knowledge is injected
through a small built-in RAG (Retrieval-Augmented Generation) layer.

This repository contains two cooperating parts:

| Part | Path | Runtime | Role |
|------|------|---------|------|
| **Robot script** | [`nao_chatgpt_official.py`](nao_chatgpt_official.py) | Python 2.7 + NAOqi 2.1 | Runs against the robot: records audio, takes a photo, plays the answer, drives gestures and LEDs |
| **Bridge server** | [`nao-api/`](nao-api/) | Python 3.8+ (stdlib only) | Transcribes, runs GPT-4o chat + vision with RAG, returns plain text |

---

## How it works

```
   ┌─────────────┐    audio + photo (multipart POST)    ┌──────────────────┐
   │   NAO V5    │ ───────────────────────────────────▶ │   Bridge server  │
   │  (robot)    │                                       │    (nao-api)     │
   │             │                                       │                  │
   │ • record    │                                       │ 1. Whisper  ─ STT│
   │ • photo     │                                       │ 2. RAG lookup    │
   │ • speak     │ ◀─────────────────────────────────── │ 3. GPT-4o vision │
   │ • gestures  │        plain-text answer              │    + chat        │
   └─────────────┘                                       └──────────────────┘
```

1. The user touches the robot's head to start a session.
2. NAO plays a beep, records ~5 s of audio, and captures a photo.
3. Both files are pulled to the controlling PC over SFTP and POSTed to the server.
4. The server transcribes the audio, retrieves relevant knowledge chunks, and
   asks GPT-4o to answer using the transcript, the image, and the session history.
5. The server returns plain text; the robot speaks it with contextual body language.
6. The loop continues until the user says a stop word (e.g. *no* / *stop*).

The server can also return three control values: `"STOP"` (the user asked to
end), `"skip"` (a duplicate request), and `""` (an error) — the robot reacts to
each accordingly.

---

## Repository layout

```
.
├── nao_chatgpt_official.py   # Robot-side script (runs with NAOqi)
├── nao-api/                  # AI bridge server (see nao-api/README.md)
│   ├── app/                  # HTTP server, routes, services, utils
│   ├── data/knowledge/       # .txt/.md files indexed for RAG
│   ├── docker/               # Dockerfile, docker-compose, nginx
│   ├── scripts/setup.sh      # One-shot local setup
│   ├── tests/test_api.py     # Test suite (no external deps)
│   └── .env.example          # Environment-variable template
└── README.md                 # You are here
```

---

## Part 1 — Bridge server (`nao-api`)

### Requirements

- Python 3.8+ (standard library only — **zero external dependencies**)
- An OpenAI API key with access to `whisper-1` and `gpt-4o`
- (Optional) Docker + Docker Compose

### Setup

```bash
cd nao-api
./scripts/setup.sh          # creates folders + .env from the template
nano .env                   # set OPENAI_API_KEY and AUTH_TOKEN
python3 app/server.py       # starts at http://0.0.0.0:8080
```

Or with Docker:

```bash
cd nao-api/docker
docker-compose up --build
```

### Endpoint

```
POST /speech/id/{chat_id}/culture/{culture}/raw/{raw}/persona/{persona}/responselength/{length}/ai-version/{ai_version}
```

**Headers**

```
Authorization: <AUTH_TOKEN>
Content-Type: multipart/form-data
```

**Body (form-data)** — both fields optional:

| Field | Type |
|-------|------|
| audio | file (`.ogg` / `.wav`) |
| photo | file (`.jpg` / `.png`) |

Other endpoints: `GET /health`, `GET /status`, `GET /` (HTML dashboard),
`POST /admin/reload-knowledge`.

See [`nao-api/README.md`](nao-api/README.md) for the full server reference.

### Knowledge base (RAG)

Drop `.txt` or `.md` files into `nao-api/data/knowledge/`. They are indexed
automatically at startup (TF-IDF over the file contents) and the most relevant
excerpts are added to the GPT prompt. Use this to teach the robot about your
company, venue, products, or FAQ.

---

## Part 2 — Robot script (`nao_chatgpt_official.py`)

This script runs on a machine that can reach the robot over the network (it uses
the NAOqi Python SDK and connects to the robot via a broker). It orchestrates the
full behavior: sit, wait for a head touch, stand, greet, then loop through
record → photo → ask the server → speak.

### Requirements

- Python 2.7 with the **NAOqi 2.1 Python SDK** available on the import path
- `requests` and `paramiko` (`pip install requests paramiko`)
- Network access to both the robot and the bridge server

### Configure

Edit the configuration block near the top of the script:

```python
NAO_IP          = "192.168.0.2"          # robot IP
SERVER_IP       = "192.168.0.8:8080"     # bridge server IP:port
AUTH_TOKEN      = "change-this-auth-token" # must match the server's AUTH_TOKEN
RESPONSE_LENGTH = "short"                 # "short" | "medium" | "standard"
ROBOT_LANGUAGE  = "Brazilian"            # NAOqi TTS language
```

### Run

```bash
python nao_chatgpt_official.py
# or override at launch:
python nao_chatgpt_official.py --pip 192.168.0.2 --server 192.168.0.8:8080
```

> **Note on language:** the robot's spoken phrases (greeting, "thinking" filler,
> farewell) and the spoken-language setting default to Brazilian Portuguese,
> matching the TTS voice the script was built and tuned for. The conversational
> answers themselves come from the server and follow the prompt/persona you
> configure. Logs, comments, and the server are in English. Adjust the spoken
> phrases and `ROBOT_LANGUAGE` if you want a different robot voice.

### Choregraphe configuration (Not Recomended)

If you wire the behavior through Choregraphe boxes instead, set:

- `CHATGPT SERVER` → this machine's IP, e.g. `192.168.1.100:8080`
- `CHATGPT PERSONA` → the persona name (ASCII, no accents — it goes in the URL)
- `CHATGPT RESPONSE LENGTH` → `short` / `medium` / `standard`

## Security notes

Before deploying this anywhere beyond a trusted LAN, please:

- **Change `AUTH_TOKEN`.** It ships as the placeholder `change-this-auth-token`
  in both the server (`.env`) and the robot script. Set a strong, matching value
  in both places.
- **Change the NAO SSH credentials.** The robot script uses the NAO factory
  default (`nao` / `nao`) for SFTP transfers. These are publicly known — change
  the password on the robot and update `NAO_SSH_PASS` accordingly.
- **Never commit your real `.env`.** It is listed in `.gitignore`. Only
  `.env.example` (with placeholder values) belongs in version control.
- **Keep your OpenAI key private.** It lives only in `.env` on the server host.
- Consider putting the server behind the bundled nginx reverse proxy (TLS +
  rate limiting) for any non-local exposure.

## License

Add your license of choice here (e.g. MIT) before publishing.
