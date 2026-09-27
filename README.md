# Study Buddy

A voice tutor for your classes. You talk to **GPT-Live-1**, OpenAI's full-duplex voice model, so you can interrupt it any time. The thinking is done by **GPT-6 Luna**, which reads your course material, teaches with real-world analogies, gives hints one step at a time instead of answers, and records what you've mastered.

```
 you ⇄ (WebRTC audio) ⇄ GPT-Live-1 ──delegates──▶ GPT-6 Luna
                             │                        │ function calls
                             ▼                        ▼
                     browser UI  ──relays──▶  local server (this app)
                     transcript + board        course index (SQLite FTS) + progress
```

## Setup (Windows, one time)

1. Install Python 3.11+ from python.org and tick "Add to PATH".
2. Double-click `setup.bat`.
3. Open `.env` and paste your `OPENAI_API_KEY`.
4. Double-click `run.bat`. The app opens at http://127.0.0.1:8765. Use Chrome or Edge and allow the microphone.

## Your classes

Each class has its own section in the sidebar:

| Folder | Class |
|---|---|
| `courses/cng20421-cloud-computing` | CNG20421N1 Cloud Computing, Stephen Han |
| `courses/cng10241-network-plus` | CNG10241H3 Networking I: Network+, Joel Ramirez |
| `courses/cng10321-security-plus` | CNG10321N2 Network Security Fundamentals (Security+), Tom Atwood |
| `courses/cis20231-linux` | CIS20231N2 Linux Fundamentals, Richard Gilson |

- Download each class's files from Canvas (syllabus first) into its `material/` folder. Click **Re-index**, then **Build concept map**.
- Selecting a class opens its page with **all your chats for that class**, newest first. Click a chat to reread it, and use **Continue this chat** to pick it up in any mode. The tutor gets the end of that conversation as context.
- To tell the tutor how a class is taught or graded, edit `notes:` in its `course.yaml`.
- Fill in **About me** in the sidebar. The tutor uses it to pick analogies from things you already know.

If you keep class files somewhere else, set `COURSES_DIR` in `.env`.

## Orbi

The little black orb in the top right is your study companion. It sleeps when no session is running, listens (with a ring that pulses when you talk), looks around while thinking, scans while it checks your screen, and glows in time with the tutor's voice. Its eyes follow your cursor. Click it to say hi, and click its name to rename it.

## Study modes

| Mode | What happens |
|---|---|
| Guided lesson | Teaches the next concept you need, starting with an analogy, and checks your understanding as it goes |
| Teach it back | You explain the concept and it grades you against the course material |
| Oral quiz | Asks you to recall answers, prioritizing what's due for review and what you're weak on |
| Problem walkthrough | Guides you through math, code or labs using hints that escalate one step at a time |
| Exam prep | Asks exam-style questions and ends with a debrief |
| 5-minute review | A quick warm-up before class |

**Hint ladder:** your attempt → nudge → analogy → one partial step → similar worked example → walk through it together. It gives a direct answer only if you ask twice, and then immediately asks you a variation to prove you can do it yourself.

## While you study

- **Board (right panel):** code and math appear here instead of being read aloud.
- **Screenshots:** press **Win+Shift+S**, then **Ctrl+V** in the app. You can also drag an image in or use **📎**. Add a question, or just press Enter. The screenshot is read once into text: question and answer choices, code, errors, IPs, diagram layout, or each step of handwritten work. Only that text goes to the tutor. The image isn't saved to disk, isn't stored by OpenAI (`store: false`) and isn't added to the conversation. This works in every mode, and each read costs about $0.0002.
- **Typing box:** paste code or type during a voice session.
- **Ctrl+Space** mutes and unmutes the mic.
- **Text mode** uses the same tutor without voice. It's cheaper and good for code-heavy sessions.
- **Three ways to study:** **Voice · Premium** (GPT-Live-1, the most natural conversation), **Voice · Economy** (browser speech recognition, Luna, and GPT-4o Mini TTS for natural spoken replies), and **Text**. Economy is turn-based; press **Esc** to stop playback.
- Transcripts are saved in `data/sessions/`. Progress and spend are saved in `data/studybuddy.db`.

## The war room (right side)

The right side has three tabs:

Drag either vertical divider to resize the course list, lesson pane, or chat. The widths are remembered; double-click a divider to reset them.

