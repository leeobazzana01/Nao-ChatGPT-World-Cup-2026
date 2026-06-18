# NAO V5 ↔ ChatGPT API — Bridge Server

A complete REST API that receives audio and an image from the NAO V5 robot,
transcribes the audio with Whisper, analyzes the image with GPT-4o vision,
and returns text for the robot to speak.

## Requirements

- Python 3.8+ (standard library only — zero external dependencies)
- An OpenAI API key with access to: `whisper-1`, `gpt-4o`
- (Optional) Docker + Docker Compose

## Structure

```
nao-api/
├── app/
│   ├── server.py          # Main HTTP server (pure stdlib)
│   ├── config.py          # Configuration via .env
│   ├── routes/
│   │   └── speech.py      # Handler for the /speech/... endpoint
│   ├── services/
│   │   ├── transcription.py   # Whisper API
│   │   ├── vision.py          # GPT-4o Vision
│   │   ├── chat.py            # GPT-4o Chat + RAG
│   │   ├── sessions.py        # Session management
│   │   └── knowledge.py       # RAG / knowledge base
│   └── utils/
│       ├── multipart.py       # multipart/form-data parser
│       ├── logger.py          # Colored logging
│       └── responses.py       # HTTP response helpers
├── data/
│   ├── sessions/          # Session history (JSON)
│   └── knowledge/         # .txt/.md files for RAG
├── logs/                  # Application logs
├── tests/
│   └── test_api.py        # Tests with simulated requests
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── scripts/
│   └── setup.sh           # Quick setup
├── .env.example           # Environment-variable template
└── README.md
```

## Quick Start

### 1. Configure environment variables

```bash
cp .env.example .env
#edit the .env and set your OPENAI_API_KEY
nano .env
```

### 2. Run directly (Python)

```bash
python3 app/server.py
# Server starts at http://0.0.0.0:8080
```

### 3. Run with Docker

```bash
cd docker
docker-compose up --build
```

## Main Endpoint

```
POST /speech/id/{chat_id}/culture/{culture}/raw/{raw}/persona/{persona}/responselength/{length}/ai-version/{ai_version}
```

**Headers:**
```
Authorization: change-this-auth-token
Content-Type: multipart/form-data
```

**Body (form-data):**
| Field | Type | Required |
|-------|------|----------|
| audio | file (.ogg/.wav) | No |
| photo | file (.jpg/.png) | No |

**Response:**
- `200 OK` + text for the robot to speak
- `"STOP"` — the user asked to stop
- `"skip"` — duplicate request
- `""` — critical error

## RAG — Knowledge Base

Place `.txt` or `.md` files in `data/knowledge/`.
The system loads them automatically and uses them as context for GPT.

Example:
```
data/knowledge/company.txt     → Information about the company
data/knowledge/products.txt    → Product catalog
data/knowledge/faq.txt         → Frequently asked questions
```

## Security

- Authentication token configurable via `.env`
- Rate limiting per IP and per chat_id
- Full logging of every request
- Input sanitization

## NAO Configuration

In Choregraphe, in the configuration boxes:
- `CHATGPT SERVER`: this machine's IP on the local network (e.g. `192.168.1.100:8080`)
- `CHATGPT PERSONA`: the desired persona name
- `CHATGPT RESPONSE LENGTH`: `short` / `medium` / `standard`
