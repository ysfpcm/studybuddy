import json
import importlib
import io
import wave

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    courses = tmp_path / "courses"; (courses / "algebra" / "material").mkdir(parents=True)
    (courses / "algebra" / "course.yaml").write_text("name: College Algebra\n")
    (courses / "algebra" / "material" / "syllabus.txt").write_text("Quadratic formula solves ax^2+bx+c=0.")
    monkeypatch.setenv("COURSES_DIR", str(courses)); monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    import studybuddy.config, studybuddy.server
    importlib.reload(studybuddy.config); server = importlib.reload(studybuddy.server)
    with TestClient(server.app) as c:
        c.post("/api/courses/algebra/index")
        yield c, server


def test_endpoints(client):
    c, server = client
    assert c.get("/").status_code == 200 and c.get("/static/app.js").status_code == 200
    st = c.get("/api/status").json(); assert st["api_key_set"] and "quiz" in st["modes"]
    courses = c.get("/api/courses").json(); assert courses[0]["name"] == "College Algebra" and courses[0]["files"] == 1
    r = c.post("/api/tools/algebra/search_material", json={"query": "quadratic formula"}).json()
    assert "Quadratic" in r["output"]
    assert c.post("/api/tools/algebra/rm_rf", json={}).status_code == 404
    assert c.post("/api/tools/nope/search_material", json={}).status_code == 404
    c.post("/api/tools/algebra/record_attempt", json={"concept": "Quadratic formula", "outcome": "partial", "hint_level": 2})
    prog = c.get("/api/courses/algebra/progress").json()
    assert prog["concepts"][0]["attempts"] == 1
    assert c.put("/api/about_me", json={"text": "I'm a solutions architect"}).json()["ok"]
    assert "architect" in c.get("/api/about_me").json()["text"]
    st = c.post("/api/sessions/start", json={"course": "algebra", "mode": "quiz", "channel": "economy"}).json()
    assert st["sid"] and st["chat_id"]
    r = c.post(f"/api/sessions/{st['sid']}/close", json={"measured_seconds": 900, "client_usage": {"input_tokens": 2000, "output_tokens": 300},
                                                        "transcript": [{"role": "you", "text": "hi"}]}).json()
    assert r["channel"] == "economy" and r["cost_voice"] == 0 and r["cost_total"] > 0 and r["month"]["budget"] > 0
    assert (server.settings.data_dir / "sessions" / f"{st['sid']}.json").exists()
    assert c.post("/api/sessions/nope/close", json={}).status_code == 404
    assert c.get("/api/spend").json()["recent"][0]["id"] == st["sid"]