- **War room:** follows the chat you have open. As you talk, it builds a recap every few exchanges: what you covered, key terms in plain words, what clicked for you, your weak spots with a one-line fix for each, quick-check cards (tap to reveal the answer) and what to study next. Everything the tutor puts on the board (tables, diagrams, code, math) stays below the recap. Reopen an old chat and its recap and board come back with it.
- **Lessons & practice:** every saved lesson page and class file for the course, sorted by section (1.1.1, 1.1.2…). Each one has:
  - **Flashcards and a mini quiz** above the breakdown. Opening a lesson generates questions from that lesson and links every question to its concept map. Quiz answers are shuffled and balanced on every attempt. Flip a card, rate how well you recalled it, or choose a quiz answer to see an explanation. Each answer updates the concept's mastery, review schedule, and class progress bar. Retry the set or generate new questions for repeated practice. Build the concept map first so answers can be scored against it;
  - a **Breakdown** that goes through every section of the lesson in order. Each section gets a plain-words explanation, an analogy and an example, plus a comparison table when the lesson compares things. It ends with key terms, a "memorize for the exam" list, exam traps and check-yourself questions. The app checks that every lesson heading made it into the breakdown and fills in any it skipped;
  - **My notes**, a box that saves as you type;
  - the original text.

  Lesson pages you save from the extension get a breakdown and a full lesson test automatically. **Now reading** at the top shows the lesson the extension is following, with a ✓ for each section it captured, so you can see it got everything. It also has a **Save & study** button. Each lesson is saved once per section number (for example `1-1-1-networking-concepts.md`); revisiting a lesson updates that note instead of duplicating it, and your own notes carry over. Lab and activity pages stay synced for live tutoring but are not auto-saved, broken down, or turned into lesson tests.
- **Quiz:** a separate test for each saved lesson page, with at least 10 applied questions generated by GPT-6 Luna. Start a test, see an explanation after each answer, and track the result through the same concept map and class progress. Retake it with shuffled answer positions or use **Regenerate questions** to generate another test at model cost. Existing lessons receive tests when the app starts. If a new lesson has no concepts in the map, Study Buddy adds them before generating its test.
- **Course summary:** one study guide for the whole course, built from all your notes, your own notes and your chat recaps. It's organized by section and starts with where you stand. Rebuild it whenever you want. It runs on the half-price Flex tier.

Cost: summaries, recaps and the guide are text-only Luna calls, each about a tenth of a cent. They count toward your monthly spend.

## Reading along with your lesson (browser extension)

With the **Study Buddy Page Reader** extension, the tutor reads the exact text of the page you're studying, like TestOut, Canvas or AWS docs. It's more complete and accurate than screen sharing, and it's cheap because it sends text, not images.

1. **Install (one time):** open `chrome://extensions`, turn on Developer mode, click **Load unpacked** and pick the `extension` folder. Then pin the orb icon.
2. On your lesson tab, click the orb and choose **Follow this tab**. The badge turns **ON**.
3. The "📖 Reading along" card in Study Buddy shows what it's synced. The text updates as you scroll, click Next or open sections, including embedded frames such as video transcripts and the answers you've selected.
4. Talk normally: "walk me through 1.1.1", "what's the difference between the appliances and functions part?" The tutor calls `read_page` and teaches from what the page actually says. On long pages it jumps to the part you're asking about.
5. **Highlight** text on the page to point at a specific part.
6. **Save to course notes**, or turn on **Auto-save** in the extension, to store pages in `material/pages/`. The tutor can search them in any later session.

The extension only reads the tab you follow, and the text goes only to Study Buddy on your PC. PDFs in the browser viewer, videos and canvas-drawn labs can't be read as text; use a Ctrl+V screenshot for those.

## Eyes (screen sharing)

Click **👁 Share screen** and choose a window, such as the AWS console, VS Code or your slides. The tutor doesn't watch continuously. It looks only when it needs to:

- **Premium voice:** Luna calls `look_at_screen` whenever you say "this", "look" or "I'm getting an error", or when it's unsure what you're doing.
- **Economy voice and Text:** your screen is described along with each thing you say.
- **📸 Look** sends the current screen right away.

The app takes a small fingerprint of each screenshot. If the screen hasn't changed since the last look, it reuses the previous description at no cost. A fresh look sends a downscaled screenshot to Luna and costs about $0.0001. Luna returns a short text description with any code, errors and question text copied out word for word, so the conversation carries text instead of image tokens. The last thing the tutor saw is shown above the board.

