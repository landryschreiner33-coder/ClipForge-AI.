"""The script (studio/script.py): reading .txt/.md/.docx/.pdf/.fdx files and pasted text into lines, the words
both sides are compared on, matching lines to the transcribed words (takes, the best take, exclusivity, clips,
what is unused), the report in words, and the speed bound. Pure functions: no database, no app."""
from __future__ import annotations

import io
import random
import time

import pytest

from clipfoundry.studio import script
from clipfoundry.studio.script import ScriptError, match, normalize, parse, report, take_quality


def _say(start: float, text: str, step: float = 0.4, p: float | None = None) -> list[dict]:
    """Timed words, one every `step` seconds from `start`, each 0.3 s long."""
    out = []
    for k, w in enumerate(text.split()):
        word = {"start": round(start + k * step, 3), "end": round(start + k * step + 0.3, 3), "w": w}
        if p is not None:
            word["p"] = p
        out.append(word)
    return out


def _after(words: list[dict], gap: float, text: str, step: float = 0.4, p: float | None = None) -> list[dict]:
    """More words starting `gap` seconds after the last one."""
    return words + _say(round(words[-1]["end"] + gap, 3), text, step, p)


def _lines(text: str) -> list[dict]:
    return parse("script.txt", text)["lines"]


def _pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF whose content stream prints `lines` one under the other (pypdf reads it back)."""
    ops = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
    for i, line in enumerate(lines):
        shown = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({shown}) Tj" if i == 0 else f"T* ({shown}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
             b"/Resources << /Font << /F1 5 0 R >> >> >>"),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


FDX = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<FinalDraft DocumentType="Script" Template="No" Version="5">
<Content>
<Paragraph Type="Scene Heading"><Text>INT. KITCHEN - DAY</Text></Paragraph>
<Paragraph Type="Action"><Text>John pours coffee.</Text></Paragraph>
<Paragraph Type="Character"><Text>JOHN</Text></Paragraph>
<Paragraph Type="Parenthetical"><Text>(tired)</Text></Paragraph>
<Paragraph Type="Dialogue"><Text>Morning. </Text><Text Style="Italic">Did you sleep?</Text></Paragraph>
<Paragraph Type="Transition"><Text>CUT TO:</Text></Paragraph>
<Paragraph Type="Character"><Text>MARY (V.O.)</Text></Paragraph>
<Paragraph Type="Dialogue"><Text>Not really, no.</Text></Paragraph>
<Paragraph Type="General"><Text>A note nobody says.</Text></Paragraph>
</Content>
</FinalDraft>
"""


# ------------------------------------------------------------------ reading
def test_text_headings_directions_speakers_and_sections():
    p = parse("notes.txt", "# Welcome\n\nINTRO:\nHOST: Hey everyone, welcome back to the channel.\n"
                           "[B-roll of the lake]\nB-ROLL: drone shot\nCUT TO the kitchen\n(a long pause here)\n"
                           "Part 2: the hike\nINT. KITCHEN - DAY\nSCENE 3\nWe hiked to the top and it was worth it.\n"
                           "MARY (V.O.): Was it, though?\n")
    kinds = [(ln["kind"], ln["text"]) for ln in p["lines"]]
    assert kinds == [("heading", "Welcome"), ("heading", "INTRO"),
                     ("line", "Hey everyone, welcome back to the channel."),
                     ("direction", "B-roll of the lake"), ("direction", "B-ROLL: drone shot"),
                     ("direction", "CUT TO the kitchen"), ("direction", "a long pause here"),
                     ("heading", "Part 2: the hike"), ("heading", "INT. KITCHEN - DAY"), ("heading", "SCENE 3"),
                     ("line", "We hiked to the top and it was worth it."), ("line", "Was it, though?")]
    assert [ln["n"] for ln in p["lines"]] == list(range(1, 13))
    assert p["lines"][2]["speaker"] == "Host" and p["lines"][11]["speaker"] == "Mary"
    assert p["lines"][10]["speaker"] == ""
    assert [ln["section"] for ln in p["lines"]][:4] == ["Welcome", "INTRO", "INTRO", "INTRO"]
    assert p["lines"][10]["section"] == "SCENE 3"
    assert p["lines"][2]["tokens"] == ["hey", "everyone", "welcome", "back", "to", "the", "channel"]
    assert p["lines"][0]["tokens"] == ["welcome"]  # headings carry their tokens too
    assert p["format"] == "txt" and p["filename"] == "notes.txt"
    assert p["counts"] == {"lines": 3, "headings": 5, "directions": 4, "words": 20}
    assert p["text"].startswith("# Welcome")


