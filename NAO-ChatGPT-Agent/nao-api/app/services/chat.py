"""
services/chat.py — Main orchestrator: builds the prompt, calls GPT, returns the reply.

Flow:
  1. Builds the system prompt (persona + length instruction + RAG context)
  2. Retrieves the session history
  3. Adds the user message (with optional image)
  4. Calls GPT
  5. Persists the reply in the history
  6. Returns the text for the robot to speak
"""

import time
from typing import Optional
from app.services import openai_client as oai
from app.services.knowledge import KnowledgeBase
from app.services.sessions import SessionManager
from app.services import vision as vis_svc
from app.utils import logger as log_module

_log = log_module.get("chat")

#response length map -> instruction + max_tokens
_RESPONSE_LENGTH = {
    "short":    ("Answer in at most 2 short, direct sentences.", 120),
    "medium":   ("Answer in 3 to 4 sentences with moderate detail.", 250),
    "standard": ("Answer in a full, informative paragraph.", 450),
}

#locale -> language map
_LOCALE_LANG = {
    "en": "English", "en-gb": "English", "en-us": "English",
    "pt": "Portuguese", "pt-br": "Brazilian Portuguese", "pt-pt": "European Portuguese",
    "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "ru": "Russian", "ar": "Arabic",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish",
    "sv": "Swedish", "da": "Danish", "fi": "Finnish",
}