Unrelated personal content, like email or messages, is summarized as "unrelated personal content" and not transcribed. It's still best to share a single window rather than your whole screen.

To make looks free, set `VISION_PROVIDER=ollama` and pull a vision model (`ollama pull qwen2.5vl:7b`). It's slower and less accurate at reading small code.

## Cost: where the money goes and how it's kept low

| Item | Price | Rough cost per hour of studying |
|---|---|---|
| Premium voice (GPT-Live-1) | $0.05/min, per second of session time | **$3.00** |
| Luna brain (input $0.20/M, cached $0.02/M, output $1.00/M) | per token | Varies with conversation length |
| Eyes | about $0.0001 per fresh look | under $0.01 |
| Economy voice (browser recognition + Luna + GPT-4o Mini TTS) | TTS is billed for generated speech; receipt shows an estimate | Depends on how much the tutor speaks |

Nearly all of the cost is premium voice minutes, so most of the savings come from reducing them:

1. **Choose the mode by task.** Use premium voice for deep lessons and walkthroughs where natural back-and-forth matters. Use **Economy voice** or **Text** for quizzes, 5-minute reviews and code-heavy work. Economy voice is billed for the speech it generates, rather than the full time you're connected.
2. **Idle auto-end:** a premium session ends after `IDLE_END_SECONDS` of silence (180 by default). **Resume** starts a new session that picks up the conversation.
3. **Hard caps:** `MAX_SESSION_MINUTES` limits a single session, and `MONTHLY_BUDGET` pauses premium voice once the month's total is reached. Economy and Text keep working after that.
4. **Prompt caching:** tutor instructions stay the same and use a fixed `prompt_cache_key`, so most of Luna's input is billed at the cached rate, about 10× cheaper. The receipt shows your cache hit rate.
5. **Flex tier** (50% off) is used for background jobs like building the concept map.
6. **Search is local and free:** SQLite full-text search, with no embedding API.
7. **Screen change detection:** the tutor only pays to look when your screen has actually changed.

**Receipts:** every session ends with a receipt covering voice minutes, Luna tokens (with cache %), eyes, total, and month-to-date against your budget. The sidebar shows the month and today. Figures come from what the API reports: session duration and token usage. If GPT-Live doesn't report Luna usage in delegation mode, the receipt says so rather than guessing. OpenAI's billing dashboard remains the official record.

## Troubleshooting

- **`model_not_found` / 403 right after the session starts:** this is a known issue with GPT-Live delegation permissions. Set `DELEGATION_MODE=client` in `.env`. In that mode this app calls Luna itself and GPT-Live speaks the result. Latency is slightly higher, but the behavior is the same.
- **Luna isn't accepted as a delegation backend:** OpenAI's examples use `gpt-5.6-luna`. Set `BRAIN_MODEL=gpt-5.6-luna`, or use `DELEGATION_MODE=client`, which calls `gpt-6-luna` directly.
- **The tutor answers without checking your material:** that's a known GPT-Live quirk. Say "check my notes" or switch to client mode.

## Code map

- `studybuddy/ingest.py`: extracts files and splits them into chunks, organized by course
- `studybuddy/retrieval.py`: BM25 search scoped to one course
- `studybuddy/progress.py`: mastery scores and the spaced-review schedule
- `studybuddy/prompts.py`: teaching style, modes and hint ladder. **Edit this file to change how the tutor teaches.**
- `studybuddy/tools.py`: the tools Luna can call (`search_material`, `get_study_focus`, `record_attempt`, `show_on_board`, `look_at_screen`, `read_page`)
- `studybuddy/brain.py`: GPT-Live session config, the Luna tool loop and screen descriptions
- `studybuddy/spend.py`: session receipts, monthly totals and the budget cap
- `studybuddy/server.py`: FastAPI server, bound to localhost only
- `studybuddy/notes.py`: course notes, lesson breakdowns, chat recaps, study guide
- `web/warroom.js`: the war room (recap, board, notes, course summary)
- `studybuddy/page.py`: the synced lesson page (kept in memory) and saving pages to notes
- `extension/`: the Page Reader browser extension
- `web/`: the UI (WebRTC, event handling, board)

Run the tests with `.venv\Scripts\python -m pytest`.