def test_long_paragraph_is_split_into_sentences_but_not_at_abbreviations():
    long = ("Dr. Smith said the lake was cold, e.g. in May. We went anyway because J. K. told us to go and "
            "we are glad we did, honestly! Was it worth it? Yes it was, and we would do it again tomorrow.")
    lines = _lines(long)
    assert [ln["text"] for ln in lines] == [
        "Dr. Smith said the lake was cold, e.g. in May.",
        "We went anyway because J. K. told us to go and we are glad we did, honestly!",
        "Was it worth it?",
        "Yes it was, and we would do it again tomorrow."]
    short = "We went to the lake. It was cold. We swam anyway."
    assert [ln["text"] for ln in _lines(short)] == [short]  # 30 words or fewer stay one line


def test_list_prefixes_and_markdown_dressing_are_stripped():
    p = parse("plan.md", b"1. First we drive **to the lake**.\n12) Then we swim.\n- Then we eat.\n"
                         b"\xe2\x80\xa2 Then [we sleep](https://example.com/sleep).\n> Then we go home.\n---\n")
    assert [ln["text"] for ln in p["lines"]] == ["First we drive to the lake.", "Then we swim.", "Then we eat.",
                                                 "Then we sleep.", "Then we go home."]
    assert p["format"] == "md"


def test_inline_parentheticals_and_bracketed_notes_are_removed_from_lines():
    lines = _lines("Welcome back to the channel (waves) everyone.\nI love it (beat) and you will too (laughs).\n"
                   "The API (the part the apps talk to every day) is simple [B-roll: laptop].")
    assert [ln["text"] for ln in lines] == [
        "Welcome back to the channel everyone.",
        "I love it and you will too.",
        "The API (the part the apps talk to every day) is simple."]  # five words or more are said
    assert all(ln["kind"] == "line" for ln in lines)


def test_docx_paragraphs_in_order_with_table_cells():
    import docx

    d = docx.Document()
    d.add_paragraph("# Intro")
    d.add_paragraph("Hey everyone, welcome back.")
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Scene 2"
    table.rows[0].cells[1].text = "We drove to the lake and it was cold."
    d.add_paragraph("Bye for now, everyone.")
    buf = io.BytesIO()
    d.save(buf)
    p = parse("Script.DOCX", buf.getvalue())
    assert p["format"] == "docx"
    assert [(ln["kind"], ln["text"]) for ln in p["lines"]] == [
        ("heading", "Intro"), ("line", "Hey everyone, welcome back."), ("heading", "Scene 2"),
        ("line", "We drove to the lake and it was cold."), ("line", "Bye for now, everyone.")]
    assert p["lines"][3]["section"] == "Scene 2"
    with pytest.raises(ScriptError, match="Word file could not be read"):
        parse("broken.docx", b"not a zip at all")


def test_pdf_text_with_mended_hyphens_and_joined_wrapped_lines():
    p = parse("script.pdf", _pdf(["INTRO", "Hello there.", "This is a hyphen-", "ated word here.",
                                  "This line does not end", "with punctuation. Next one.", "Bye now."]))
    assert p["format"] == "pdf"
    assert [(ln["kind"], ln["text"]) for ln in p["lines"]] == [
        ("heading", "INTRO"), ("line", "Hello there."), ("line", "This is a hyphenated word here."),
        ("line", "This line does not end with punctuation. Next one."), ("line", "Bye now.")]
    with pytest.raises(ScriptError, match="PDF could not be read"):
        parse("broken.pdf", b"%PDF-1.4 but nothing else")


def test_fdx_scene_headings_actions_characters_and_dialogue():
    p = parse("film.fdx", FDX.encode("utf-8"))
    assert p["format"] == "fdx"
    assert [(ln["kind"], ln["text"], ln["speaker"]) for ln in p["lines"]] == [
        ("heading", "INT. KITCHEN - DAY", ""), ("direction", "John pours coffee.", ""),
        ("direction", "tired", ""), ("line", "Morning. Did you sleep?", "John"),
        ("line", "Not really, no.", "Mary")]
    assert p["counts"] == {"lines": 2, "headings": 1, "directions": 2, "words": 7}
    # the text kept for the Script panel reads back into the same lines
    again = parse("film.txt", p["text"])
    assert [(ln["kind"], ln["text"], ln["speaker"]) for ln in again["lines"]] == \
        [(ln["kind"], ln["text"], ln["speaker"]) for ln in p["lines"]]
    with pytest.raises(ScriptError, match="Final Draft file could not be read"):
        parse("film.fdx", b"<FinalDraft><Content>")


