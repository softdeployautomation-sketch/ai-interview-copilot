# 🎤 AI Interview Copilot — Setup Guide

This guide gets you from download to your first AI-assisted call in **under 10 minutes**.

---

## 📋 Requirements

- **Python 3.10 or higher** ([python.org/downloads](https://www.python.org/downloads/))
- **ffmpeg** (for browser audio decoding) — `brew install ffmpeg` on Mac
- **A free Groq API key** ([console.groq.com/keys](https://console.groq.com/keys))
- **macOS, Linux, or Windows**

---

## 📦 Step 1: Install Python (if you don't have it)

Open Terminal / Command Prompt and check:
```bash
python3 --version
```

If you see `Python 3.10.x` or higher → good. Otherwise:
- **Mac:** `brew install python@3.11`
- **Windows:** Download installer from [python.org](https://www.python.org/downloads/) — check "Add to PATH"
- **Linux:** `sudo apt install python3.11 python3-pip python3-venv`

---

## 📦 Step 2: Install ffmpeg

The app uses ffmpeg to decode browser audio recordings.

- **Mac:** `brew install ffmpeg`
- **Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html) → add to PATH
- **Linux:** `sudo apt install ffmpeg`

Verify: `ffmpeg -version`

---

## 📦 Step 3: Install AI Interview Copilot

1. **Unzip** the file you downloaded
2. Open Terminal
3. Navigate to the folder:
   ```bash
   cd ai-interview-copilot
   ```
4. Create a virtual environment (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate    # Mac/Linux
   venv\Scripts\activate       # Windows
   ```
5. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔑 Step 4: Get Your Free Groq API Key (60 seconds)

1. Go to **[console.groq.com/keys](https://console.groq.com/keys)**
2. Sign in with Google (no credit card needed)
3. Click **"Create API Key"**
4. **Copy the key** (starts with `gsk_...`)

---

## ⚙️ Step 5: Configure

1. Copy the example config:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` in any text editor
3. Replace `gsk_YOUR_KEY_HERE` with your actual Groq key:
   ```
   GROQ_API_KEY=gsk_abc123xyz...
   ```
4. Save and close

---

## 📚 Step 6: Build Your Knowledge Base

This is the secret sauce. The AI grounds its answers in YOUR files.

In the `kb/` folder, add:
- `resume.md` — your resume
- `projects.md` — projects you've worked on
- `company.md` — info about the company you're interviewing with
- `faq.md` — frequently asked questions + your answers
- `objection_handlers.md` — sales-specific responses
- Any `.md`, `.txt`, `.pdf`, or `.docx` files

The AI will search these files and pull relevant chunks during the conversation.

**Tip:** More specific files = better answers. Don't dump everything in one massive file.

---

## 🚀 Step 7: Launch

```bash
./run_server.sh           # Mac/Linux
# OR on Windows:
python app.py
```

You'll see:
```
🎤 Starting AI Interview Copilot on port 5055...
   Open http://localhost:5055 in your browser
```

Open: **http://localhost:5055**

---

## 🎯 Step 8: Use It Live

1. Start your call (Zoom / Google Meet / phone)
2. In your browser, click **"Listen"** in the AI Interview Copilot
3. Grant microphone permission
4. When asked a question, click **"Stop & Answer"**
5. Within 3-5 seconds, you'll see:
   - The transcribed question
   - A focused, grounded answer pulled from your KB
   - Source files used

**Pro tip:** Position the browser window next to your meeting window for hands-free reading.

---

## 🆘 Troubleshooting

**"No module named 'flask'"**
→ Activate your venv first: `source venv/bin/activate`

**"GROQ_API_KEY not set"**
→ Check that `.env` exists in the app folder and contains your real key

**"ffmpeg: command not found"**
→ Install ffmpeg (Step 2). On Mac: `brew install ffmpeg`

**"Microphone permission denied"**
→ Refresh the browser tab and allow microphone access when prompted

**Transcription is slow**
→ Make sure you're using Groq cloud mode (default). It's ~3x faster than local Whisper.

**Answers are too generic**
→ Add more specific files to your `kb/` folder. The AI can only ground in what you give it.

---

## 🔄 Advanced: Offline Mode

Want to run 100% offline? (No internet, no API calls)

1. Install [Ollama](https://ollama.com) on your machine
2. Pull a model: `ollama pull llama3.1:8b`
3. Uncomment the offline section in your `.env`
4. Install offline Whisper: `pip install faster-whisper`
5. Restart the app

---

## 📬 Support

Stuck? Email **support@buildwithai.com** — we respond within 24 hours.

Ace your interviews! 🎤

— **Build With AI**
