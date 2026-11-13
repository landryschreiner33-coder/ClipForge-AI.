"""The smarter built-in AI (docs/clipforge/SMARTER_AI.md).

The meaning model (clipfoundry/embedder.py) and the two calibrated vector spaces (pipeline/semantic.py, brain/meaning.py);
the scout that reads the whole video and the judge that ranks the finalists (pipeline/scout.py); the eyes
(pipeline/eyes.py) and the ears (pipeline/ears.py); your taste (taste.py); the meaning model and the table-of-contents
pass in story finding (pipeline/stories.py); punch-ins where the voice leans on a word (studio/smart_edit.py); the
request plumbing for JSON schemas and pictures (builtin_ai.py, pipeline/llm.py); the settings and Memory API.

Every model here is a stand-in: a tiny file server for the download, a fake ONNX Runtime session, fixed answers in
place of ClipForge AI. The real meaning model and the real vision call are checked by scripts/builtin_ai_check.py on
GitHub's runners (--meaning, --eyes); the last test below runs the real model when CLIPFORGE_MEANING_MODEL_DIR points
at a downloaded copy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from clipfoundry.pipeline import candidates, deep, llm, scout, semantic
from clipfoundry.pipeline.common import JobContext
from test_autopilot_analysis import COOKING, ENGINES, OPTS, _deep_inputs, _talk
from test_studio_smart_edit import _asset, _cut, _project, _say, _words, env  # noqa: F401 - the env fixture

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
AI_OPTS = {**OPTS, "ai_provider": "ollama", "ollama_model": "test", "ai_edit_timeout_s": 60}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


@pytest.fixture()
def client(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


# ------------------------------------------------------------------ stand-ins
class _Files(BaseHTTPRequestHandler):
    """The model hub: serves whole files and records every request."""
    files: dict[str, bytes] = {}
    requests: list[str] = []

    def log_message(self, *a):  # noqa: D401
        pass

    def do_GET(self):  # noqa: N802
        type(self).requests.append(self.path)
        data = self.files.get(self.path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


VOCAB = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "the", "cat", "sat", "on", "mat", "##s", "a", "kitten", "rest", "##ed",
         "rug", ",", ".", "!", "un", "##believ", "##able", "2", "##0", "cafe", "我", "们", "fish", "dog", "ran", "far",
         "away", "home", "tax", "return", "due", "quarter", "##ly"]


@pytest.fixture()
def hub(monkeypatch, data):
    """A tiny model hub: a small random "model" and a small vocabulary, with their real checksums pinned."""
    from clipfoundry import embedder

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    model = os.urandom(20_000)
    vocab = ("\n".join(VOCAB) + "\n").encode("utf-8")
    files = {"model.onnx": ("onnx/model.onnx", len(model), hashlib.sha256(model).hexdigest()),
             "vocab.txt": ("vocab.txt", len(vocab), hashlib.sha256(vocab).hexdigest())}
    monkeypatch.setattr(embedder, "FILES", files)
    monkeypatch.setattr(embedder, "hub_url", lambda name: f"{base}/{files[name][0]}")
    _Files.files = {"/onnx/model.onnx": model, "/vocab.txt": vocab}
    _Files.requests = []
    yield SimpleNamespace(base=base, model=model, vocab=vocab, files=files)
    server.shutdown()


class _FakeSession:
    """Stands in for ONNX Runtime: every token id has one fixed vector, and the hidden states are those vectors, so
    the pooled sentence vector is the mean of its tokens' vectors (padding must not change it)."""

    def __init__(self, vocab_size: int, dim: int):
        self.table = np.random.default_rng(0).standard_normal((vocab_size, dim)).astype(np.float32)
        self.calls = 0

    def get_inputs(self):
        return [SimpleNamespace(name=n) for n in ("input_ids", "attention_mask", "token_type_ids")]

    def get_outputs(self):
        return [SimpleNamespace(name="last_hidden_state")]

    def run(self, names, feed):
        self.calls += 1
        ids = feed["input_ids"]
        assert names == ["last_hidden_state"]
        assert feed["attention_mask"].shape == ids.shape == feed["token_type_ids"].shape
        return [self.table[ids]]


@pytest.fixture()
def fake_model(hub, monkeypatch):
    """The downloaded stand-in model, "loaded" into the fake session."""
    from clipfoundry import embedder

    embedder.ensure_model()
    tok = embedder.WordPiece(embedder.model_dir() / "vocab.txt")
    session = _FakeSession(len(tok.ids), embedder.DIM)
    monkeypatch.setattr(embedder, "_model", embedder._Loaded(session, tok))
    monkeypatch.setattr(embedder, "runtime_ok", lambda: True)
    monkeypatch.setattr(embedder, "in_cloud", lambda: False)
    return session


class _Fake:
    """Stands in for ClipForge AI: an answer per kind of request (told apart by the prompt), and a record of every
    request with its keyword arguments."""

    def __init__(self, scout=None, judge=None, stories=None, eyes=None, raise_=None, raw=None):
        self.scout, self.judge, self.stories, self.eyes, self.raise_, self.raw = scout, judge, stories, eyes, raise_, raw
        self.calls: list[dict] = []

    def __call__(self, opts, prompt, **kw):
        self.calls.append({"prompt": prompt, **kw})
        if self.raise_:
            raise self.raise_
        if self.raw is not None:
            return self.raw
        if "finalists below" in prompt:
            fn = self.judge
        elif "of the transcript" in prompt:
            fn = self.scout
        elif "BEGIN A NEW STORY" in prompt or "BEGINS A NEW STORY" in prompt:
            fn = self.stories
        else:
            fn = self.eyes
        return json.dumps(fn(prompt)) if fn else "{}"


# ------------------------------------------------------------------ the settings
def test_the_new_parts_are_on_by_default():
    from clipfoundry import config

    for key in ("meaning_model", "deep_analysis", "ai_scout", "ai_eyes"):
        assert config.DEFAULT_SETTINGS[key] is True


# ------------------------------------------------------------------ the meaning model: download
def test_the_meaning_model_is_downloaded_once_checked_and_remembered(hub):
    from clipfoundry import embedder

    assert not embedder.model_ready()
    seen = []
    folder = embedder.ensure_model(lambda status, done, total: seen.append((status, done, total)))
    assert embedder.model_ready() and (folder / "model.onnx").read_bytes() == hub.model
    assert "Apache" in (folder / "LICENSE.txt").read_text(encoding="utf-8")
    marker = json.loads((folder / embedder.MARKER).read_text(encoding="utf-8"))
    assert marker["files"] == {n: sha for n, (_p, _s, sha) in hub.files.items()}
    assert marker["repo"] == embedder.REPO and marker["revision"] == embedder.REVISION
    assert seen[0][0].startswith("Downloading") and seen[-1][1] == seen[-1][2] == embedder.download_bytes()
    assert embedder.download_bytes() == len(hub.model) + len(hub.vocab)
    assert sorted(_Files.requests) == ["/onnx/model.onnx", "/vocab.txt"]
    embedder.ensure_model()  # present: nothing is fetched again
    assert len(_Files.requests) == 2
    st = embedder.status({"meaning_model": True})
    assert st["ready"] and st["enabled"] and st["name"] == "all-MiniLM-L6-v2" and st["license"] == "Apache-2.0"
    assert st["model"] == embedder.MODEL and st["download_bytes"] == embedder.download_bytes()
    assert st["usable"] == (embedder.runtime_ok() and not embedder.in_cloud()) and st["folder"] == str(folder)
    off = embedder.status({"meaning_model": False})
    assert not off["enabled"] and not off["usable"] and "Switched off" in off["problem"]


def test_a_changed_file_or_a_new_pinned_version_is_not_trusted(hub, monkeypatch):
    from clipfoundry import embedder

    folder = embedder.ensure_model()
    (folder / "vocab.txt").write_bytes(hub.vocab + b"##x\n")  # a file that grew
    assert not embedder.model_ready()
    (folder / "vocab.txt").write_bytes(hub.vocab)
    assert embedder.model_ready()
    monkeypatch.setattr(embedder, "FILES", {**hub.files, "vocab.txt": ("vocab.txt", len(hub.vocab), "0" * 64)})
    assert not embedder.model_ready()  # the pin moved: the old folder is downloaded again
    embedder.remove()
    assert not folder.exists() and not embedder.model_ready()