def test_encodings_limits_empty_and_unknown_formats():
    assert _lines("Héllo there, friend.")[0]["text"] == "Héllo there, friend."
    assert parse("s.txt", "Héllo there, friend.".encode("utf-16"))["lines"][0]["text"] == "Héllo there, friend."
    assert parse("s.txt", b"\xef\xbb\xbfHello there, friend.")["lines"][0]["text"] == "Hello there, friend."
    assert parse("s.txt", b"Hello\r\nthere, friend.")["text"] == "Hello\nthere, friend."
    with pytest.raises(ScriptError, match="limit is 5 MB"):
        parse("big.txt", b"a" * (script.MAX_BYTES + 1))
    with pytest.raises(ScriptError, match="longer than 200,000 characters"):
        parse("long.txt", "word " * 50_000)
    with pytest.raises(ScriptError, match="more than 2,000 lines"):
        parse("many.txt", "\n".join(f"Line number {i} is here." for i in range(script.MAX_LINES + 1)))
    with pytest.raises(ScriptError, match="no text"):
        parse("empty.txt", "---\n\n   \n***\n")
    with pytest.raises(ScriptError, match=r"\.txt, \.md, \.docx, \.pdf or \.fdx"):
        parse("script.exe", b"Hello there.")
    with pytest.raises(ScriptError, match="no text in it"):
        parse("scan.pdf", _pdf([" "]))
    assert script.SUPPORTED == (".txt", ".text", ".md", ".markdown", ".docx", ".pdf", ".fdx")


def test_normalize_numbers_apostrophes_stems_and_fillers():
    assert normalize("I'm sure we don't") == ["im", "sure", "we", "dont"]
    assert normalize("In 2024 we had 3.5 million, 50% of it, $20 and $1 by 10:30") == [
        "in", "two", "thousand", "twenty", "four", "we", "had", "three", "point", "five", "million", "fifty",
        "percent", "of", "it", "twenty", "dollars", "and", "one", "dollar", "by", "ten", "thirty"]
    assert normalize("1,000 people, the 1st, 2nd, 3rd and 21st time, 20th") == [
        "one", "thousand", "people", "the", "first", "second", "third", "and", "twenty", "first", "time",
        "twentieth"]
    assert normalize("walking walked boxes makes stories glasses goes things") == [
        "walk", "walk", "box", "make", "story", "glass", "goes", "thing"]
    assert normalize("um, uh... Erm hmm MHM ah uhm the lake") == ["the", "lake"]
    assert normalize("Hello, there! B-roll; e-mail... don't") == ["hello", "there", "b", "roll", "e", "mail", "dont"]
    assert normalize("...") == []


# ------------------------------------------------------------------ matching
def test_dropped_and_substituted_words_still_match():
    lines = _lines("The water was really cold and clear today.")
    dropped = match(lines, {"a": _say(1.0, "the water was cold and clear today")}, ["a"])
    lm = dropped["lines"][0]
    assert lm["status"] == "matched" and 0.6 <= lm["coverage"] < 1.0
    assert lm["take"]["said"] == "the water was cold and clear today"
    assert (lm["take"]["i0"], lm["take"]["i1"]) == (0, 6)
    assert (lm["take"]["start"], lm["take"]["end"]) == (1.0, 3.7)
    assert lm["take"]["asset_id"] == "a" and lm["takes"] == []
    replaced = match(lines, {"a": _say(1.0, "the water was really cold and bright today")}, ["a"])
    assert replaced["lines"][0]["status"] == "matched" and 0.6 <= replaced["lines"][0]["coverage"] < 1.0
    assert dropped["stats"] == {"matched": 1, "weak": 0, "missing": 0, "skipped": 0, "alternatives": 0,
                                "off_script_words": 0, "off_script_s": 0}


