# Study Buddy Page Reader (Chrome / Edge extension)

This extension lets your tutor read the exact text of the page you're studying, such as a TestOut lesson, a Canvas page or AWS docs, with no screenshots or copy-paste.

## Install (one time)
1. Open `chrome://extensions` (in Edge, `edge://extensions`).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `extension` folder.
4. Pin it: click the puzzle icon, then the pin next to **Study Buddy Page Reader**.

## Use
- Open your lesson, click the orb icon and choose **Follow this tab**. The badge shows **ON**.
- As you scroll, click Next or open sections, the tutor gets the updated text within a second or two. In Study Buddy, the "📖 Reading along" card shows what it has.
- Ask naturally: "explain 1.1.1", "what does this section mean by…". To point at a specific part, highlight the text first.
- **Save to notes** stores lesson pages in the course's `material/pages/` folder so the tutor can search them later. Turn on **Auto-save** to save lessons as you study. Lab and activity pages remain synced for live help but are not saved as lessons.

## Privacy
- Only the tab you follow is read. Text goes only to Study Buddy at `127.0.0.1` on your PC, and it's kept in memory unless you save it.
- Web pages can't send fake "page content" to your tutor. The server only accepts requests carrying the extension's header.

## Limits
- It can't read PDFs open in the browser's PDF viewer, video frames, or canvas-drawn labs. Use **Ctrl+V** with a screenshot for those.