def test_a_download_with_the_wrong_checksum_is_refused_and_the_next_try_waits(hub, monkeypatch):
    from clipfoundry import embedder

    _Files.files["/vocab.txt"] = hub.vocab[:-4] + b"xyz\n"  # the same size, other bytes
    with pytest.raises(embedder.MeaningError, match="checksum"):
        embedder.ensure_model()
    assert not embedder.model_ready() and not list(embedder.model_dir().glob("*.part"))
    n = len(_Files.requests)
    with pytest.raises(embedder.MeaningError, match="checksum"):
        embedder.ensure_model()  # for an hour, the fallback is used without another request
    assert len(_Files.requests) == n
    assert "checksum" in embedder.status({"meaning_model": True})["problem"]
    assert embedder.embed_or_none(["hello"], {"meaning_model": True}) is None  # callers fall back quietly
    assert semantic.embed_texts(["hello there", "general kenobi"], opts={"meaning_model": True}).model == "lexical"
    # a person asking on the settings page tries again at once, in the background
    _Files.files["/vocab.txt"] = hub.vocab
    monkeypatch.setattr(embedder, "_loaded", lambda: None)  # the random "model" cannot be loaded for real
    done = threading.Event()
    task = embedder.install(lambda snapshot: done.set())
    assert task["state"] == "running" and task["total"] == embedder.download_bytes()
    assert done.wait(20)
    st = embedder.status()
    assert st["task"]["state"] == "done" and st["task"]["completed"] == embedder.download_bytes() and st["ready"]


def test_a_missing_file_a_cancelled_download_and_an_offline_computer_each_say_what_happened(hub):
    from clipfoundry import embedder

    del _Files.files["/vocab.txt"]
    with pytest.raises(embedder.MeaningError, match="answered 404"):
        embedder.ensure_model()
    embedder.reset_for_tests()
    _Files.files["/vocab.txt"] = hub.vocab
    embedder.cancel()
    with pytest.raises(embedder.MeaningError, match="Canceled"):
        embedder.ensure_model()
    assert not list(embedder.model_dir().glob("*.part"))
    embedder.reset_for_tests()
    embedder.hub_url = lambda name: "http://127.0.0.1:9/" + name  # a closed port, like no network
    with pytest.raises(embedder.MeaningError, match="online"):
        embedder.ensure_model()


def test_in_the_cloud_the_meaning_model_is_never_downloaded(hub, monkeypatch):
    from clipfoundry import embedder

    monkeypatch.setattr(embedder, "in_cloud", lambda: True)
    with pytest.raises(embedder.MeaningError, match="desktop app"):
        embedder.ensure_model()
    with pytest.raises(embedder.MeaningError, match="desktop app"):
        embedder.install()
    assert _Files.requests == [] and "desktop app" in embedder.status()["problem"]


# ------------------------------------------------------------------ the meaning model: the tokenizer and the vectors
def test_the_tokenizer_splits_words_like_bert_uncased(tmp_path):
    from clipfoundry import embedder

    vocab = tmp_path / "vocab.txt"
    vocab.write_text("\n".join(VOCAB) + "\n", encoding="utf-8")
    tok = embedder.WordPiece(vocab)
    assert embedder.WordPiece.words("The CAT sat, on 2 mats!\tCafé 我们") == \
        ["the", "cat", "sat", ",", "on", "2", "mats", "!", "cafe", "我", "们"]
    ids = tok.encode("The cat sat on mats.")
    names = [VOCAB[i] for i in ids]
    assert names == ["[CLS]", "the", "cat", "sat", "on", "mat", "##s", ".", "[SEP]"]
    assert [VOCAB[i] for i in tok.pieces("unbelievable")] == ["un", "##believ", "##able"]
    assert tok.pieces("xylophone") == [tok.unk] and tok.pieces("20") == [tok.ids["2"], tok.ids["##0"]]
    short = embedder.WordPiece(vocab, max_tokens=5)
    cut = short.encode("the cat sat on the mat on the mat")
    assert len(cut) == 5 and cut[0] == tok.cls and cut[-1] == tok.sep


def test_vectors_are_pooled_over_real_tokens_only_cached_and_deduplicated(fake_model):
    from clipfoundry import embedder

    on = {"meaning_model": True}
    short, long = "the cat sat", "the cat sat on the mat and the kitten rested on the rug far away from home"
    alone = {t: embedder.embed([t], on)[0].copy() for t in (long, short)}
    assert fake_model.calls == 2
    embedder._cache.clear(), embedder._cache_order.clear()
    both = embedder.embed([short, long, short], on)  # one batch: the short text is padded next to the long one
    assert fake_model.calls == 3  # one run for two distinct texts
    assert np.allclose(both[0], alone[short], atol=1e-5) and np.allclose(both[1], alone[long], atol=1e-5)
    assert np.allclose(both[2], both[0]) and np.allclose(np.linalg.norm(both, axis=1), 1.0, atol=1e-5)
    embedder.embed([short, long], on)
    assert fake_model.calls == 3  # answered from the cache
    with pytest.raises(embedder.MeaningError, match="switched off"):
        embedder.embed([short], {"meaning_model": False})
    assert embedder.embed_or_none([short], {"meaning_model": False}) is None
    assert embedder.embed_or_none([], on).shape == (0, embedder.DIM)
    assert embedder.embed_one(short, on).shape == (embedder.DIM,)


def test_sentence_vectors_carry_their_model_and_baseline_and_cos_cal_removes_it(fake_model):
    from clipfoundry import embedder

    texts = ["The cat sat on the mat.", "A kitten rested on the rug.", "Quarterly tax returns are due."]
    emb = semantic.embed_texts(texts, opts={"meaning_model": True})
    assert isinstance(emb, semantic.Embeddings) and emb.model == embedder.MODEL and emb.shape == (3, embedder.DIM)
    assert emb.baseline == semantic.MEANING_BASELINE  # too few sentences to measure the video's own baseline
    assert emb[1:].model == embedder.MODEL and emb[1:].baseline == emb.baseline  # slices keep both
    assert semantic.cos_cal(emb, emb[0], emb[0]) == pytest.approx(1.0, abs=1e-5)
    off = semantic.embed_texts(texts, opts={"meaning_model": False})
    assert off.model == "lexical" and off.baseline == 0.0 and off.shape[1] <= semantic.DIM + semantic.RAW_DIM
    e = semantic.Embeddings(np.eye(3, dtype=np.float32), "x", 0.5)
    assert semantic.cos_cal(e, e[0], e[1]) == -1.0 and semantic.cos_cal(e, e[0], e[0]) == 1.0
    plain = semantic.Embeddings(np.eye(3, dtype=np.float32))
    assert semantic.cos_cal(plain, plain[0], plain[1]) == 0.0
    assert semantic.embed_texts([]).shape == (0, 1)


def test_the_baseline_is_measured_on_the_video_itself_when_it_is_long_enough(monkeypatch):
    from clipfoundry import embedder

    rng = np.random.default_rng(1)
    vecs = rng.standard_normal((40, embedder.DIM)).astype(np.float32) + 0.6  # every pair leans the same way
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    monkeypatch.setattr(embedder, "embed_or_none", lambda texts, settings=None: vecs[:len(texts)])
    emb = semantic.embed_texts([f"sentence {k}" for k in range(40)])
    assert emb.model == embedder.MODEL and 0.2 < emb.baseline <= 0.35  # the unrelated level (capped at 0.35)
    sims = [semantic.cos_cal(emb, emb[i], emb[j]) for i in range(40) for j in range(i + 6, 40)]
    assert abs(float(np.median(sims))) < 0.15  # after calibration, unrelated sits near 0


def test_novelty_is_a_rank_and_the_semantic_features_keep_their_shape():
    words, sents = _talk(COOKING + ENGINES + COOKING)
    emb = semantic.embed_sentences(sents)
    assert emb.model == "lexical"
    engines = semantic.features(emb, len(COOKING), len(COOKING) + len(ENGINES) - 1)
    cooking = semantic.features(emb, 0, len(COOKING) - 1)
    assert set(engines) == {"coherence", "min_adjacent", "closure", "context_dependency", "novelty", "score"}
    assert 0.0 <= engines["novelty"] <= 1.0 and engines["novelty"] > cooking["novelty"]  # the odd passage out
    assert semantic.features(emb, -1, -1)["novelty"] == 0.5


def test_the_brain_uses_whichever_vector_space_is_available_and_reads_old_memories_still(fake_model, monkeypatch):
    pytest.importorskip("onnxruntime")
    from clipfoundry import brain, embedder
    from clipfoundry.brain import meaning

    assert meaning.min_similar(embedder.MODEL) == 0.30 and meaning.min_similar(meaning.HASH_MODEL) == 0.15
    monkeypatch.setattr(embedder, "model_ready", lambda: False)  # before the download: hashing
    assert meaning.model({"meaning_model": True}) == meaning.HASH_MODEL
    old = brain.remember("local", "Never zoom in on faces", kind="rule", source="said")
    assert old["meaning_model"] == meaning.HASH_MODEL and len(old["meaning"]) == meaning.DIM * 4
    monkeypatch.setattr(embedder, "model_ready", lambda: True)  # downloaded: the meaning model
    assert meaning.model({"meaning_model": True}) == embedder.MODEL
    assert meaning.model({"meaning_model": False}) == meaning.HASH_MODEL
    packed, which = meaning.make("Keep the hook under three seconds", {"meaning_model": True})
    assert which == embedder.MODEL and len(packed) == embedder.DIM * 4
    new = brain.remember("local", "Keep the hook under three seconds", kind="rule", source="said")
    assert new["meaning_model"] == embedder.MODEL and len(new["meaning"]) == embedder.DIM * 4
    rec = brain.recall("do not zoom in on faces", "local", mode="clips", kinds=("rule",), limit=4, budget_chars=600)
    assert old["id"] in rec.ids  # a memory saved with the other space is still found (by its words)