def test_weak_missing_and_skipped_lines_and_directions():
    lines = _lines("Alpha bravo charlie delta echo foxtrot golf hotel india juliet.\n"
                   "Nothing of this sentence was ever said.\nBye.\n[B-roll of the lake]\n# Chapter two")
    words = _say(0.0, "alpha bravo charlie delta echo kilo lima mike november oscar papa quebec")
    result = match(lines, {"a": words}, ["a"])
    weak, missing, skipped, direction, heading = result["lines"]
    assert weak["status"] == "weak" and weak["coverage"] == 0.5 and weak["take"]["i1"] == 4
    assert missing["status"] == "missing" and missing["take"] is None and missing["takes"] == []
    assert skipped["status"] == "skipped" and skipped["take"] is None
    assert direction["status"] == "direction" and heading["status"] == "heading"
    assert result["stats"]["matched"] == 0 and result["stats"]["weak"] == 1
    assert result["stats"]["missing"] == 1 and result["stats"]["skipped"] == 1
    assert result["clips"] == [{"asset_id": "a", "i0": 0, "i1": 4, "lines": [1], "start": 0.0, "end": 1.9}]
    assert result["unused"] == {"a": [[5, 11]]}


def test_a_lone_word_far_from_the_rest_is_not_part_of_the_take():
    lines = _lines("Alpha bravo charlie delta echo foxtrot golf hotel india juliet.")
    words = _say(0.0, "alpha one two three four five bravo charlie delta echo foxtrot golf hotel india juliet")
    take = match(lines, {"a": words}, ["a"])["lines"][0]["take"]
    assert take["i0"] == 6 and take["coverage"] == 0.9 and take["said"].startswith("bravo")


def test_the_later_take_wins_when_takes_are_equal():
    lines = _lines("The water was really cold and clear.")
    words = _after(_say(1.0, "the water was really cold and clear"), 2.0, "the water was really cold and clear")
    lm = match(lines, {"a": words}, ["a"])["lines"][0]
    assert lm["status"] == "matched" and lm["take"]["i0"] == 7
    assert [t["i0"] for t in lm["takes"]] == [0]
    assert lm["takes"][0]["coverage"] == 1.0 and lm["takes"][0]["quality"] == lm["take"]["quality"]


def test_the_cleaner_take_wins_when_takes_differ():
    lines = _lines("The water was really cold and clear.")
    clean_then_fillers = _after(_say(1.0, "the water was really cold and clear"), 2.0,
                                "the water was um um really cold and clear")
    lm = match(lines, {"a": clean_then_fillers}, ["a"])["lines"][0]
    assert lm["take"]["i0"] == 0 and lm["take"]["fillers"] == 0
    assert lm["takes"][0]["i0"] == 7 and lm["takes"][0]["fillers"] == 2
    assert lm["takes"][0]["quality"] < lm["take"]["quality"]
    sure_then_unsure = _say(1.0, "the water was really cold and clear", p=0.95) + \
        _say(6.0, "the water was really cold and clear", p=0.6)
    lm = match(lines, {"a": sure_then_unsure}, ["a"])["lines"][0]
    assert lm["take"]["i0"] == 0 and lm["takes"][0]["i0"] == 7
    stumbling_then_clean = _after(_say(1.0, "the water was the water was really cold and clear"), 2.0,
                                  "the water was really cold and clear")
    lm = match(lines, {"a": stumbling_then_clean}, ["a"])["lines"][0]
    assert lm["take"]["i0"] == 10 and lm["take"]["stumbles"] == 0


def test_takes_across_two_files_follow_the_media_bin_order():
    lines = _lines("The water was really cold and clear.")
    a = _say(1.0, "the water was really cold and clear")
    b = _say(4.0, "the water was really cold and clear")
    lm = match(lines, {"a": a, "b": b}, ["a", "b"])["lines"][0]
    assert lm["take"]["asset_id"] == "b" and [t["asset_id"] for t in lm["takes"]] == ["a"]
    lm = match(lines, {"a": a, "b": b}, ["b", "a"])["lines"][0]
    assert lm["take"]["asset_id"] == "a" and [t["asset_id"] for t in lm["takes"]] == ["b"]
    assert match(lines, {"a": a}, ["b", "a", "zzz"])["lines"][0]["take"]["asset_id"] == "a"


def test_a_stretch_of_speech_is_used_by_one_line_only():
    lines = _lines("We swam until sunset.\nThen we went home.\nWe swam until sunset.")
    words = _after(_say(1.0, "we swam until sunset"), 0.2, "then we went home")
    result = match(lines, {"a": words}, ["a"])
    first, middle, again = result["lines"]
    assert first["status"] == "matched" and first["take"]["i0"] == 0
    assert middle["status"] == "matched"
    assert again["status"] == "missing" and again["take"] is None
    assert [t["i0"] for t in again["takes"]] == [0]  # the take is still shown as an alternative
    assert result["stats"]["missing"] == 1 and result["stats"]["alternatives"] == 1