def test_lesson_practice_updates_concept_progress(client, monkeypatch):
    c, server = client
    lesson = server.settings.courses_dir / "algebra" / "material" / "syllabus.txt"
    lesson.write_text("# 1.1.1 Quadratic equations\n\n" +
                      "The quadratic formula solves ax squared plus bx plus c equals zero. " * 8,
                      encoding="utf-8")
    c.post("/api/courses/algebra/index")
    note_id = "material/syllabus.txt"
    url = "/api/courses/algebra/note/practice?id=material%2Fsyllabus.txt"
    assert c.post(url).status_code == 400  # concept map is required for scored practice
    with server.db_lock:
        key = server.progress.upsert_concept(server.conn, "algebra", "Quadratic formula", "1.1.1 Quadratic equations",
                                             "Use the formula to solve quadratic equations")
        server.progress.upsert_concept(server.conn, "algebra", "Linear functions", "2.1.1 Other lesson",
                                       "Plot a straight line")
        server.conn.commit()
    calls = []

    def fake_response(_settings, prompt, task, **_kwargs):
        assert task == "practice" and "quadratic formula" in prompt.lower() and key in prompt
        assert "linear functions" not in prompt.lower()
        calls.append(prompt)
        items = {
            "cards": [{"concept_key": key, "front": f"Recall {i}", "back": "Use the formula",
                       "explanation": "The formula finds roots."} for i in range(3)],
            "quiz": [{"concept_key": key, "question": f"Question {i}",
                      "options": ["Wrong", "Formula", "Guess", "Skip"], "correct_index": 1,
                      "explanation": "The formula is supported by the lesson; guessing is not."} for i in range(3)],
        }
        return json.dumps(items), {"input_tokens": 100, "output_tokens": 100}

    monkeypatch.setattr(server.brain, "response_text", fake_response)
    first = c.post(url).json()
    assert len(first["cards"]) == len(first["quiz"]) == 3
    assert "correct_index" not in first["quiz"][0]
    assert first["cards"][0]["concept_name"] == "Quadratic formula"
    assert len(calls) == 1 and not first["cached"]
    second = c.post(url).json()
    assert second["cached"] and second["run_id"] != first["run_id"] and len(calls) == 1
    with server.db_lock:
        run = json.loads(server.conn.execute("SELECT content FROM practice_runs WHERE id=?", (first["run_id"],)).fetchone()[0])
    assert len({q["correct_index"] for q in run["quiz"]}) == 3  # no all-A pattern, even from a fixed model key

    answer_url = url.replace("/practice?", "/practice/answer?")
    correct = next(q["correct_index"] for q in run["quiz"] if q["id"] == "q1")
    wrong = (correct + 1) % 4
    a = c.post(answer_url, json={"run_id": first["run_id"], "item_id": "q1", "choice": wrong}).json()
    assert a["outcome"] == "missed" and a["correct_index"] == correct and a["recorded"]
    assert "guessing" in a["explanation"]
    again = c.post(answer_url, json={"run_id": first["run_id"], "item_id": "q1", "choice": correct}).json()
    assert not again["recorded"] and again["outcome"] == "missed"
    card = c.post(answer_url, json={"run_id": first["run_id"], "item_id": "f1", "rating": "got_it"}).json()
    assert card["outcome"] == "got_it" and card["mastery"] > 0
    progress = next(x for x in c.get("/api/courses/algebra/progress").json()["concepts"] if x["name"] == "Quadratic formula")
    assert progress["attempts"] == 2 and progress["mastery"] == card["mastery"]
    assert c.get("/api/courses").json()[0]["avg_mastery"] > 0
    assert c.post(answer_url, json={"run_id": first["run_id"], "item_id": "q2", "choice": 4}).status_code == 400
    assert c.post(answer_url, json={"run_id": "bad", "item_id": "q1", "choice": 1}).status_code == 400
    assert not c.post(url + "&force=true").json()["cached"] and len(calls) == 2
    assert c.post(url.replace(note_id.replace("/", "%2F"), "..%2Fsecret.txt")).status_code == 400


def test_saved_lesson_generates_full_test_and_regenerates(client, monkeypatch):
    import time
    from urllib.parse import quote

    c, server = client
    with server.db_lock:
        key = server.progress.upsert_concept(server.conn, "algebra", "Network types", "1.1.2 Network Types",
                                             "Choose a network type for a situation")
        server.conn.commit()
    monkeypatch.setattr(server.notes, "summarize", lambda *a, **kw: {"summary": "done"})
    calls = []

    def fake_response(_settings, prompt, task, **_kwargs):
        assert task == "practice" and "Write 12-15 DISTINCT questions" in prompt
        calls.append(prompt)
        return json.dumps({"quiz": [{"concept_key": key, "question": f"Scenario {len(calls)}-{i}",
                                    "options": ["Best fit", "Near miss", "Wrong scale", "Wrong purpose"],
                                    "correct_index": 0,
                                    "explanation": "Best fit meets the requirements; the others do not."}
                                   for i in range(12)]}), {"input_tokens": 100, "output_tokens": 200}

    monkeypatch.setattr(server.brain, "response_text", fake_response)
    c.post("/api/ui/state", json={"course": "algebra"})
    c.post("/api/page", headers={"X-Study-Buddy": "1"}, json={"url": "https://example.test/1.1.2",
           "title": "1.1.2 Network Types", "text": "A network type fits a particular reach and purpose. " * 16})
    saved = c.post("/api/page/save", json={}).json()["saved"].split("/", 1)[1]
    rows = []
    for _ in range(50):
        rows = c.get("/api/courses/algebra/tests").json()
        if rows and rows[0]["ready"]:
            break
        time.sleep(0.02)
    assert rows[0]["ready"] and rows[0]["questions"] == 12 and len(calls) == 1
    url = f"/api/courses/algebra/note/test?id={quote(saved, safe='')}"
    first = c.post(url).json()
    assert first["cached"] and len(first["quiz"]) == 12 and len(calls) == 1
    assert "correct_index" not in first["quiz"][0]
    with server.db_lock:
        run = json.loads(server.conn.execute("SELECT content FROM practice_runs WHERE id=?", (first["run_id"],)).fetchone()[0])
    assert set(q["correct_index"] for q in run["quiz"]) == {0, 1, 2, 3}
    item = run["quiz"][0]
    answer_url = f"/api/courses/algebra/note/practice/answer?id={quote(saved, safe='')}"
    result = c.post(answer_url, json={"run_id": first["run_id"], "item_id": item["id"],
                                       "choice": item["correct_index"]}).json()
    assert result["outcome"] == "got_it"
    assert next(x for x in c.get("/api/courses/algebra/progress").json()["concepts"] if x["name"] == "Network types")["attempts"] == 1
    second = c.post(url + "&force=true").json()
    assert not second["cached"] and len(calls) == 2 and second["quiz"][0]["question"].startswith("Scenario 2-")