# ------------------------------------------------------------------ the scout and the judge
def test_the_brief_carries_the_lengths_the_playbooks_and_your_taste():
    b = scout.brief({**AI_OPTS, "video_name": "Lake day"})
    assert b.video_name == "Lake day" and b.min_s == 15 and b.max_s == 60 and b.target_s == 30
    assert b.knowhow and len(b.knowhow) <= scout.KNOWHOW_CHARS + 200  # the built-in playbooks about picking clips
    text = b.text()
    assert '"Lake day"' in text and "15 to 60 seconds long, ideally about 30" in text and b.knowhow in text
    assert scout.configured(AI_OPTS) and not scout.configured(OPTS) and not scout.configured({**AI_OPTS, "ai_scout": False})
    assert scout.budget_s(AI_OPTS) == 600 and scout.budget_s({**AI_OPTS, "ai_edit_timeout_s": 5}) == 60


def test_windows_cover_every_sentence_in_order_and_ranges_snap_to_the_allowed_length():
    words, sents = _talk(COOKING + ENGINES + COOKING + ENGINES)
    wins = scout.windows(sents, chars=400)
    assert wins[0][0] == 0 and wins[-1][1] == len(sents) - 1 and len(wins) > 1
    assert all(a[1] + 1 == b[0] for a, b in zip(wins, wins[1:]))
    assert scout.windows(sents) == [(0, len(sents) - 1)]
    assert scout.windows([]) == []
    # a range longer than allowed is cut from the end; a short one grows forward; outside the window is nothing
    mins = 2 * (sents[1]["end"] - sents[0]["start"])
    first, last = scout._fit(sents, 0, 1, 0, len(sents) - 1, mins, mins * 3)
    assert first == 0 and sents[last]["end"] - sents[0]["start"] >= mins
    first, last = scout._fit(sents, 0, len(sents) - 1, 0, len(sents) - 1, 1.0, mins)
    assert first == 0 and sents[last]["end"] - sents[0]["start"] <= mins and last < len(sents) - 1
    assert scout._fit(sents, 40, 41, 0, 5, 1.0, 60.0) is None
    assert scout._fit(sents, 0, 0, 0, 0, 100.0, 200.0) is None  # cannot grow: too short stays out


def test_the_scout_reads_the_whole_video_and_its_moments_join_the_pool():
    words, sents, loud, cands = _deep_inputs()
    feats = candidates.sentence_features(sents, words)
    b = scout.brief(AI_OPTS)
    fake = _Fake(scout=lambda p: {"moments": [{"first": 2, "last": 3, "kind": "insight", "why": "a clear tip"},
                                               {"first": 900, "last": 901, "kind": "funny", "why": "outside"},
                                               {"first": 9, "last": 9, "kind": "nonsense", "why": "x"}]})
    added, notes = scout.nominate(sents, feats, loud, AI_OPTS, JobContext(), [], b, complete=fake)
    assert notes["windows"] == notes["asked"] == notes["answered"] == notes["read"] == 1 and notes["coverage"] == 1.0
    assert notes["nominated"] == notes["added"] == len(added) == 2 and notes["problems"] == []
    assert notes["provider"] == "Ollama test"
    for w in added:
        assert b.min_s * 0.6 <= w["end"] - w["start"] <= b.max_s * 1.05 and w["scout"]["part"] == 1 and w["s0"] >= 0
    assert added[0]["scout"] == {"kind": "insight", "why": "a clear tip", "part": 1} and added[0]["s0"] == 2
    assert added[1]["scout"]["kind"] == "moment"  # a kind the model made up
    call = fake.calls[0]
    assert call["json_schema"] is scout.SCOUT_SCHEMA and call["task"] == "scout" and call["json_object"]
    assert call["system"] == scout.SYSTEM and call["max_tokens"] == 400 and call["num_ctx"] == 8192
    assert "0 [0:00]" in call["prompt"] and "Name up to 4 moments" in call["prompt"] and b.knowhow in call["prompt"]
    # a moment the local analysis already found is confirmed (marked and lifted), not duplicated
    twin = candidates.window(sents, feats, added[0]["s0"], added[0]["s1"], loud, AI_OPTS, candidates.common_words(sents))
    before = twin["stage1"]
    again, notes2 = scout.nominate(sents, feats, loud, AI_OPTS, JobContext(), [twin], b, complete=fake)
    assert notes2["confirmed"] == 1 and twin["scout"]["kind"] == "insight"
    assert twin["stage1"] == pytest.approx(before + scout.SCOUT_BONUS) and all(w["s0"] != twin["s0"] for w in again)
    # nothing without a model, and failures are noted rather than raised
    quiet = _Fake(scout=lambda p: {"moments": []})
    assert scout.nominate(sents, feats, loud, OPTS, JobContext(), [], b, complete=quiet) == ([], scout.nominate(
        sents, feats, loud, OPTS, JobContext(), [], b, complete=quiet)[1]) and quiet.calls == []
    down = _Fake(raise_=llm.ProviderError("the model is down"))
    added, notes = scout.nominate(sents, feats, loud, AI_OPTS, JobContext(), [], b, complete=down)
    assert added == [] and notes["problems"] == ["part 1 of 1: the model is down"] and notes["answered"] == 0
    garbled = _Fake(raw="I would pick the second half")
    _, notes = scout.nominate(sents, feats, loud, AI_OPTS, JobContext(), [], b, complete=garbled)
    assert notes["problems"] == ["part 1 of 1: the answer was not readable."]