def test_consecutive_lines_chain_into_one_clip_and_break_on_a_gap_or_a_heading():
    lines = _lines("We drove to the lake.\nThe water was cold.\n# The hike\nWe hiked to the top.\n"
                   "It was worth every step.")
    words = _after(_say(1.0, "we drove to the lake the water was cold we hiked to the top"), 2.0,
                   "it was worth every step")
    result = match(lines, {"a": words}, ["a"])
    assert [m["status"] for m in result["lines"]] == ["matched", "matched", "heading", "matched", "matched"]
    assert result["clips"] == [
        {"asset_id": "a", "i0": 0, "i1": 8, "lines": [1, 2], "start": 1.0, "end": 4.5},
        {"asset_id": "a", "i0": 9, "i1": 13, "lines": [4], "start": 4.6, "end": 6.5},
        {"asset_id": "a", "i0": 14, "i1": 18, "lines": [5], "start": 8.5, "end": 10.4}]
    gap = _after(_say(1.0, "we drove to the lake"), 1.4, "the water was cold")
    assert len(match(_lines("We drove to the lake.\nThe water was cold."), {"a": gap}, ["a"])["clips"]) == 1
    gap = _after(_say(1.0, "we drove to the lake"), 2.0, "the water was cold")
    assert len(match(_lines("We drove to the lake.\nThe water was cold."), {"a": gap}, ["a"])["clips"]) == 2


def test_unused_spans_are_what_was_said_outside_the_script():
    lines = _lines("We drove to the lake.\nThe water was cold.")
    words = _say(0.0, "okay so um let me check the camera")
    words = _after(words, 0.5, "we drove to the lake")
    words = _after(words, 0.3, "you know")                     # two words between takes: too short to list
    words = _after(words, 0.3, "the water was cold")
    words = _after(words, 1.0, "and that is it thanks")
    result = match(lines, {"a": words}, ["a"])
    assert result["unused"] == {"a": [[0, 7], [19, 23]]}
    assert result["stats"]["off_script_words"] == 13
    assert result["stats"]["off_script_s"] == pytest.approx((words[7]["end"] - words[0]["start"]) +
                                                            (words[23]["end"] - words[19]["start"]))
    assert match(lines, {}, [])["unused"] == {} and match(lines, {}, [])["stats"]["missing"] == 2


def test_lines_without_parse_fields_and_long_said_text():
    words = _say(0.0, " ".join(["Supercalifragilistic"] * 40))
    result = match([{"n": 1, "text": " ".join(["supercalifragilistic"] * 40)}], {"a": words}, ["a"])
    take = result["lines"][0]["take"]
    assert take["coverage"] == 1.0 and len(take["said"]) <= 300 and take["said"].endswith("…")


def test_take_quality():
    clean = _say(0.0, "the water was really cold and clear today")
    assert take_quality(clean) == 0.85                                   # no confidence: 0.85 assumed
    assert take_quality(_say(0.0, "the water was really cold and clear today", p=1.0)) == 1.0
    assert take_quality(_say(0.0, "the water was really cold and clear today", p=0.5)) == 0.5
    fillers = _say(0.0, "the water was um uh really cold and clear today")
    assert take_quality(fillers) == pytest.approx((1 - 0.25 * 2 / 10) * 0.85, abs=0.001)
    stumble = _say(0.0, "the water was the water was really cold and clear today")
    assert take_quality(stumble) == pytest.approx(0.9 * 0.85, abs=0.001)
    stumbles = _say(0.0, "the the water was was really really really cold and clear today")
    assert take_quality(stumbles) == pytest.approx(0.7 * 0.85, abs=0.001)  # four runs, capped at 0.3
    paused = _after(_say(0.0, "the water was really"), 2.0, "cold and clear today")
    span = paused[-1]["end"] - paused[0]["start"]
    assert take_quality(paused) == pytest.approx((1 - 0.15 * 2.0 / span) * 0.85, abs=0.001)
    assert take_quality([]) == 0.0
    assert 0.0 <= take_quality(_say(0.0, "um uh um uh", p=0.1)) <= 1.0