def test_new_lesson_extends_concept_map_before_test(client, monkeypatch):
    import time

    c, server = client
    monkeypatch.setattr(server.notes, "summarize", lambda *a, **kw: {"summary": "done"})
    seen = []

    def fake_response(_settings, prompt, task, **_kwargs):
        seen.append(task)
        if task == "concept_map":
            return json.dumps({"concepts": [
                {"name": name, "objective": "Select the right design for a scenario"}
                for name in ("Bus topology", "Star topology", "Mesh topology")]}), {"input_tokens": 50, "output_tokens": 60}
        assert task == "practice" and "star topology" in prompt.lower()
        key = server.progress.key_of("Star topology")
        return json.dumps({"quiz": [{"concept_key": key, "question": f"Topology scenario {i}",
                                    "options": ["Star", "Bus", "Mesh", "Ring"], "correct_index": 0,
                                    "explanation": "The star arrangement fits this situation."}
                                   for i in range(10)]}), {"input_tokens": 80, "output_tokens": 100}

    monkeypatch.setattr(server.brain, "response_text", fake_response)
    c.post("/api/ui/state", json={"course": "algebra"})
    c.post("/api/page", headers={"X-Study-Buddy": "1"}, json={"url": "https://example.test/1.1.3",
           "title": "1.1.3 Network Topology", "text": "Star, bus, and mesh topologies arrange network links in different ways. " * 14})
    c.post("/api/page/save", json={})
    rows = []
    for _ in range(50):
        rows = c.get("/api/courses/algebra/tests").json()
        if rows and rows[0]["ready"]:
            break
        time.sleep(0.02)
    assert rows[0]["ready"] and rows[0]["questions"] == 10 and seen == ["concept_map", "practice"]
    mapped = c.get("/api/courses/algebra/progress").json()["concepts"]
    assert {x["name"] for x in mapped} >= {"Star topology", "Bus topology", "Mesh topology"}
    assert all(x["unit"] == "1.1.3 Network Topology" for x in mapped)


def test_live_session_brokering(client, monkeypatch):
    c, server = client
    seen = {}

    def fake_create(s, sdp, cfg):
        seen.update(sdp=sdp, cfg=cfg)
        return {"session": {"id": "live_1"}, "transport": {"type": "webrtc", "sdp": "ANSWER"}}

    monkeypatch.setattr(server.brain, "create_live_session", fake_create)
    r = c.post("/api/live/session", json={"sdp": "OFFER", "course": "algebra", "mode": "walkthrough"}).json()
    assert r["sdp"] == "ANSWER" and r["session_id"] == "live_1" and r["chat_id"]
    brain_instr = seen["cfg"]["delegation"]["responses"]["instructions"]
    assert "College Algebra" in brain_instr and "Problem walkthrough" in brain_instr and "architect" not in brain_instr
    assert "sk-test" not in str(r) and r["sid"]
    # resume: previous transcript gets folded into the brain instructions
    c.post(f"/api/sessions/{r['sid']}/close", json={"measured_seconds": 60, "transcript": [{"role": "you", "text": "explain the discriminant"}]})
    r2 = c.post("/api/live/session", json={"sdp": "OFFER", "course": "algebra", "resume_sid": r["sid"]}).json()
    assert r2["resumed"] and "explain the discriminant" in seen["cfg"]["delegation"]["responses"]["instructions"]
    # budget: once spent >= budget, premium voice is refused
    server.settings.monthly_budget = 0.01
    assert c.post("/api/live/session", json={"sdp": "OFFER", "course": "algebra"}).status_code == 402
    server.settings.monthly_budget = 25