def test_the_judge_ranks_the_finalists_side_by_side_within_bounds():
    words, sents, loud, cands = _deep_inputs()
    _, results, _ = deep.evaluate_select(sents, words, loud, OPTS, JobContext(), "talk", cands)
    pool = [r for r in results if r.get("s0", -1) >= 0]
    n = min(scout.JUDGE_MAX, len(pool))
    assert n >= 3
    # a ranking that names too few finalists is not used
    notes = scout.judge(results, sents, AI_OPTS, JobContext(), None,
                        complete=_Fake(judge=lambda p: {"ranking": [1], "verdicts": []}))
    assert notes["finalists"] == n and "too few" in notes["problems"][0] and not any("judge" in r for r in results)

    def judged(prompt: str) -> dict:
        k = int(re.search(r"The (\d+) finalists below", prompt).group(1))
        assert k == n and f"Finalist {k} (" in prompt and "Finalist 1 (" in prompt
        return {"ranking": list(range(k, 0, -1)),  # the model turns the local order upside down
                "verdicts": [{"n": 1, "verdict": "red", "note": "needs what came before"},
                             {"n": k, "verdict": "green", "note": "lands"}, {"n": 2, "verdict": "purple", "note": "?"}]}
    fake = _Fake(judge=judged)
    notes = scout.judge(results, sents, AI_OPTS, JobContext(), scout.brief(AI_OPTS), complete=fake)
    assert notes["finalists"] == n and notes["answered"] == 1 and notes["problems"] == []
    assert notes["verdicts"] == {"red": 1, "green": 1, "none": n - 2}
    order = sorted(pool, key=lambda r: r["clip_score"], reverse=True)[:n]
    top, bottom, middle = order[0], order[-1], order[n // 2]
    assert top["judge"]["rank"] == n and top["judge"]["verdict"] == "red" and top["judge"]["note"] == "needs what came before"
    assert top["judge"]["adjust"] == -(scout.JUDGE_WEIGHT + scout.RED_PENALTY) and top["judge"]["of"] == n
    assert [f for f in top["analysis"]["flags"] if f["id"] == "ai_red"][0]["severity"] == "warn"
    assert bottom["judge"]["rank"] == 1 and bottom["judge"]["verdict"] == "green"
    assert bottom["judge"]["adjust"] == scout.JUDGE_WEIGHT + scout.GREEN_BONUS
    assert abs(middle["judge"]["adjust"]) <= scout.JUDGE_WEIGHT and middle["judge"]["verdict"] == ""
    assert all(r["judge"]["provider"] == "Ollama test" for r in order)
    call = fake.calls[0]
    assert call["json_schema"] is scout.JUDGE_SCHEMA and call["max_tokens"] == 700 and "seconds long" in call["prompt"]
    assert "Rank them from the one most likely to hold a viewer" in call["prompt"]


def test_the_deep_analysis_keeps_the_scouts_moments_and_explains_every_verdict(monkeypatch):
    words, sents, loud, big = _deep_inputs()
    feats = candidates.sentence_features(sents, words)
    small = candidates.find_candidates(words, sents, loud, OPTS, pool_size=4, max_overlap=0.5)
    assert len(small) == 4 < len(big)
    # the model names a strong moment the small pool missed
    extra = max((c for c in big if all(candidates._overlap(c, k) <= 0.6 for k in small)), key=lambda c: c["stage1"])
    fake = _Fake(scout=lambda p: {"moments": [{"first": extra["s0"], "last": extra["s1"], "kind": "story",
                                               "why": "a whole story with an ending"}]},
                 judge=lambda p: {"ranking": list(range(1, int(re.search(r"The (\d+) finalists", p).group(1)) + 1)),
                                  "verdicts": [{"n": 1, "verdict": "green", "note": "a clear first line"}]})
    monkeypatch.setattr(llm, "complete", fake)
    b = scout.brief(AI_OPTS)
    added, notes = scout.nominate(sents, feats, loud, AI_OPTS, JobContext(), small, b, complete=fake)
    assert notes["nominated"] == notes["added"] == 1 and notes["confirmed"] == 0
    assert (added[0]["s0"], added[0]["s1"]) == (extra["s0"], extra["s1"]) and added[0]["stage1"] > extra["stage1"]
    monkeypatch.setattr(deep, "DEEP_KEEP", 2)  # a tight deep stage: the model's moment must still get a place
    chosen, results, notes = deep.evaluate_select(sents, words, loud, AI_OPTS, JobContext(), "talk", small + added,
                                                  brief=b)
    st = notes["stages"]
    assert st["pool"] == 5 and st["scouted"] == 1 and st["deep"] == 2 and st["seen"] == 0  # no video: eyes closed
    mine = [r for r in results if r.get("scout")]
    assert len(mine) == 1 and mine[0]["scout"]["why"] == "a whole story with an ending"
    assert "named by ClipForge AI while reading the video (story)" in mine[0]["explanation"]
    gave_way = [t for t in notes["candidates"] if any("gave its place" in why for why in t["reasons"])]
    assert len(gave_way) <= 1 and all(t["stage"] == "semantic" for t in gave_way)
    assert notes["judge"]["finalists"] == 2 and notes["judge"]["answered"] == 1 and all(r.get("judge") for r in results)
    best = max(results, key=lambda r: r["clip_score"])
    assert best["judge"] == {"rank": 1, "of": 2, "verdict": "green", "note": "a clear first line",
                             "adjust": scout.GREEN_BONUS, "provider": "Ollama test"}
    assert f"+{scout.GREEN_BONUS:.1f} ClipForge AI ranked it 1 of 2 (green)" in best["explanation"]
    for r in results:
        assert r["deep"]["prosody"] is None and r["deep"]["seen"] is None  # no sound file, no video
        assert r["clip_score"] == deep.clip_score(r)[0]
    assert [call["task"] for call in fake.calls] == ["scout", "scout"]  # one read of the video, one ranking


def test_the_deep_analysis_opens_its_eyes_on_a_video_with_the_built_in_model(monkeypatch):
    from clipfoundry.pipeline import eyes

    words, sents, loud, _big = _deep_inputs()
    small = candidates.find_candidates(words, sents, loud, OPTS, pool_size=4, max_overlap=0.5)
    opts = {**OPTS, "ai_provider": "builtin", "ai_scout": False, "ai_edit_timeout_s": 60}
    fake = _Fake(eyes=lambda p: {"kind": "talking_head", "people": 1, "text_on_screen": "", "best_frame": 2,
                                 "appeal": 9, "description": "A woman explains at a desk.", "problem": ""})
    monkeypatch.setattr(llm, "complete", fake)
    monkeypatch.setattr(llm, "provider_label", lambda s: "ClipForge AI (Basic)")
    monkeypatch.setattr(eyes, "frame", lambda video, t, **kw: f"data:image/jpeg;base64,{int(t)}")
    monkeypatch.setattr(deep, "visual_features", lambda *a, **k: None)  # no real video on this computer
    monkeypatch.setattr(deep, "DEEP_KEEP", 2)
    meta = {"width": 1920, "height": 1080, "has_video": True, "duration": words[-1]["end"] + 1.0}
    chosen, results, notes = deep.evaluate_select(sents, words, loud, opts, JobContext(), "talk", small,
                                                  video_path="talk.mp4", meta=meta)
    st = notes["stages"]
    assert st["deep"] == 2 and st["seen"] == 2 and st["visual"] == 0 and "judge" not in notes
    for r in results:
        seen = r["deep"]["seen"]
        assert seen["kind"] == "talking_head" and seen["adjust"] == pytest.approx(3.2) and seen["frames"] == 3
        assert r["start"] < seen["thumbnail_t"] < r["end"]
        assert "+3.2 ClipForge AI looked at the picture (A woman explains at a desk, appeal 9/10)" in r["explanation"]
        assert r["clip_score"] == deep.clip_score(r)[0]
    assert len(fake.calls) == 2 and all(c["task"] == "eyes" and len(c["images"]) == 3 for c in fake.calls)


# ------------------------------------------------------------------ the eyes
def test_the_eyes_look_at_three_frames_and_answer_in_a_fixed_shape(monkeypatch):
    from clipfoundry.pipeline import eyes

    opts = {"ai_provider": "builtin", "ai_edit_timeout_s": 60}
    assert eyes.configured(opts) and eyes.configured(opts, {"width": 1280, "has_video": True})
    assert not eyes.configured({**opts, "ai_eyes": False}) and not eyes.configured(AI_OPTS)  # the built-in model only
    assert not eyes.configured(opts, {"width": 0}) and not eyes.configured(opts, {"width": 640, "has_video": False})
    assert eyes.frame_times(10.0, 30.0) == [15.0, 20.0, 25.0] and eyes.budget_s(opts) == 300
    monkeypatch.setattr(eyes, "frame", lambda video, t, **kw: f"data:image/jpeg;base64,{int(t)}")
    monkeypatch.setattr(llm, "provider_label", lambda s: "ClipForge AI (Standard)")
    fake = _Fake(eyes=lambda p: {"kind": "talking_head", "people": 1, "text_on_screen": " LIVE ", "best_frame": 2,
                                 "appeal": 8, "description": "A man talks to the camera.", "problem": ""})
    seen = eyes.look("v.mp4", 10.0, 30.0, "Here is the thing about pasta", opts, None, complete=fake)
    assert seen == {"kind": "talking_head", "people": 1, "text_on_screen": "LIVE", "description": "A man talks to the camera",
                    "problem": "", "appeal": 8, "thumbnail_t": 20.0, "frames": 3, "adjust": 2.4,
                    "provider": "ClipForge AI (Standard)"}
    call = fake.calls[0]
    assert call["images"] == ["data:image/jpeg;base64,15", "data:image/jpeg;base64,20", "data:image/jpeg;base64,25"]
    assert call["json_schema"] is eyes.SCHEMA and call["task"] == "eyes" and call["max_tokens"] == 300
    assert "These are 3 frames" in call["prompt"] and "Here is the thing about pasta" in call["prompt"]
    # bounds: a dull picture costs at most WEIGHT, a striking one earns at most WEIGHT
    dull = _Fake(eyes=lambda p: {"kind": "slides", "people": 0, "best_frame": 9, "appeal": -3, "problem": "dark"})
    seen = eyes.look("v.mp4", 0.0, 8.0, "", opts, None, complete=dull)
    assert seen["adjust"] == -3.2 and seen["appeal"] == 1 and seen["thumbnail_t"] == eyes.frame_times(0, 8)[-1]
    wow = _Fake(eyes=lambda p: {"kind": "other", "people": 99, "best_frame": 0, "appeal": 10})
    seen = eyes.look("v.mp4", 0.0, 8.0, "", opts, None, complete=wow)
    assert seen["adjust"] == eyes.WEIGHT and seen["people"] == 20 and seen["thumbnail_t"] == eyes.frame_times(0, 8)[0]
    # nothing to see, an unreadable answer or a failing model: no verdict, never an error
    assert eyes.look("v.mp4", 0.0, 8.0, "", opts, None, complete=_Fake(raw="a nice video")) is None
    assert eyes.look("v.mp4", 0.0, 8.0, "", opts, None, complete=_Fake(raise_=llm.ProviderError("down"))) is None
    blind = _Fake(eyes=lambda p: {})
    monkeypatch.setattr(eyes, "frame", lambda video, t, **kw: None)
    assert eyes.look("v.mp4", 0.0, 8.0, "", opts, None, complete=blind) is None and blind.calls == []


@needs_ffmpeg
def test_a_frame_is_a_small_jpeg(tmp_path):
    from synthetic_media import make_video

    from clipfoundry.pipeline import eyes

    video = make_video(tmp_path / "v.mp4", seconds=2.0, audio=False)
    url = eyes.frame(str(video), 1.0)
    assert url.startswith("data:image/jpeg;base64,")
    import base64

    raw = base64.b64decode(url.split(",", 1)[1])
    assert raw[:2] == b"\xff\xd8" and 500 < len(raw) < 200_000
    assert eyes.frame(str(tmp_path / "missing.mp4"), 1.0) is None


def test_the_thumbnail_is_the_frame_the_eyes_picked_when_it_is_inside_the_clip():
    from clipfoundry.pipeline import render

    seen = {"analysis": {"deep": {"seen": {"thumbnail_t": 112.0}}}, "start": 100.0}
    assert render.thumbnail_time(seen, 20.0) == 12.0
    assert render.thumbnail_time({**seen, "edit": {"speed": 2.0}}, 20.0) == 6.0  # the clip plays faster
    assert render.thumbnail_time(seen, 10.0) == 1.2  # past the end of a shortened clip: the usual spot
    assert render.thumbnail_time({"start": 5.0}, 2.4) == pytest.approx(0.8) and render.thumbnail_time({}, 20.0) == 1.2
    assert render.thumbnail_time({"analysis": {"deep": {"seen": {"thumbnail_t": "soon"}}}, "start": 0}, 20.0) == 1.2


# ------------------------------------------------------------------ the ears
SR = 16000


def _voice(seconds: float, f0, gain=1.0, harmonics: int = 6) -> np.ndarray:
    """A voice-like pitched sound: a few harmonics of f0 (a number or a function of time)."""
    t = np.arange(int(seconds * SR)) / SR
    f = f0(t) if callable(f0) else np.full_like(t, float(f0))
    phase = 2 * np.pi * np.cumsum(f) / SR
    x = sum(np.sin(h * phase) / h for h in range(1, harmonics + 1))
    return (0.2 * gain * x / harmonics).astype(np.float32)


def _wav(path: Path, x: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def _spoken(start: float, end: float, step: float = 0.3) -> list[dict]:
    return [{"start": round(t, 2), "end": round(min(end, t + step), 2), "w": "la"} for t in np.arange(start, end, step)]


def test_the_ears_hear_emphasis_where_pitch_and_loudness_rise_together():
    from clipfoundry.pipeline import ears

    plain = _voice(6.0, 120.0)
    k0, k1 = int(3.0 * SR), int(3.6 * SR)
    plain[k0:k1] = _voice(0.6, 120.0 * 2 ** (6 / 12), gain=3.0)  # six semitones up and about 10 dB louder
    res = ears.analyze(plain, 0.0, _spoken(0.0, 6.0))
    assert res["frames"] > 250 and res["voiced_share"] > 0.8
    assert len(res["emphasis_times"]) == 1 and 2.9 <= res["emphasis_times"][0] <= 3.7
    assert res["emphasis_per_30s"] == 2.0  # per 30 s, counted over at least 15 s so a short clip cannot inflate it
    assert res["laughter_like"] == 0 and res["estimated"]
    # the times are reported in the recording's own clock
    later = ears.analyze(plain, 100.0, _spoken(100.0, 106.0))
    assert len(later["emphasis_times"]) == 1 and 102.9 <= later["emphasis_times"][0] <= 103.7
    assert ears.analyze(np.zeros(100, dtype=np.float32))["frames"] == 0  # too short to say anything


def test_the_ears_tell_a_lively_voice_from_a_flat_one():
    from clipfoundry.pipeline import ears

    flat = ears.analyze(_voice(5.0, 130.0), 0.0, _spoken(0.0, 5.0))
    assert flat["monotone"] and flat["pitch_variation"] < 0.1 and flat["score"] < 0.3
    t_mod = lambda t: 140.0 * 2 ** (0.5 * np.sin(2 * np.pi * 0.7 * t))  # sweeps half an octave up and down
    lively_x = _voice(5.0, t_mod) * (1.0 + 0.6 * np.sin(2 * np.pi * 0.9 * np.arange(int(5.0 * SR)) / SR)).astype(np.float32)
    lively = ears.analyze(lively_x, 0.0, _spoken(0.0, 5.0))
    assert not lively["monotone"] and lively["pitch_variation"] > 0.5 and lively["pitch_semitones_std"] > 2.0
    assert lively["score"] > flat["score"]


def test_the_ears_hear_laughter_like_bursts_where_nobody_speaks():
    from clipfoundry.pipeline import ears

    x = _voice(6.0, 120.0)
    rng = np.random.default_rng(2)
    k0, k1 = int(2.0 * SR), int(4.0 * SR)
    burst_t = np.arange(k1 - k0) / SR
    pulses = (np.sin(2 * np.pi * 5.0 * burst_t) > 0).astype(np.float32)  # five bursts a second
    x[k0:k1] = (0.15 * rng.standard_normal(k1 - k0) * pulses).astype(np.float32)
    words = _spoken(0.0, 2.0) + _spoken(4.0, 6.0)
    res = ears.analyze(x, 0.0, words)
    assert res["laughter_like"] == 1 and 1.5 <= res["laughter_seconds"] <= 2.2
    quiet = x.copy()
    quiet[k0:k1] = 0.0  # the same gap with nothing in it
    assert ears.analyze(quiet, 0.0, words)["laughter_like"] == 0
    steady = x.copy()
    steady[k0:k1] = (0.15 * rng.standard_normal(k1 - k0)).astype(np.float32)  # noise that does not pulse
    assert ears.analyze(steady, 0.0, words)["laughter_like"] == 0
    assert res["pause_before_end_s"] == pytest.approx(0.0, abs=0.05)


def test_clip_prosody_and_emphasis_points_read_the_file_and_the_cache(tmp_path, monkeypatch):
    from clipfoundry.pipeline import ears

    x = _voice(70.0, 120.0)
    for at in (10.0, 65.0):
        k = int(at * SR)
        x[k:k + int(0.6 * SR)] = _voice(0.6, 120.0 * 2 ** (6 / 12), gain=3.0)
    wav = _wav(tmp_path / "audio.wav", x)
    words = _spoken(0.0, 70.0)
    clip = ears.clip_prosody(wav, 8.0, 14.0, words)
    assert clip and 9.9 <= clip["emphasis_times"][0] <= 10.7 and clip["frames"] > 250
    assert ears.clip_prosody(None, 0, 1, words) is None and ears.clip_prosody(tmp_path / "no.wav", 0, 1, words) is None
    cache = tmp_path / "prosody.json"
    points = ears.emphasis_points(wav, words, cache=cache)  # one-minute blocks: the second emphasis sits in block 2
    assert len(points) == 2 and 9.9 <= points[0] <= 10.7 and 64.9 <= points[1] <= 65.7
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["key"]["version"] == ears.VERSION and saved["key"]["size"] == wav.stat().st_size
    monkeypatch.setattr(ears, "analyze", lambda *a, **k: pytest.fail("the cache should answer"))
    assert ears.emphasis_points(wav, words, cache=cache) == points
    assert ears.emphasis_points(None, words) == [] and ears.emphasis_points(tmp_path / "no.wav", words) == []


def test_punch_ins_land_where_the_voice_leans_on_a_word(env, monkeypatch):  # noqa: F811 - the env fixture
    from clipfoundry.studio import engine, smart_edit, video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    script = _say(1.0, "One two three.") + _say(2.6, "Four five six.") + _say(4.2, "Seven eight nine.")
    words = {v["id"]: _words(script)}
    monkeypatch.setattr(smart_edit, "emphasis_points", lambda asset, ws: [4.5])  # the voice rises on "eight"
    project = _project([v], {"smart_edit": "tight", "music": "none", "punch_in": True}, "Fast")
    plan = _cut(project, words)
    zooms = [c.get("zoom", 1.0) for c in plan["clips"]]
    assert zooms == [1.0, 1.0, smart_edit.PUNCH_IN]
    assert any("1 punch-in where your voice leans on a word" in n for n in plan["notes"])
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    # an even voice must not leave the jump cuts bare: the old rhythm takes over, and the note says so
    monkeypatch.setattr(smart_edit, "emphasis_points", lambda asset, ws: [])
    plan = _cut(_project([v], {"smart_edit": "tight", "music": "none", "punch_in": True}, "Flat"), words)
    assert [c.get("zoom", 1.0) for c in plan["clips"]] == [1.0, smart_edit.PUNCH_IN, 1.0]
    assert any("1 punch-in: your voice stays even after the cuts, so every other cut zooms in a little" in n
               for n in plan["notes"])
    monkeypatch.setattr(smart_edit, "emphasis_points", lambda asset, ws: [1.2])  # rises only before the first cut
    plan = _cut(_project([v], {"smart_edit": "tight", "music": "none", "punch_in": True}, "Early"), words)
    assert [c.get("zoom", 1.0) for c in plan["clips"]] == [1.0, smart_edit.PUNCH_IN, 1.0]
    monkeypatch.setattr(smart_edit, "emphasis_points", lambda asset, ws: None)  # no sound copy yet: the old rule
    plan = _cut(_project([v], {"smart_edit": "tight", "music": "none", "punch_in": True}, "Old"), words)
    assert [c.get("zoom", 1.0) for c in plan["clips"]] == [1.0, smart_edit.PUNCH_IN, 1.0]
    assert any("every other cut zooms in a little" in n for n in plan["notes"])


# ------------------------------------------------------------------ your taste
def _clip(cid: str, hook: float, **extra) -> dict:
    from clipfoundry.pipeline import virality

    factors = {k: 5.0 for k in virality.FACTORS}
    factors["hook"] = hook
    return {"id": cid, "project_id": "", "start": 0.0, "end": 30.0,
            "analysis": {"factors": factors, "viral_potential": 50 + 3 * hook,
                         "signals": {"question_open": hook > 5, "story": False, "hook_words": 1}}, **extra}


def test_a_clip_becomes_the_same_numbers_from_its_summary_and_from_a_result():
    from clipfoundry import taste
    from clipfoundry.pipeline import virality

    x = taste.features_from_summary(_clip("c", 9.0)["analysis"], 30.0)
    assert len(x) == len(taste.FEATURES) == len(virality.FACTORS) + 5 and all(0.0 <= v <= 1.0 for v in x)
    assert x[0] == 0.9 and x[-5] == pytest.approx(0.77) and x[-4] == pytest.approx(30 / 90) and x[-3] == 1.0
    assert taste.features_from_summary({}, 30.0) is None
    words, sents, loud, cands = _deep_inputs()
    _, results, _ = deep.evaluate_select(sents, words, loud, OPTS, JobContext(), "talk", cands)
    r = results[0]
    y = taste.features_from_result(r)
    assert y == taste.features_from_summary(virality.summary(r["analysis"]), r["end"] - r["start"])
    assert taste.features_from_result({"analysis": {}}) is None


def test_lessons_are_recorded_once_per_kind_and_a_change_of_mind_cancels_the_earlier_one(data):
    from clipfoundry import taste

    clip = _clip("c1", 8.0)
    assert taste.record(clip, "exported", "ws1")["value"] == 1.0
    assert taste.record(clip, "exported", "ws1") and len(taste.events("ws1")) == 1
    taste.record(clip, "deselected", "ws1")
    assert sorted(e["kind"] for e in taste.events("ws1")) == ["deselected", "exported"]
    taste.record(clip, "reselected", "ws1")
    assert sorted(e["kind"] for e in taste.events("ws1")) == ["exported", "reselected"]
    assert taste.record(clip, "liked", "ws1") is None and taste.record({"id": "x", "analysis": {}}, "exported", "ws1") is None
    assert taste.record({}, "exported", "ws1") is None
    st = taste.status("ws1")
    assert st["events"] == 2 and st["kept"] == 2 and st["left_out"] == 0 and not st["ready"]
    assert st["needed"] == {"events": taste.MIN_EVENTS - 2, "kept": taste.MIN_EACH - 2, "left_out": taste.MIN_EACH}
    assert st["preferences"] == [] and st["weight"] == taste.WEIGHT and taste.model("ws1") is None
    assert taste.brief_line("ws1") == "" and taste.apply([{"analysis": {}}], {"workspace_id": "ws1"}) == 0


def test_after_enough_lessons_the_taste_model_learns_what_you_keep_and_says_so(data):
    from clipfoundry import taste

    rng = np.random.default_rng(5)
    for k in range(9):
        taste.record(_clip(f"keep{k}", 7.5 + rng.random() * 2), "exported", "ws2")
        taste.record(_clip(f"drop{k}", 1.0 + rng.random() * 2), "deselected", "ws2")
    m = taste.model("ws2")
    assert m and m["n"] == 18 and m["positives"] == 9 and m["negatives"] == 9 and m["features"] == taste.FEATURES
    assert m["weights"][taste.FEATURES.index("hook")] > 0.3  # the hook decided, so it has the biggest say
    good = taste.predict(m, taste.features_from_summary(_clip("g", 9.0)["analysis"], 30.0))
    bad = taste.predict(m, taste.features_from_summary(_clip("b", 1.5)["analysis"], 30.0))
    assert good["p"] > 0.8 > 0.2 > bad["p"] and good["adjust"] >= 0.8 * taste.WEIGHT and bad["adjust"] <= -0.8 * taste.WEIGHT
    assert good["why"][0] == "a stronger hook" and bad["why"][0] == "a weaker hook"
    assert "a stronger hook" in taste.preferences(m)[0:2]
    st = taste.status("ws2")
    assert st["ready"] and st["events"] == 18 and st["by_kind"] == {"exported": 9, "deselected": 9} and st["trained_at"]
    assert taste.brief_line("ws2").startswith("The owner's own choices so far (18 of them): they keep clips with")
    assert taste.model("ws2") is m  # cached until the lessons change
    taste.record(_clip("keep9", 8.0), "published", "ws2")
    assert taste.model("ws2")["n"] == 19
    # every evaluated result gets a verdict, bounded and explained, and the Clip Score moves with it
    words, sents, loud, cands = _deep_inputs()
    _, results, _ = deep.evaluate_select(sents, words, loud, {**OPTS, "workspace_id": "ws2"}, JobContext(), "talk", cands)
    tasted = [r for r in results if r.get("taste")]
    assert tasted and all(-taste.WEIGHT <= r["taste"]["adjust"] <= taste.WEIGHT for r in tasted)
    moved = [r for r in tasted if abs(r["taste"]["adjust"]) >= 0.5]
    assert moved and all(any(line.startswith(f"{r['taste']['adjust']:+.1f} your taste") for line in r["explanation"])
                         for r in moved)
    # forgetting empties the lessons and the model
    assert taste.forget("ws2") == 19 and taste.model("ws2") is None and not taste.status("ws2")["ready"]
    assert taste.events("ws2") == []


def test_the_api_reports_the_meaning_model_and_your_taste_and_records_a_left_out_clip(client, monkeypatch):
    from clipfoundry import db, embedder, taste

    m = client.get("/api/ai/meaning").json()
    assert m["name"] == "all-MiniLM-L6-v2" and m["model"] == embedder.MODEL and not m["ready"] and m["enabled"]
    assert m["download_bytes"] == embedder.download_bytes() and m["task"] == {}
    assert client.post("/api/ai/meaning/remove").json()["ready"] is False
    monkeypatch.setattr(embedder, "in_cloud", lambda: False)
    monkeypatch.setattr(embedder, "_loaded", lambda: None)
    started = client.post("/api/ai/meaning/install").json()
    assert started["task"]["state"] == "running"
    for _ in range(200):
        got = client.get("/api/ai/meaning").json()
        if got["task"].get("state") != "running":
            break
        import time

        time.sleep(0.05)
    assert got["task"]["state"] == "error" and "online" in got["task"]["error"]  # the hub is a closed port here
    assert client.post("/api/ai/meaning/cancel").status_code == 200
    # the Memory page: lessons so far, and forgetting
    t = client.get("/api/taste").json()
    assert t["events"] == 0 and not t["ready"] and t["needed"]["events"] == taste.MIN_EVENTS and t["weight"] == taste.WEIGHT
    project = db.create_project("Talk", workspace_id="local", status="done")
    clip = db.create_clip(project["id"], start=0.0, end=30.0, selected=1, title="A", analysis=_clip("x", 8.0)["analysis"])
    assert client.patch(f"/api/clips/{clip['id']}", json={"selected": False}).status_code == 200
    rows = taste.events("local")
    assert [r["kind"] for r in rows] == ["deselected"] and rows[0]["clip_id"] == clip["id"]
    assert client.patch(f"/api/clips/{clip['id']}", json={"selected": False}).status_code == 200  # no change: no lesson
    assert len(taste.events("local")) == 1
    assert client.patch(f"/api/clips/{clip['id']}", json={"selected": True}).status_code == 200
    assert [r["kind"] for r in taste.events("local")] == ["reselected"]
    assert client.get("/api/taste").json()["events"] == 1
    assert client.delete("/api/taste").json()["events"] == 0 and taste.events("local") == []


# ------------------------------------------------------------------ the meaning model in story finding
def _topics(sents: list[dict], groups: list[int], seed: int = 0) -> semantic.Embeddings:
    """Fake meaning vectors: every sentence of a group sits near its group's direction (as sentences about one
    subject do), unrelated groups are orthogonal."""
    from clipfoundry import embedder

    rng = np.random.default_rng(seed)
    dirs = np.linalg.qr(rng.standard_normal((embedder.DIM, max(groups) + 1)))[0].T
    arr = np.vstack([dirs[g] + 0.35 * rng.standard_normal(embedder.DIM) / np.sqrt(embedder.DIM) for g in groups]
                    ).astype(np.float32)
    arr /= np.linalg.norm(arr, axis=1, keepdims=True)
    return semantic.Embeddings(arr, embedder.MODEL, 0.0)


def test_meaning_shifts_point_at_the_change_of_subject_and_only_with_the_meaning_model():
    from clipfoundry.pipeline import stories

    words, sents = _talk(COOKING + ENGINES)
    assert stories.meaning_shifts(sents, None) is None and stories.meaning_shifts(sents, semantic.embed_sentences(sents)) is None
    emb = _topics(sents, [0] * len(COOKING) + [1] * len(ENGINES))
    shifts, z = stories.meaning_shifts(sents, emb)
    gap = len(COOKING) - 1
    assert len(shifts) == len(sents) - 1 and int(np.argmin(z)) == gap and z[gap] <= -1.8 and shifts[gap] < 0.35
    assert stories.meaning_shifts(sents[:5], emb[:5]) is None  # too short to compare six against six


PARTY = ["The neighbours threw a garden party the week the roses finally bloomed.",
         "Every basket from our harvest went onto their long table by the fence.",
         "The tomatoes were sliced and the sunflowers stood in jars next to the compost bin.",
         "Somebody's kid found a beetle in the salad and screamed the whole street awake.",
         "We laughed until the shovel on the wall fell off its hook.",
         "By midnight the fence lights were the only thing in the garden still standing.",
         "The rake ended up in the pond and nobody owned up to it.",
         "That garden party is still the summer everyone talks about."]


def _two_stories(pause: float):
    """The garden story and the garden-party story: the same words, a different story, `pause` seconds between."""
    from test_full_stories import GARDEN, _sentences
    from story_fixtures import read_aloud

    from clipfoundry.pipeline import transcribe

    transcript, _ = read_aloud([("story", GARDEN), ("story", PARTY)], pauses={GARDEN[-1]: pause})
    return transcribe.flatten_words(transcript), _sentences(transcript), transcript["duration"], len(GARDEN)


def test_a_change_of_subject_the_words_do_not_show_counts_once_there_is_a_pause_too(monkeypatch):
    from clipfoundry import embedder
    from clipfoundry.pipeline import stories

    words, sents, duration, split_at = _two_stories(3.0)
    emb = _topics(sents, [0] * split_at + [1] * (len(sents) - split_at))
    gap = split_at - 1
    shifts, z = stories.meaning_shifts(sents, emb)
    assert int(np.argmin(z)) == gap and z[gap] <= -2.5 and shifts[gap] <= 0.25
    marks = stories.marks_of(sents)
    by_words = stories._boundary(sents, gap, 0, len(sents) - 1, marks)
    by_meaning = stories._boundary(sents, gap, 0, len(sents) - 1, marks, 0.0, (float(shifts[gap]), float(z[gap])))
    assert by_words["why"] == ["a 3.0 s pause"] and by_words["score"] < stories.THRESHOLD  # the words overlap
    assert by_meaning["why"] == ["a 3.0 s pause", "a change of topic"] and by_meaning["score"] >= stories.THRESHOLD
    plain = stories.propose(words, sents, duration, opts={"meaning_model": False})
    assert len(plain["items"]) == 1 and "meaning model" not in plain["method"] and plain["ai"] == {}
    monkeypatch.setattr(embedder, "embed_or_none", lambda texts, settings=None: np.asarray(emb)[:len(texts)])
    monkeypatch.setattr(semantic, "_baseline", lambda vecs, fallback: 0.0)
    split = stories.propose(words, sents, duration, opts={"meaning_model": True})
    assert [i["kind"] for i in split["items"]] == ["story", "story"] and split["ai"] == {"meaning_model": embedder.MODEL}
    assert split["method"].endswith("and the meaning model") and len(split["boundaries"]) == 1
    assert abs(split["boundaries"][0]["time"] - (sents[gap]["end"] + sents[split_at]["start"]) / 2) < 0.01
    # read straight through with no pause at all, a change of subject alone is never a boundary: it becomes a
    # place worth asking ClipForge AI about (the table-of-contents pass and the review below)
    words, sents, duration, split_at = _two_stories(0.15)
    emb = _topics(sents, [0] * split_at + [1] * (len(sents) - split_at))
    monkeypatch.setattr(embedder, "embed_or_none", lambda texts, settings=None: np.asarray(emb)[:len(texts)])
    assert len(stories.propose(words, sents, duration, opts={"meaning_model": True})["items"]) == 1
    _accepted, near, _chunks, _marks = stories.candidates(sents, duration, emb)
    asked = [b for b in near if b["after"] == split_at - 1]
    assert len(asked) == 1 and stories.NEAR <= asked[0]["score"] < stories.THRESHOLD and asked[0]["why"] == ["a change of topic"]


def test_short_posts_with_a_varying_silence_between_them_are_all_found_with_the_meaning_model(monkeypatch):
    """Six posts of about a minute each, titles read straight, 2.5 to 4.5 s of silence between posts and 0.3 to 0.9 s
    inside them: with so many breaks, the 97th percentile of the pauses is one of them, and the shortest breaks must
    still count as a long pause for this narrator when the meaning model sees the subject change."""
    import itertools
    import random

    from clipfoundry import embedder
    from clipfoundry.pipeline import stories, transcribe
    from clipfoundry.pipeline.text_utils import build_sentences
    from story_fixtures import REDDIT_VOCAB, TEMPLATES, _sentence_words

    titles = ["My sister keeps telling everyone I ruined her wedding.", "Am I wrong for leaving my neighbour on the balcony?",
              "My husband keeps inviting his mother on our date nights.", "My brother wants half of the car grandpa left me.",
              "My cousin thinks I ruined her wedding speech.", "Am I wrong for locking the balcony door all winter?"]
    topics = ["wedding", "balcony", "inlaws", "car", "wedding", "balcony"]
    for seed in range(1, 6):
        rng, cycle = random.Random(seed), itertools.cycle(TEMPLATES)
        posts = []
        for k, topic in enumerate(topics):
            body = []
            for _ in range(13):
                a, b, c = rng.sample(REDDIT_VOCAB[topic], 3)
                body.append(next(cycle).format(a=a, b=b, c=c) + ".")
            posts.append([titles[k], *body])
        segments, groups, t = [], [], 0.6
        for k, post in enumerate(posts):
            for n, text in enumerate(post):
                words, t_end = _sentence_words(text, t)
                segments.append({"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})
                groups.append(k)
                t = t_end + (rng.uniform(2.5, 4.5) if n == len(post) - 1 else rng.uniform(0.3, 0.9))
        transcript = {"language": "en", "duration": round(t + 2.0, 3), "source": "fixture", "segments": segments}
        words = transcribe.flatten_words(transcript)
        sents = build_sentences(words)
        assert len(sents) == len(groups)
        emb = _topics(sents, groups)
        monkeypatch.setattr(embedder, "embed_or_none", lambda texts, settings=None, emb=emb: np.asarray(emb)[:len(texts)])
        monkeypatch.setattr(semantic, "_baseline", lambda vecs, fallback: 0.0)
        found = stories.propose(words, sents, transcript["duration"], opts={"meaning_model": True})
        assert sum(1 for i in found["items"] if i["kind"] == "story") == 6, seed


def test_the_table_of_contents_pass_names_where_stories_begin_and_the_rules_follow(monkeypatch):
    from test_full_stories import GARDEN, TOLD, _two_topics

    from clipfoundry.pipeline import stories, transcribe

    # the second story starts with words that start a story ("Another time, ..."): a place worth the model's word
    transcript, sents = _two_topics(TOLD, repeat=2)
    words, duration = transcribe.flatten_words(transcript), transcript["duration"]
    first_told = 2 * len(GARDEN) - 1

    def answer(prompt: str) -> dict:
        if "List the numbers" in prompt:  # the table of contents: sentence numbers (0 and 999 are nonsense)
            return {"starts": [first_told, 0, 999]}
        places = re.findall(r"Place (\d+):.*?>>> marked: \"(.*?)\"", prompt, re.S)  # the review: place numbers
        return {"new_story": [int(n) for n, text in places if text.startswith(TOLD[0][:30])]}
    fake = _Fake(stories=answer)
    judge = stories.Judge(AI_OPTS, sents, complete=fake)
    accepted, near, _chunks, marks = stories.candidates(sents, duration)
    assert not any(b["after"] == first_told - 1 for b in accepted)
    accepted2, near2 = judge.scan(accepted, near, marks)
    assert judge.report["scanned"] == 1 and judge.report["parts"] == 1 and judge.report["problems"] == []
    found = [b for b in accepted2 if b["after"] == first_told - 1]
    assert len(found) == 1 and "ClipForge AI read a new story beginning here" in found[0]["why"]
    assert found[0]["score"] >= stories.THRESHOLD
    call = fake.calls[0]
    assert call["json_schema"] is stories.SCAN_SCHEMA and call["task"] == "stories" and f"{first_told} [" in call["prompt"]
    result = stories.propose(words, sents, duration, judge=stories.Judge(AI_OPTS, sents, complete=fake))
    assert [i["kind"] for i in result["items"]] == ["story", "story"] and "checked by ClipForge AI" in result["method"]
    assert result["ai"]["scanned"] == 1
    # an unreadable or failing answer leaves the rules' decision
    garbled = stories.Judge(AI_OPTS, sents, complete=_Fake(raw="chapter one"))
    assert garbled.scan(accepted, near, marks) == (accepted, near) and "not readable" in garbled.report["problems"][0]
    down = stories.Judge(AI_OPTS, sents, complete=_Fake(raise_=llm.ProviderError("down")))
    assert down.scan(accepted, near, marks) == (accepted, near) and down.report["problems"] == ["part 1 of 1: down"]
    # the model naming a place where nothing in the words starts a story (a change of subject only) splits nothing
    transcript, sents = _two_topics(repeat=2)
    words, duration = transcribe.flatten_words(transcript), transcript["duration"]

    def eager(prompt: str) -> dict:
        if "List the numbers" in prompt:
            return {"starts": [2 * len(GARDEN) - 1]}
        return {"new_story": [int(n) for n in re.findall(r"Place (\d+):", prompt)]}
    result = stories.propose(words, sents, duration, judge=stories.Judge(AI_OPTS, sents, complete=_Fake(stories=eager)))
    assert [i["kind"] for i in result["items"]] == ["story"]


# ------------------------------------------------------------------ the request plumbing
def test_the_built_in_model_gets_pictures_and_a_fixed_answer_shape(monkeypatch):
    import httpx

    from clipfoundry import builtin_ai

    monkeypatch.setattr(builtin_ai.server, "ensure", lambda settings: ("http://127.0.0.1:1/v1", "k"))
    monkeypatch.setattr(builtin_ai.server, "touch", lambda: None)
    sent = []

    def post(url, json=None, headers=None, timeout=None, trust_env=None):
        sent.append({"url": url, "body": json, "headers": headers, "timeout": timeout})
        return SimpleNamespace(status_code=200, text="", json=lambda: {"choices": [{"message": {"content": '{"ok": 1}'},
                                                                                   "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "post", post)
    schema = {"type": "object", "properties": {"ok": {"type": "integer"}}}
    out = builtin_ai.chat({}, "sys", "look", timeout=30, json_schema=schema, images=["data:image/jpeg;base64,AA"],
                          max_tokens=50)
    assert out == '{"ok": 1}' and sent[0]["url"].endswith("/chat/completions") and sent[0]["timeout"] == 30
    body = sent[0]["body"]
    assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
    assert body["messages"][1]["content"] == [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA"}},
                                              {"type": "text", "text": "look"}]
    assert body["max_tokens"] == 50 and body["messages"][0] == {"role": "system", "content": "sys"}
    builtin_ai.chat({}, "sys", "hello", json_object=True)
    assert sent[1]["body"]["response_format"] == {"type": "json_object"} and sent[1]["body"]["messages"][1]["content"] == "hello"
    builtin_ai.chat({}, "sys", "hello")
    assert "response_format" not in sent[2]["body"] and "max_tokens" not in sent[2]["body"]


def test_complete_passes_a_schema_and_pictures_through_to_the_built_in_model_only_when_given(monkeypatch):
    from clipfoundry import builtin_ai

    seen = []
    monkeypatch.setattr(builtin_ai, "chat", lambda s, system, prompt, **kw: seen.append(kw) or "{}")
    schema = {"type": "object"}
    llm.complete({"ai_provider": "builtin"}, "x", task="eyes", json_object=True, json_schema=schema,
                 images=["data:image/jpeg;base64,AA"], timeout=40, max_tokens=300)
    assert seen[0] == {"timeout": 40.0, "json_object": True, "max_tokens": 300, "json_schema": schema,
                       "images": ["data:image/jpeg;base64,AA"]}
    llm.complete({"ai_provider": "builtin"}, "x", json_object=True)
    assert seen[1] == {"timeout": 180.0, "json_object": True, "max_tokens": None}


def test_the_pipeline_options_know_whose_taste_to_learn(monkeypatch):
    from clipfoundry.pipeline import process

    opts = process._options({"id": "p1", "workspace_id": "ws9", "name": "Talk", "options": {}}, {"clip_count": 2})
    assert opts["workspace_id"] == "ws9" and opts["origin"] == "manual" and opts["clip_count"] == 2
    assert process._options({"id": "p2", "name": "Talk"}, {})["workspace_id"] == "local"


# ------------------------------------------------------------------ the research guides' rules (text_utils/virality)
CHAIN = ["We got to the lake early and then we set up the tent.",
         "And then we made breakfast, and after that we went for a swim.",
         "Then we packed up and drove home before dark."]
TURNS = ["We got to the lake early, but the tent was still in the garage.",
         "Which meant breakfast was a granola bar, until a neighbour lent us a stove.",
         "Turns out the swim was the best part, so we stayed until dark."]


def _score(lines: list[str]) -> dict:
    from clipfoundry import config
    from clipfoundry.pipeline import virality
    from test_core import flat_loudness

    words, sents = _talk(lines)
    feats = candidates.sentence_features(sents, words)
    return virality.analyze(0, len(sents) - 1, sents, feats, words, flat_loudness(words[-1]["end"]),
                            dict(config.DEFAULT_SETTINGS))


def test_a_story_told_as_an_and_then_chain_scores_below_the_same_story_with_turns():
    chain, turns = _score(CHAIN), _score(TURNS)
    assert chain["signals"]["episodic"] >= 2 and chain["signals"]["causal_pivots"] == 0
    assert turns["signals"]["causal_pivots"] >= 3
    assert turns["factors"]["curiosity"] > chain["factors"]["curiosity"]
    flag = next(f for f in chain["flags"] if f["id"] == "and_then")
    assert flag["severity"] == "warn" and "keep the viewer guessing" in flag["detail"]
    assert not any(f["id"] == "and_then" for f in turns["flags"])


def test_a_constrained_experiment_opener_counts_as_a_hook_and_a_chapter_filler_as_a_break():
    words, sents = _talk(["I spent 30 days eating only what I grew, here's what happened.",
                          "Furthermore, the second point is the soil."])
    f = candidates.sentence_features(sents, words)
    assert f[0]["hookw"] >= 2 and f[1]["transition"]


# ------------------------------------------------------------------ the real model (when a copy is at hand)
REAL = os.environ.get("CLIPFORGE_MEANING_MODEL_DIR", "")


@pytest.mark.skipif(not REAL or not (Path(REAL) / "model.onnx").is_file(), reason="CLIPFORGE_MEANING_MODEL_DIR unset")
def test_the_real_meaning_model_puts_paraphrases_together_and_strangers_apart(data, monkeypatch):
    pytest.importorskip("onnxruntime")
    from clipfoundry import embedder

    src = Path(REAL)
    files = {n: (p, (src / n).stat().st_size, hashlib.sha256((src / n).read_bytes()).hexdigest())
             for n, (p, _s, _h) in embedder.FILES.items()}
    monkeypatch.setattr(embedder, "FILES", files)
    folder = embedder.model_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for n in files:
        shutil.copyfile(src / n, folder / n)
    (folder / embedder.MARKER).write_text(json.dumps({"files": {n: f[2] for n, f in files.items()}}), encoding="utf-8")
    assert embedder.model_ready()
    emb = semantic.embed_texts(["The cat sat on the mat.", "A kitten rested on the rug.", "Quarterly tax returns are due.",
                                "Boil the pasta in salted water."], opts={"meaning_model": True})
    assert emb.model == embedder.MODEL
    same = semantic.cos_cal(emb, emb[0], emb[1])
    assert same > 0.4 > semantic.cos_cal(emb, emb[0], emb[2]) and same > semantic.cos_cal(emb, emb[1], emb[3])