# ------------------------------------------------------------------ in words
def _result(statuses: dict[int, str], total: int, **stats) -> dict:
    lines = [{"n": n, "status": statuses.get(n, "matched")} for n in range(1, total + 1)]
    counts = {"matched": 0, "weak": 0, "missing": 0, "skipped": 0}
    for m in lines:
        counts[m["status"]] += 1
    counts.update({"alternatives": 0, "off_script_words": 0, "off_script_s": 0}, **stats)
    return {"lines": lines, "clips": [], "unused": {}, "stats": counts}


def test_report_wording():
    script_lines = [{"n": n, "kind": "line"} for n in range(1, 46)]
    result = _result({7: "missing", 20: "missing", 31: "missing", 2: "weak", 3: "weak", 4: "weak"}, 45,
                     alternatives=7, off_script_words=400, off_script_s=130.0)
    assert report(result, script_lines) == [
        "Followed your script: 42 of 45 lines were found in the footage (3 of them only partly).",
        "3 lines have no take in the footage: lines 7, 20 and 31 (see Script).",
        "Kept 7 other takes switched off after the take that plays; Use this take swaps them.",
        "Left out 2 min 10 s said in the footage that is not in the script (switched off at the end)."]
    result = _result({7: "missing", 9: "skipped"}, 10, alternatives=1, off_script_s=0.4)
    assert report(result, [{"n": n, "kind": "line"} for n in range(1, 11)]) == [
        "Followed your script: 8 of 10 lines were found in the footage.",
        "1 line has no take in the footage: line 7 (see Script).",
        "Kept 1 other take switched off after the take that plays; Use this take swaps it.",
        "Skipped 1 one-word line: too short to look for."]
    many = _result({n: "missing" for n in range(1, 11)}, 12, off_script_s=3725)
    assert report(many, [{"n": n, "kind": "line"} for n in range(1, 13)]) == [
        "Followed your script: 2 of 12 lines were found in the footage.",
        "10 lines have no take in the footage: lines 1, 2, 3, 4, 5, 6, 7, 8 and 2 more (see Script).",
        ("Most of the script was not found: check that the script and the footage are in the same language and "
         "that the right files are in the media bin."),
        "Left out 1 h 2 min said in the footage that is not in the script (switched off at the end)."]
    assert report(_result({}, 0), [{"n": 1, "kind": "heading"}]) == [
        "Your script has no spoken lines to look for in the footage (headings and directions are never said)."]


def test_report_from_a_real_match():
    lines = _lines("We drove to the lake.\nThe water was cold.\nNobody said this one.")
    words = _after(_say(0.0, "we drove to the lake the water was cold"), 0.5, "and then we went home again")
    notes = report(match(lines, {"a": words}, ["a"]), lines)
    assert notes[0] == "Followed your script: 2 of 3 lines were found in the footage."
    assert notes[1] == "1 line has no take in the footage: line 3 (see Script)."
    assert notes[2] == "Left out 2 s said in the footage that is not in the script (switched off at the end)."


# ------------------------------------------------------------------ speed
def test_300_lines_against_20000_words_match_in_under_three_seconds():
    rng = random.Random(7)
    vocab = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(4, 9)))
             for _ in range(1500)]
    weights = [1 / (i + 1) for i in range(len(vocab))]  # a few very common words, a long tail of rare ones
    texts = [" ".join(rng.choices(vocab, weights, k=rng.randint(8, 16))).capitalize() + "." for _ in range(300)]
    lines = parse("long.txt", "\n".join(texts))["lines"]
    assert len(lines) == 300
    spoken: list[str] = []
    for text in rng.sample(texts, len(texts)):
        for _ in range(rng.randint(1, 3)):
            ws = text.rstrip(".").lower().split()
            if rng.random() < 0.5:
                del ws[rng.randrange(len(ws))]  # a dropped word
            spoken += ws + rng.choices(vocab, weights, k=rng.randint(0, 3))
    while len(spoken) < 20_000:
        spoken += rng.choices(vocab, weights, k=50)
    words = _say(0.0, " ".join(spoken[:20_000]), step=0.3)
    assert len(words) == 20_000
    t0 = time.perf_counter()
    result = match(lines, {"a": words}, ["a"])
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, f"matching took {elapsed:.2f} s"
    assert result["stats"]["matched"] >= 290
    assert sum(len(c["lines"]) for c in result["clips"]) == result["stats"]["matched"] + result["stats"]["weak"]