def test_openai_error_surfaces(client, monkeypatch):
    c, server = client

    def boom(*a, **k):
        raise server.brain.OpenAIError("/live/sessions -> 403: nope")

    monkeypatch.setattr(server.brain, "create_live_session", boom)
    r = c.post("/api/live/session", json={"sdp": "x", "course": "algebra"})
    assert r.status_code == 502 and "403" in r.json()["detail"]


def test_vision_endpoint_tracks_cost(client, monkeypatch):
    c, server = client
    monkeypatch.setattr(server.brain, "describe_screen", lambda s, img, q, kind="screen": ("AWS console, EC2 launch wizard", 0.00015))
    sid = c.post("/api/sessions/start", json={"course": "algebra"}).json()["sid"]
    r = c.post("/api/vision/describe", json={"image": "data:image/jpeg;base64,AA", "question": "what step?", "sid": sid}).json()
    assert r["description"].startswith("AWS console")
    rec = c.post(f"/api/sessions/{sid}/close", json={}).json()
    assert rec["vision_calls"] == 1 and rec["vision_cost"] > 0


def test_course_sections_and_chat_history(tmp_path, monkeypatch):
    import shutil
    courses = tmp_path / "courses"
    shutil.copytree("courses", courses)
    monkeypatch.setenv("COURSES_DIR", str(courses)); monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    import studybuddy.config, studybuddy.server
    importlib.reload(studybuddy.config); server = importlib.reload(studybuddy.server)
    with TestClient(server.app) as c:
        cs = c.get("/api/courses").json()
        assert [x["slug"] for x in cs] == ["cng20421-cloud-computing", "cng10241-network-plus",
                                           "cng10321-security-plus", "cis20231-linux"]  # hidden aws folder excluded
        assert cs[1]["code"] == "CNG10241H3" and cs[1]["instructor"] == "Joel Ramirez"
        slug = "cis20231-linux"
        st = c.post("/api/sessions/start", json={"course": slug, "mode": "quiz", "channel": "text"}).json()
        c.post(f"/api/sessions/{st['sid']}/close", json={"transcript": [
            {"role": "you", "text": "what does chmod 755 do"}, {"role": "tutor", "text": "What do you think 7 means?"}]})
        chats = c.get(f"/api/courses/{slug}/sessions").json()
        assert chats[0]["title"] == "what does chmod 755 do" and chats[0]["turns"] == 2
        assert c.get("/api/courses/cng10241-network-plus/sessions").json() == []   # per-course
        t = c.get(f"/api/sessions/{st['sid']}/transcript").json()
        assert t["course"] == slug and t["transcript"][1]["role"] == "tutor"
        r = c.post("/api/sessions/start", json={"course": slug, "mode": "quiz", "resume_sid": st["sid"]}).json()
        assert r["resumed"] and "chmod 755" in server.chats[r["chat_id"]].instructions
        assert "CIS20231N2" in server.chats[r["chat_id"]].instructions


def test_page_sync_endpoints(client):
    c, server = client
    body = {"url": "https://testout.example/1.1.1", "title": "1.1.1 Networking Concepts", "text": "Networking lets devices share resources. " * 20}
    assert c.post("/api/page", json=body).status_code == 403                 # no header -> rejected (web pages can't inject)
    r = c.post("/api/page", json=body, headers={"X-Study-Buddy": "1"}).json()
    assert r["active"] and r["title"].startswith("1.1.1")
    assert c.get("/api/page").json()["chars"] == r["chars"]
    assert c.post("/api/page/save", json={}).status_code == 400              # no course open yet
    c.post("/api/ui/state", json={"course": "algebra"})
    saved = c.post("/api/page/save", json={}).json()["saved"]
    assert saved.startswith("algebra/material/pages/")
    hits = c.post("/api/tools/algebra/search_material", json={"query": "devices share resources"}).json()["output"]
    assert "pages/" in hits                                                   # saved page is now searchable notes
    out = c.post("/api/tools/algebra/read_page", json={}).json()["output"]
    assert "share resources" in out
    assert c.delete("/api/page", headers={"X-Study-Buddy": "1"}).json() == {"active": False}


