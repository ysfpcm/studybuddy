# Courses

One folder per class. Inside each:

- `course.yaml` with `name`, `code`, `instructor`, `order` (sidebar position) and `notes` for the tutor
- `material/`: whatever you download from Canvas (PDF, PowerPoint, Word, Markdown/text, code files)

| Folder | Class |
|---|---|
| `cng20421-cloud-computing` | CNG20421N1 Cloud Computing, Stephen Han |
| `cng10241-network-plus` | CNG10241H3 Networking I: Network+, Joel Ramirez |
| `cng10321-security-plus` | CNG10321N2 Network Security Fundamentals (Security+), Tom Atwood |
| `cis20231-linux` | CIS20231N2 Linux Fundamentals, Richard Gilson |

Put the **syllabus** in first (a filename containing "syllabus" is read first when building the concept map).
Subfolders are fine (`material/week-03/...`). After adding files, click **Re-index**. Indexing also runs on startup.

To add a class, copy a folder, rename it (lowercase-with-dashes) and edit `course.yaml`. To hide a folder, add `hidden: true` to its `course.yaml`.
The four active course folders are the only course folders included here.
