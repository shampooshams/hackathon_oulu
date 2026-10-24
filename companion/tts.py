"""Turn a two-host podcast script into audio.

With a Gemini key: Gemini's multi-speaker text-to-speech (natural voices, a WAV file).
Without one, or if it fails: the browser's built-in voices read the lines in turn.
Citations like [F3] are removed before speaking; the [Ad] line is read as "Advertisement".
"""
from __future__ import annotations

import io
import json
import os
import re
import wave

from companion.offline import HOSTS
from companion.verify import strip_citations

VOICES = {HOSTS[0]: "Kore", HOSTS[1]: "Puck"}   # Gemini prebuilt voices
LINE = re.compile(r"^\s*(" + "|".join(HOSTS) + r")\s*:\s*(.+)$")


def script_lines(text: str) -> list[tuple[str, str]]:
    """[(host, spoken text)], ready to read aloud."""
    out = []
    for raw in text.splitlines():
        m = LINE.match(raw)
        host, said = (m.group(1), m.group(2)) if m else (HOSTS[0], raw)
        said = strip_citations(said).replace("[Ad]", "Advertisement.").replace("*", "").strip()
        if said:
            out.append((host, said))
    return out


def gemini_audio(text: str) -> bytes:
    """WAV bytes from Gemini multi-speaker TTS. Raises if no key or the call fails."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("no Gemini key")
    from google import genai
    from google.genai import types

    script = "\n".join(f"{h}: {s}" for h, s in script_lines(text))
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[types.SpeakerVoiceConfig(speaker=h, voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=v))) for h, v in VOICES.items()])))
    resp = genai.Client(api_key=key).models.generate_content(
        model=os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"),
        contents=f"Read this sports podcast as a lively, natural conversation:\n{script}", config=config)
    pcm = resp.candidates[0].content.parts[0].inline_data.data   # 16-bit mono PCM, 24 kHz
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return buf.getvalue()


def browser_player(text: str, lang: str = "en-GB") -> str:
    """HTML/JS player that reads the lines with two different browser voices."""
    payload = json.dumps(script_lines(text)).replace("</", "<\\/")
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;color:#f0f4f5;display:flex;align-items:center;gap:.5em">
 <button id="play" style="padding:.55em 1.1em;border-radius:6px;border:0;background:#d3fa5b;color:#122014;
   font-weight:800;cursor:pointer">▶ Play</button>
 <button id="stop" style="padding:.55em 1.1em;border-radius:6px;border:1px solid #3a4652;background:#202b36;
   color:#f0f4f5;cursor:pointer">■ Stop</button>
 <span id="now" style="font-size:12px;color:#9ba7b4">Browser voices</span>
</div>
<script>
 const lines = {payload}, hosts = {json.dumps(list(HOSTS))};
 function voicesFor() {{
   const all = speechSynthesis.getVoices().filter(v => v.lang.startsWith('{lang[:2]}'));
   return [all[0] || null, all[1] || all[0] || null];
 }}
 document.getElementById('play').onclick = () => {{
   speechSynthesis.cancel();
   const vs = voicesFor();
   lines.forEach(([host, text]) => {{
     const u = new SpeechSynthesisUtterance(text);
     const i = hosts.indexOf(host); u.lang = '{lang}'; u.rate = 1.04;
     if (vs[i]) u.voice = vs[i]; u.pitch = i === 1 ? 0.85 : 1.15;
     u.onstart = () => document.getElementById('now').textContent = host + ' speaking…';
     speechSynthesis.speak(u);
   }});
 }};
 document.getElementById('stop').onclick = () => speechSynthesis.cancel();
</script>"""
