#!/usr/bin/env bash
# scripts/setup.sh — Initial setup for the NAO API
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════╗"
echo "║      NAO API — Initial Setup             ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"

#project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

#python
echo -e "${CYAN}[1/4] Checking Python...${NC}"
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}ERROR: Python 3 not found. Install Python 3.8+${NC}"
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  Python $PY_VER found ✓"

#check minimum version
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" || {
    echo -e "${RED}ERROR: Python 3.8+ required (found $PY_VER)${NC}"
    exit 1
}

#directories
echo -e "${CYAN}[2/4] Creating directories...${NC}"
mkdir -p data/sessions data/knowledge logs
echo "  data/sessions/ ✓"
echo "  data/knowledge/ ✓"
echo "  logs/ ✓"

#.env
echo -e "${CYAN}[3/4] Configuring .env...${NC}"
if [ -f ".env" ]; then
    echo -e "  ${YELLOW}.env already exists — not overwriting${NC}"
else
    cp .env.example .env
    echo -e "  .env created from .env.example"
    echo ""
    echo -e "  ${YELLOW}IMPORTANT: Edit .env and set your OPENAI_API_KEY${NC}"
    echo "  Run: nano .env"
fi

#checking wether OPENAI API is configured or not
if [ -f ".env" ]; then
    KEY=$(grep "OPENAI_API_KEY" .env | cut -d= -f2 | tr -d '"' | tr -d "'")
    if [[ "$KEY" == "sk-proj-your-openai-api-key-here" || -z "$KEY" ]]; then
        echo -e "  ${RED}WARNING: OPENAI_API_KEY not configured in .env!${NC}"
    else
        echo -e "  OPENAI_API_KEY configured ✓"
    fi
fi

#example of knowledge
echo -e "${CYAN}[4/4] Creating example knowledge file...${NC}"
if [ ! -f "data/knowledge/example.txt" ]; then
    cat > data/knowledge/example.txt << 'EOF'
# General Information

This file is an example knowledge base for the NAO robot.
You can edit this file or create new .txt/.md files in this folder.

The RAG (Retrieval-Augmented Generation) system indexes every file
in this folder automatically when the server starts.

## How to use

Add information relevant to the context where the robot will be used:
- Company or organization name
- Products or services offered
- Frequently asked questions (FAQ)
- Procedures and rules
- Any domain-specific knowledge

## Example: FAQ

**Question:** What are the opening hours?
**Answer:** Opening hours are Monday to Friday, 8am to 6pm.

**Question:** How do I contact support?
**Answer:** By email at support@example.com or by phone at (555) 123-4567.
EOF
    echo "  data/knowledge/example.txt created ✓"
else
    echo "  Existing knowledge files kept ✓"
fi

#final result
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗"
echo "║  Setup complete!                         ║"
echo "╚══════════════════════════════════════════╝${NC}"
echo ""
echo "To start the server:"
echo -e "  ${CYAN}python3 app/server.py${NC}"
echo ""
echo "To start with Docker:"
echo -e "  ${CYAN}cd docker && docker-compose up --build${NC}"
echo ""
echo "Choregraphe configuration (NAO):"
echo "  CHATGPT SERVER → <THIS_MACHINE_IP>:8080"
echo ""