def test_lab_activity_syncs_without_creating_lesson_notes(client, monkeypatch):
    c, server = client
    jobs = []
    monkeypatch.setattr(server, "_summarize_quietly", lambda *args: jobs.append(args))
    c.post("/api/ui/state", json={"course": "algebra"})
    lab = {"url": "https://example.test/units/1.1.8", "title": "Learning Platform | CompTIA",
           "section": "1.1.8", "section_title": "Lab: Create Network Topologies",
           "text": "Arrange the network devices and connect the links. " * 20, "save": True}
    result = c.post("/api/page", json=lab, headers={"X-Study-Buddy": "1"}).json()
    assert result["activity"] and result["saved"] is None and result["active"]
    assert c.get("/api/page").json()["note_id"] is None
    assert c.post("/api/page/save", json={}).json() == {"saved": None, "skipped": "lab_activity"}
    assert not jobs and not list((server.settings.courses_dir / "algebra" / "material" / "pages").glob("*.md"))

    generic_lab = {"url": "https://example.test/productviewer/opaque-id", "title": "Learning Platform | CompTIA",
                   "text": "Exam Objectives Covered\n\n## Activity: Connect Devices\n\n" + "Arrange the devices. " * 30}
    generic = c.post("/api/page", json=generic_lab, headers={"X-Study-Buddy": "1"}).json()
    assert generic["activity"] and c.post("/api/page/save", json={}).json()["saved"] is None

    # A previously saved lab is hidden from both lesson and test lists after an update.
    legacy = server.settings.courses_dir / "algebra" / "material" / "pages" / "1-1-8-lab.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# 1.1.8 Lab: Create Network Topologies\n\nSource: https://example.test/units/1.1.8\n\nLab steps")
    (legacy.parent / "generic-activity.md").write_text(
        "# Learning Platform | CompTIA\n\nSource: https://example.test/opaque\n\n## Activity: Connect Devices\n\nLab steps")
    c.post("/api/courses/algebra/index")
    assert all(n["kind"] != "page" for n in c.get("/api/courses/algebra/notes").json())
    assert c.get("/api/courses/algebra/tests").json() == []

    lesson = {"url": "https://example.test/units/1.1.9", "title": "1.1.9 Network Security",
              "text": "The lesson explains lab safety and secure network designs. " * 20 +
                      "\n\n## Activity: optional review exercise\n\nApply the ideas."}
    normal = c.post("/api/page", json=lesson, headers={"X-Study-Buddy": "1"}).json()
    assert not normal["activity"]
    assert c.post("/api/page/save", json={}).json()["saved"].endswith("1-1-9-network-security.md")


