# 🎤 AI Interview Copilot

**Your real-time AI assistant for interviews, sales calls, and meetings.**

Listens to questions → searches YOUR knowledge base → generates grounded, accurate answers in seconds. Runs locally on your machine. Privacy-first.

---

## ✨ What It Does

You're on a job interview / sales call / important meeting. The other side asks a question. AI Interview Copilot:

1. **Listens** to the question via your microphone
2. **Transcribes** the audio (powered by Whisper)
3. **Searches** your personal knowledge base — resume, company info, FAQs
4. **Generates** a focused answer using AI, grounded in YOUR information
5. **Displays** the answer in your browser within seconds

Perfect for:
- **Job interviews** — load your resume + project notes → never get caught off guard
- **Sales calls** — load product docs + objection handlers → confident responses
- **Customer support** — load knowledge base → consistent, accurate answers
- **Live meetings** — load company info + agenda → never miss a beat

---

## ⚡ Quick Start (5 minutes)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Get your FREE Groq API key
#    → https://console.groq.com/keys

# 3. Configure
cp .env.example .env
# Edit .env and paste your Groq key

# 4. Add your knowledge files to the kb/ folder (resume, notes, etc.)
# 5. Launch
./run_server.sh
```

Open: **http://localhost:5055**

See **INSTALL_GUIDE.md** for the complete walkthrough.

---

## 🎁 What You Get

- Full source code (Python + Flask + Whisper integration)
- Cloud mode (FREE via Groq API) — no model downloads needed
- Optional offline mode (Ollama + faster-whisper)
- Knowledge base ingestion (.md, .txt, .pdf, .docx)
- BM25-powered retrieval
- Browser UI — works in any modern browser
- Free lifetime updates
- Email support

---

## 🔒 Privacy

- Everything runs on YOUR machine
- Knowledge base never leaves your computer
- Audio sent ONLY to Groq's transcription API (cloud mode)
- Or 100% offline with local Whisper + Ollama (advanced mode)

---

Built by **Build With AI**.