class ChatService:
    def __init__(
        self,
        api_key: str,
        model: str,
        sessions: SessionManager,
        knowledge: KnowledgeBase,
        personas=None,        # PersonaManager (identity from disk)
        copa=None,            # CopaService (live World Cup scores)
        timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._sessions = sessions
        self._knowledge = knowledge
        self._personas = personas
        self._copa = copa
        self._timeout = timeout

    def respond(
        self,
        chat_id: str,
        persona: str,
        culture: str,
        response_length: str,
        ai_version: str,
        user_text: str,
        image_data: Optional[bytes] = None,
        image_filename: str = "image.jpg",
    ) -> "ChatResult":
       
       #returns ChatGPT text result to robot speak  
        t0 = time.perf_counter()

        #determine the effective model
        model = self._resolve_model(ai_version)

        #building RAG context
        rag_context = ""
        if self._knowledge.chunk_count > 0 and user_text:
            rag_context = self._knowledge.format_context(user_text, top_k=5)

        #live score -> ONLY when the prompt explicitly asks for a real-time result
        #this is the on-demand GET: ordinary turns never hit the live fetcher
        live_context = ""
        if self._copa and user_text:
            match = self._copa.detect_live_query(user_text)
            if match is not None:
                live = self._copa.fetch_live(match)
                live_context = f"Placar ao vivo solicitado pelo usuário: {live.speakable()}"
                _log.info(f"Live query -> {match.id}: {live.status} ({live.source})")

        #building the system prompt
        system_prompt = self._build_system_prompt(
            persona=persona,
            culture=culture,
            response_length=response_length,
            rag_context=rag_context,
            live_context=live_context,
            has_image=(image_data is not None),
        )

        #retrieve history
        history = self._sessions.get_history(chat_id)

        #building the user message 
        if image_data and vis_svc.model_supports_vision(model):
            user_msg = vis_svc.prepare_image_message(
                image_data=image_data,
                filename=image_filename,
                user_text=user_text,
                detail="low",      #"low" = fast + cheap
            )
        else:
            user_msg = {"role": "user", "content": user_text}

        #building the full message list
        messages = [{"role": "system", "content": system_prompt}] + history + [user_msg]

        #max_tokens based on the desired length
        _, max_tokens = _RESPONSE_LENGTH.get(response_length, _RESPONSE_LENGTH["short"])

        #calling GPT
        try:
            reply_text = oai.chat_completion(
                messages=messages,
                api_key=self._api_key,
                model=model,
                max_tokens=max_tokens,
                temperature=0.7,
                timeout=self._timeout,
            )
        except oai.OpenAIError as exc:
            _log.error(f"GPT error: {exc}")
            return ChatResult(
                reply="",
                error=str(exc),
                model=model,
                elapsed=time.perf_counter() - t0,
            )

        #cleanning the reply for robot speech ---
        clean_reply = _clean_for_speech(reply_text)

        #persist in history
        new_messages = [
            user_msg,
            {"role": "assistant", "content": reply_text},
        ]
        self._sessions.append_messages(chat_id, persona, new_messages)

        elapsed = time.perf_counter() - t0
        _log.info(
            f"Chat OK | session={chat_id[:8]} | persona={persona} | "
            f"model={model} | len={len(clean_reply)} | {elapsed:.2f}s"
        )

        return ChatResult(
            reply=clean_reply,
            error=None,
            model=model,
            elapsed=elapsed,
        )

    #internals                                                       
    def _resolve_model(self, ai_version: str) -> str:
        #validates and resolves the model, falls back to the default model
        
        allowed = {
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
            "gpt-4-turbo-preview", "gpt-3.5-turbo",
        }
        v = ai_version.lower().strip()
        
        #accepts partial prefixes (e.g. "gpt-4" -> "gpt-4o")
        for a in allowed:
            if v == a or a.startswith(v):
                return a
        return self._model  #fallback

    def _build_system_prompt(
        self,
        persona: str,
        culture: str,
        response_length: str,
        rag_context: str,
        live_context: str = "",
        has_image: bool = False,
    ) -> str:

        #identity -> persona text from disk (falls back to a generic line)
        persona_text = None
        if self._personas is not None:
            persona_text = self._personas.get(persona)
        if not persona_text:
            persona_name = persona.replace("-", " ").strip() or "NAO Robot"
            persona_text = (
                f"You are {persona_name}, a friendly, helpful, and "
                f"expressive NAO humanoid robot."
            )

        #reply language
        lang_key = culture.lower().replace("_", "-").split("-")[0]
        full_lang = _LOCALE_LANG.get(culture.lower(), _LOCALE_LANG.get(lang_key, "English"))

        #length instruction
        length_instr, _ = _RESPONSE_LENGTH.get(response_length, _RESPONSE_LENGTH["short"])

        #identity block (who the robot is)
        lines = [persona_text, ""]

        #technical / TTS block (how the robot must speak) — kept separate from identity
        lines += [
            f"You are speaking directly to a human standing in front of you.",
            f"Always respond in {full_lang}.",
            f"Response length: {length_instr}",
            "Speak naturally and conversationally — your response will be read aloud by a text-to-speech engine.",
            "Do NOT use markdown, bullet points, emojis, code blocks, or any special formatting.",
            "Do NOT say 'As an AI' or refer to yourself as a language model.",
            "Keep your tone warm, engaging, and appropriate for spoken conversation.",
        ]

        if has_image:
            lines.append(vis_svc.build_vision_prompt_addition(has_image))

        #live score takes priority over RAG when present
        if live_context:
            lines.append("\n" + live_context)
            lines.append("Use this live score to answer; it is the most up-to-date information.")

        if rag_context:
            lines.append("\n" + rag_context)
            lines.append(
                "Use the above knowledge when relevant to answer the user's question. "
                "If the knowledge doesn't apply, answer from your general knowledge."
            )

        return "\n".join(lines)


def _clean_for_speech(text: str) -> str:#removes formatting that would hurt the NAO TTS output
    
    import re
    #removing markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    
    #removing bold/italic
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    
    #removing inline code
    text = re.sub(r"`+(.+?)`+", r"\1", text)
    
    #removing URLs
    text = re.sub(r"https?://\S+", "", text)
    
    #normalizing multiple line breaks
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r"\n", " ", text)
    
    #remove basic emojis (Unicode range)
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    
    #normalize whitespace
    text = " ".join(text.split())
    return text.strip()


class ChatResult:
    __slots__ = ("reply", "error", "model", "elapsed")

    def __init__(
        self,
        reply: str,
        error: Optional[str],
        model: str,
        elapsed: float,
    ) -> None:
        self.reply = reply
        self.error = error
        self.model = model
        self.elapsed = elapsed

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.reply)