def test_notes_summaries_guide_recap(client, monkeypatch):
    c, server = client
    calls = []

    def fake_post(s, path, body, timeout=0):
        calls.append(body)
        prompt = body["input"] if isinstance(body["input"], str) else ""
        if "wants the short version" in prompt:
            text = "## The big picture\nSwitches keep traffic local.\n## Section by section\n### Overview\nThink of a switch like a mail sorter.\n## Key terms\n| Term | In plain words |\n|---|---|\n| MAC | hardware address |"
        elif "Respond with ONLY JSON" in prompt:
            text = json.dumps({"title": "Switches vs routers", "covered": ["switching"], "key_terms": [{"term": "MAC", "plain": "hardware address"}],
                               "clicked": ["mail sorter"], "weak_spots": [{"issue": "mixed up hub and switch", "fix": "hub repeats, switch learns"}],
                               "quick_checks": [{"q": "What does a switch use?", "a": "MAC addresses"}], "next_up": "Routing"})
        else:
            text = "# College Algebra — study guide\n## Where you stand\nSolid on switching."
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 1000, "output_tokens": 200}}

    monkeypatch.setattr(server.brain, "_post", fake_post)
    monkeypatch.setattr(server.brain, "_post_flex", fake_post)
    c.post("/api/ui/state", json={"course": "algebra"})
    c.post("/api/page", headers={"X-Study-Buddy": "1"}, json={"url": "https://t/1.2.1", "title": "1.2.1 Switches",
            "text": "A switch forwards frames using MAC addresses and learns which port each device is on. " * 10})
    c.post("/api/page/save", json={})
    import time; time.sleep(0.5)                                      # auto-summary runs in the background
    ns = c.get("/api/courses/algebra/notes").json()
    page_note = next(n for n in ns if n["kind"] == "page")
    assert page_note["section"] == "1.2.1" and page_note["summary"].startswith("## The big picture")
    assert c.get("/api/page").json()["note_id"] == page_note["id"]    # "now reading" knows it's saved
    assert ns[0]["id"] == page_note["id"]                              # sectioned pages sort first
    # re-summarize unchanged text -> cached, no new call
    n_calls = len(calls)
    assert c.post(f"/api/courses/algebra/note/summarize?id={page_note['id']}").json()["cached"]
    assert len(calls) == n_calls
    # my notes
    c.put(f"/api/courses/algebra/note/mine?id={page_note['id']}", json={"text": "switch = smart mail sorter"})
    assert next(n for n in c.get("/api/courses/algebra/notes").json() if n["id"] == page_note["id"])["my_notes"] == "switch = smart mail sorter"
    assert "forwards frames" in c.get(f"/api/courses/algebra/note?id={page_note['id']}").json()["text"]
    assert c.get("/api/courses/algebra/note?id=../../../etc/passwd").status_code == 400
    # chat recap + boards
    sid = c.post("/api/sessions/start", json={"course": "algebra", "mode": "guided"}).json()["sid"]
    tr = [{"role": "you", "text": "what's the difference between a hub and a switch?"}, {"role": "tutor", "text": "A hub repeats; a switch learns MAC addresses."}]
    rc = c.post(f"/api/sessions/{sid}/recap", json={"transcript": tr,
        "boards": [{"title": "Hub vs switch", "markdown": "A switch learns MAC addresses."}]}).json()
    assert rc["title"] == "Switches vs routers" and rc["weak_spots"][0]["fix"].startswith("hub repeats")
    assert "Board: Hub vs switch" in calls[-1]["input"]
    c.post(f"/api/sessions/{sid}/close", json={"transcript": tr, "boards": [{"title": "Hub vs switch", "markdown": "A switch learns MAC addresses."}]})
    t = c.get(f"/api/sessions/{sid}/transcript").json()
    assert t["boards"][0]["title"] == "Hub vs switch" and t["recap"]["title"] == "Switches vs routers"
    assert c.post(f"/api/sessions/{sid}/recap", json={}).status_code == 200
    assert "A switch learns MAC addresses." in calls[-1]["input"]
    assert c.get("/api/courses/algebra/sessions").json()[0]["title"] == "Switches vs routers"
    # study guide uses notes + my notes + recaps
    g = c.post("/api/courses/algebra/guide").json()
    assert g["markdown"].startswith("# College Algebra") and c.get("/api/courses/algebra/guide").json()["markdown"]
    guide_prompt = calls[-1]["input"]
    assert "switch = smart mail sorter" in guide_prompt and "mixed up hub and switch" in guide_prompt
    # background AI work counts toward monthly spend
    assert c.get("/api/spend").json()["month"]["spent"] > 0



def test_breakdown_covers_every_section(client, monkeypatch):
    c, server = client
    prompts = []

    def fake_post(s, path, body, timeout=0):
        prompts.append(body["input"])
        if "skipped these lesson sections" in body["input"]:
            text = "### Appliances, Applications, and Functions\nAppliances are purpose-built boxes like switches and firewalls."
        else:  # first pass forgets the last section
            text = ("## The big picture\nWhat networks are.\n## Section by section\n### Overview\nNodes and links.\n"
                    "### Client-Server vs. Peer-to-Peer Networks\n| | Client-server | Peer-to-peer |\n\n## Key terms\n| Term | In plain words |")
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 3000, "output_tokens": 900}}

    monkeypatch.setattr(server.brain, "_post", fake_post)
    lesson = ("A network is two or more computer systems linked by a transmission medium. " * 3 +
              "\n\n## Client-Server vs. Peer-to-Peer Networks\n\n" + "A server makes resources available. A client consumes them. " * 2 +
              "\n\n## Appliances, Applications, and Functions\n\n- Appliances: switches, routers, firewalls.\n- Applications: services like email.")
    c.post("/api/ui/state", json={"course": "algebra"})
    r = c.post("/api/page", headers={"X-Study-Buddy": "1"}, json={"url": "https://lab.example/pv/1.1.1/abc?nonce=111",
            "title": "Learning Platform | CompTIA", "section": "1.1.1", "section_title": "Networking Concepts", "text": lesson}).json()
    assert r["title"] == "1.1.1 Networking Concepts"
    assert r["headings"] == ["Client-Server vs. Peer-to-Peer Networks", "Appliances, Applications, and Functions"]
    saved = c.post("/api/page/save", json={}).json()["saved"]
    assert saved == "algebra/material/pages/1-1-1-networking-concepts.md"
    note_id = saved.split("/", 1)[1]
    out = c.post(f"/api/courses/algebra/note/summarize?id={note_id}&force=true&full=true").json()
    assert out["missing"] == [] and "### Appliances, Applications, and Functions" in out["summary"]
    assert out["summary"].index("Appliances, Applications") < out["summary"].index("## Key terms")   # repaired in place
    full_prompt = next(p for p in prompts if "## Section by section" in p)                             # (saving also queues a short one)
    assert "- Appliances, Applications, and Functions" in full_prompt                                   # outline was given


def test_resave_replaces_old_copy_and_keeps_my_notes(client, monkeypatch):
    c, server = client
    monkeypatch.setattr(server, "_summarize_quietly", lambda *a: None)
    c.post("/api/ui/state", json={"course": "algebra"})
    body = {"url": "https://lab.example/pv/1.1.1/abc?nonce=AAA", "title": "Learning Platform | CompTIA", "text": "Old partial lesson text. " * 20}
    c.post("/api/page", headers={"X-Study-Buddy": "1"}, json=body)
    old = c.post("/api/page/save", json={}).json()["saved"].split("/", 1)[1]
    c.put(f"/api/courses/algebra/note/mine?id={old}", json={"text": "my mnemonic"})
    body.update(url="https://lab.example/pv/1.1.1/abc?nonce=BBB", section="1.1.1", section_title="Networking Concepts",
                text="Full lesson now. " * 40)
    c.post("/api/page", headers={"X-Study-Buddy": "1"}, json=body)
    new = c.post("/api/page/save", json={}).json()["saved"].split("/", 1)[1]
    ns = c.get("/api/courses/algebra/notes").json()
    pages = [n for n in ns if n["kind"] == "page"]
    assert [n["id"] for n in pages] == [new] and pages[0]["my_notes"] == "my mnemonic" and new != old


def test_delete_chat(client):
    c, server = client
    st = c.post("/api/sessions/start", json={"course": "algebra", "mode": "quiz", "channel": "text"}).json()
    c.post(f"/api/sessions/{st['sid']}/close", json={"transcript": [{"role": "you", "text": "delete me"}]})
    assert any(x["id"] == st["sid"] for x in c.get("/api/courses/algebra/sessions").json())
    assert c.delete(f"/api/sessions/{st['sid']}").status_code == 403          # header required
    assert c.delete(f"/api/sessions/{st['sid']}", headers={"X-Study-Buddy": "1"}).json() == {"ok": True}
    assert not any(x["id"] == st["sid"] for x in c.get("/api/courses/algebra/sessions").json())
    assert not (server.settings.data_dir / "sessions" / f"{st['sid']}.json").exists()
    assert c.delete("/api/sessions/nope", headers={"X-Study-Buddy": "1"}).status_code == 404


def test_delete_saved_lesson_and_add_it_again(client, monkeypatch):
    c, server = client
    monkeypatch.setattr(server, "_summarize_quietly", lambda *a: None)
    c.post("/api/ui/state", json={"course": "algebra"})
    body = {"url": "https://lesson.example/1.1.1", "title": "1.1.1 Networking Concepts",
            "section": "1.1.1", "section_title": "Networking Concepts", "text": "A client connects to a server. " * 40}
    assert c.post("/api/page", headers={"X-Study-Buddy": "1"}, json=body).status_code == 200
    lesson_id = c.post("/api/page/save", json={}).json()["saved"].split("/", 1)[1]
    c.put(f"/api/courses/algebra/note/mine?id={lesson_id}", json={"text": "Remember this"})
    with server.db_lock:
        cur = server.conn.execute("INSERT INTO practice_sets(course, note_id, fingerprint, content) VALUES (?,?,?,?)",
                                  ("algebra", lesson_id, "test", "{}"))
        server.conn.execute("INSERT INTO practice_runs(id, set_id, course, note_id) VALUES (?,?,?,?)",
                            ("run-test", cur.lastrowid, "algebra", lesson_id))
        server.conn.execute("INSERT INTO practice_answers(run_id, item_id, outcome, mastery) VALUES (?,?,?,?)",
                            ("run-test", "question", "got_it", 1))
        server.conn.commit()
    url = f"/api/courses/algebra/note?id={lesson_id}"
    assert c.delete(url).status_code == 403
    assert c.delete("/api/courses/algebra/note?id=material/syllabus.txt", headers={"X-Study-Buddy": "1"}).status_code == 400
    assert c.delete(url, headers={"X-Study-Buddy": "1"}).json() == {"ok": True}
    assert not (server.settings.courses_dir / "algebra" / lesson_id).exists()
    assert not any(n["id"] == lesson_id for n in c.get("/api/courses/algebra/notes").json())
    with server.db_lock:
        for table in ("notes", "practice_sets", "practice_runs"):
            assert not server.conn.execute(f"SELECT 1 FROM {table} WHERE course=? AND {('id' if table == 'notes' else 'note_id')}=?",
                                           ("algebra", lesson_id)).fetchone()
        assert not server.conn.execute("SELECT 1 FROM practice_answers WHERE run_id='run-test'").fetchone()
    assert c.delete(url, headers={"X-Study-Buddy": "1"}).status_code == 404
    assert c.post("/api/page/save", json={}).json()["saved"].endswith(lesson_id)
    assert any(n["id"] == lesson_id for n in c.get("/api/courses/algebra/notes").json())


def test_economy_tts_audio_and_estimated_receipt(client, monkeypatch):
    c, server = client
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 24000 * 2)  # two seconds
    seen = []
    monkeypatch.setattr(server.brain, "synthesize_speech", lambda settings, text: (seen.append(text), audio.getvalue())[1])
    sid = c.post("/api/sessions/start", json={"course": "algebra", "channel": "economy"}).json()["sid"]
    assert c.post("/api/tts", json={"sid": sid, "text": "Hello, Marc."}).content == audio.getvalue()
    assert seen == ["Hello, Marc."]
    assert c.post("/api/tts", json={"sid": sid, "text": ""}).status_code == 400
    assert c.post("/api/tts", json={"sid": "missing", "text": "Hello"}).status_code == 404
    receipt = c.post(f"/api/sessions/{sid}/close", json={}).json()
    assert receipt["tts_seconds"] == 2
    assert receipt["tts_cost"] == pytest.approx(2 / 60 * server.settings.price_tts_est_per_min)
    assert receipt["cost_total"] == pytest.approx(receipt["tts_cost"], abs=1e-5)
    assert c.post("/api/tts", json={"sid": sid, "text": "again"}).status_code == 404


def test_short_breakdown_is_default_and_trimmed_when_long(client, monkeypatch):
    c, server = client
    prompts = []

    def fake_post(s, path, body, timeout=0):
        prompts.append(body["input"])
        if "too long: cut it" in body["input"]:
            text = "**The one big idea:** Switches learn MAC addresses.\n\n**Traps:**\n1. Hubs repeat; switches learn."
        else:  # first draft blows the word budget
            text = "**The one big idea:** " + "Switches forward frames by MAC address. " * 80
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 500, "output_tokens": 300}}

    monkeypatch.setattr(server.brain, "_post", fake_post)
    monkeypatch.setattr(server, "_summarize_quietly", lambda *a: None)
    c.post("/api/ui/state", json={"course": "algebra"})
    c.post("/api/page", headers={"X-Study-Buddy": "1"}, json={"url": "https://t/1.2.1", "title": "1.2.1 Switches",
            "text": "A switch forwards frames using MAC addresses and learns which port each device is on. " * 10})
    note_id = c.post("/api/page/save", json={}).json()["saved"].split("/", 1)[1]
    out = c.post(f"/api/courses/algebra/note/summarize?id={note_id}").json()
    assert len(prompts) == 2 and "wants the short version" in prompts[0] and "LAN (Local)" in prompts[0]  # one-shot example
    assert "A switch forwards frames" not in prompts[1]                        # trim pass sends only the draft
    assert out["summary"].startswith("**The one big idea:** Switches learn") and out["words"] <= server.notes.MAX_WORDS
    assert c.post(f"/api/courses/algebra/note/summarize?id={note_id}").json()["cached"]
    note = next(n for n in c.get("/api/courses/algebra/notes").json() if n["id"] == note_id)
    assert note["summary"] == out["summary"] and note["has_full"] is False
