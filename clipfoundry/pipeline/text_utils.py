"""Tokenisation, lexicons and sentence segmentation used by clip discovery."""
from __future__ import annotations

import math
import re
from collections import Counter

STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because been before being below between
both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from
further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his
how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my myself no nor
not of off on once only or other ought our ours ourselves out over own same shan't she she'd she'll she's should
shouldn't so some such than that that's the their theirs them themselves then there there's these they they'd
they'll they're they've this those through to too under until up very was wasn't we we'd we'll we're we've were
weren't what what's when when's where where's which while who who's whom why why's with won't would wouldn't you
you'd you'll you're you've your yours yourself yourselves um uh like yeah okay ok oh just really actually gonna
wanna gotta kind sort thing things stuff got get gets getting go going goes went know mean think said say says
lot lots also well right now even still much many one two maybe something anything everything way make made
""".split())

FILLERS = {"um", "uh", "erm", "hmm", "mm", "ah", "like", "yeah", "okay", "ok", "so", "you know", "i mean"}

# Starting a clip on these words usually means it depends on earlier context.
DANGLING_STARTS = {"and", "but", "so", "or", "because", "also", "then", "which", "that", "it", "this", "these",
                   "those", "he", "she", "they", "him", "her", "them", "his", "its", "there", "anyway",
                   "plus", "though", "although", "yeah", "right", "exactly", "well"}

HOOK_WORDS = {"secret", "secrets", "mistake", "mistakes", "never", "nobody", "everyone", "truth", "why", "how",
              "stop", "biggest", "worst", "best", "most", "only", "wrong", "crazy", "insane", "shocking",
              "problem", "reason", "real", "actually", "imagine", "listen", "warning", "don't", "must",
              "need", "should", "hack", "trick", "rule", "rules", "lesson", "tip", "tips", "surprising",
              "weird", "strange", "honest", "honestly", "unpopular", "controversial", "myth", "lie", "lies",
              "changed", "life", "money", "free", "fast", "easy", "hard", "impossible", "first", "last"}

HOOK_PHRASES = ["here's", "here is", "the truth", "the problem", "the reason", "the secret", "let me tell",
                "you need to", "you have to", "nobody talks", "no one talks", "what if", "did you know",
                "the biggest", "the most", "i never", "i remember", "the first time", "this is why",
                "this is how", "stop doing", "the key", "the one thing", "number one", "most people",
                "you won't believe", "the thing is", "let me explain", "i'll tell you", "here's why",
                "here's how", "the moment", "turns out", "what nobody"]

EMOTION_WORDS = {"love", "hate", "scared", "afraid", "fear", "angry", "happy", "sad", "cried", "cry", "crying",
                 "hurt", "pain", "amazing", "incredible", "unbelievable", "insane", "crazy", "terrible",
                 "horrible", "beautiful", "shocked", "shocking", "embarrassing", "proud", "excited", "furious",
                 "heartbroken", "lost", "died", "dead", "death", "fight", "fought", "win", "won", "fail",
                 "failed", "failure", "success", "dream", "dreams", "broke", "rich", "poor", "fired", "quit",
                 "hilarious", "funny", "wild", "massive", "huge", "literally", "absolutely", "completely"}

PAYOFF_PHRASES = ["that's why", "that is why", "which means", "the point is", "the lesson", "so the",
                  "and that's", "that's how", "that's what", "the answer", "turns out", "ended up",
                  "in the end", "finally", "at the end of the day", "bottom line", "so if you", "remember",
                  "the key is", "the trick is", "what i learned", "and it worked", "it changed", "because of that",
                  "and now", "since then", "that's the", "so yeah", "that is why", "that is the", "that is how",
                  "and that is", "the whole secret", "the secret is", "the takeaway", "so remember", "which is why",
                  "the moral", "beat being", "the best part"]

# Sentences that close one topic / open another (a clip should not run across them).
TRANSITION_PHRASES = ["anyway", "moving on", "move on", "let's move", "next week", "next time", "that's all",
                      "that is all", "on another note", "speaking of which", "by the way", "let's talk about",
                      "next up", "switching gears", "one more thing", "last thing", "before we get into",
                      "before we start", "let's get into", "let's jump", "back to"]

# Sentences that set something up (great openers, weak endings).
SETUP_PHRASES = ["let me tell you", "here's", "here is", "what if", "i'll tell you", "let me explain", "let me show",
                 "a story", "guess what", "the question is", "you know what", "i want to talk about"]

# Warm-up lines that make an opening slow ("so today I want to talk about...").
SLOW_OPEN_PHRASES = ["hey guys", "hi guys", "hello everyone", "hey everyone", "welcome back", "welcome to",
                     "what's up", "in this video", "in today's", "today i want", "today we're", "today we are",
                     "so today", "before we start", "before we begin", "before we get", "let's get started",
                     "let's get into it", "let me start", "first of all", "to start off", "alright so",
                     "all right so", "okay so", "ok so", "so basically", "i just wanted to", "i want to start",
                     "quick disclaimer", "real quick"]

# Openers that promise something the viewer only gets by watching on (open loops).
OPEN_LOOP_PHRASES = ["here's why", "here is why", "here's how", "here is how", "the reason", "the secret",
                     "what nobody", "no one tells", "nobody tells", "you won't believe", "guess what", "turns out",
                     "the truth", "the problem is", "the problem with", "most people", "the mistake", "the one thing",
                     "the biggest", "what happened", "wait for it", "let me tell you", "i'll tell you",
                     "here's the thing", "here's what", "what if", "did you know", "the key", "the craziest",
                     "you need to know", "stop doing"]

CONTRAST_WORDS = {"but", "actually", "instead", "however", "wrong", "except", "although", "yet", "surprisingly",
                  "unexpected", "opposite", "myth", "mistake", "wasn't", "isn't", "didn't", "doesn't"}

INTENSIFIERS = {"so", "really", "literally", "absolutely", "completely", "totally", "never", "always", "insane",
                "crazy", "extremely", "incredibly", "seriously", "honestly", "massive", "huge", "every", "nothing",
                "everything", "worst", "best"}

# The clip leans on something said before it.
BACKREF_PHRASES = ["as i said", "like i said", "as i mentioned", "like i mentioned", "i mentioned", "we talked about",
                   "we discussed", "as we saw", "earlier", "going back to", "back to what", "the other one",
                   "what you just said", "you just said", "like you said", "as you said", "that guy",
                   "that story"]

# A sentence that starts as a reply to someone else.
RESPONSE_STARTS = {"exactly", "yes", "yeah", "yep", "no", "nope", "right", "absolutely", "true", "correct",
                   "definitely", "totally", "agreed", "sure", "mhm", "precisely"}

# Promotional housekeeping that rarely works in a short.
PROMO_PHRASES = ["subscribe", "sponsor", "link in the description", "in the description", "patreon",
                 "promo code", "discount code", "hit the bell", "smash that like", "check out my"]

# Words too generic to be useful hashtags.
GENERIC_WORDS = set("""
zero one two three four five six seven eight nine ten eleven twelve twenty thirty forty fifty hundred thousand
million billion first second third last next week weeks month months year years day days today tomorrow yesterday
time times will would could should might must shall people person thing things everything nothing something
anything every single whole worst best better good great bad little much many more most less least lot always
never sometimes usually often really very pretty quite start started starting make made makes making take took
taken takes want wanted wants need needed needs come came comes coming give gave given look looked looking
work worked working talk talked talking tell told telling said ask asked asking thought feel felt keep kept
simply just only still even ever basically literally actually probably definitely maybe exactly whole
""".split())

STORY_MARKERS = ["i was", "we were", "one day", "when i", "i remember", "back when", "years ago", "last year",
                 "there was", "i had", "i went", "i got", "my first", "so i", "then i", "she said", "he said",
                 "they said", "told me", "happened"]

CATEGORY_LEXICON = {
    "Story": STORY_MARKERS + ["happened", "remember", "ago", "suddenly", "then"],
    "Educational": ["how to", "step", "tip", "tips", "learn", "because", "reason", "means", "example", "research",
                    "study", "data", "the key", "works", "explain", "understand", "method", "strategy", "why"],
    "Motivational": ["you can", "never give up", "believe", "discipline", "mindset", "goal", "goals", "dream",
                     "success", "hard work", "keep going", "grow", "growth", "change your", "your life"],
    "Funny": ["haha", "laugh", "laughing", "joke", "funny", "hilarious", "ridiculous", "[laughter]", "lol",
              "dumb", "stupid"],
    "Opinion": ["i think", "honestly", "overrated", "underrated", "wrong", "unpopular", "controversial",
                "should", "shouldn't", "i believe", "in my opinion", "hot take", "disagree"],
    "Emotional": ["love", "lost", "cried", "scared", "hurt", "heart", "family", "miss", "died", "afraid", "alone"],
    "Business": ["money", "business", "revenue", "sales", "customers", "startup", "company", "profit", "market",
                 "invest", "price", "clients", "brand", "marketing"],
}

WORD_RE = re.compile(r"[a-z0-9']+")
ABBREV = {"mr.", "mrs.", "ms.", "dr.", "vs.", "etc.", "e.g.", "i.e.", "st.", "jr.", "sr.", "u.s.", "no."}


def tokens(text: str) -> list[str]:
    return WORD_RE.findall(text.lower().replace("’", "'"))


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 2 and not t.isdigit()]


def count_phrases(text_lower: str, phrases: list[str]) -> int:
    return sum(1 for p in phrases if p in text_lower)


def ends_sentence(word: str) -> bool:
    w = word.strip().lower()
    return w.endswith((".", "?", "!", "…", '."', '?"', '!"')) and w not in ABBREV


def build_sentences(words: list[dict], max_words: int = 45) -> list[dict]:
    """Group timed words into sentence-like units with natural boundaries."""
    sentences: list[dict] = []
    cur: list[int] = []

    def flush() -> None:
        if not cur:
            return
        i0, i1 = cur[0], cur[-1]
        text = " ".join(words[i]["w"] for i in cur)
        sentences.append({"i0": i0, "i1": i1, "start": words[i0]["start"], "end": words[i1]["end"],
                          "text": text, "n": len(cur)})
        cur.clear()

    for i, w in enumerate(words):
        cur.append(i)
        gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 99.0
        text = w["w"]
        if (
            ends_sentence(text)
            or gap > 1.2
            or (len(cur) >= max_words * 0.6 and (text.endswith((",", ";", ":")) or gap > 0.45))
            or len(cur) >= max_words
        ):
            flush()
    flush()
    return sentences


def clean_text(text: str) -> str:
    text = re.sub(r"\b(um+|uh+|erm|hmm+)\b[,.]?\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tf_vector(text: str) -> Counter:
    return Counter(content_tokens(text))


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def keywords(text: str, global_df: Counter | None = None, n_docs: int = 1, top: int = 6) -> list[str]:
    tf = tf_vector(text)
    scored = []
    for term, f in tf.items():
        if len(term) < 4 or term in GENERIC_WORDS or "'" in term:
            continue
        if f < 2 and term.endswith(("ed", "ly", "ing")):
            continue  # verb/adverb forms make weak hashtags
        idf = math.log((n_docs + 1) / (1 + (global_df or {}).get(term, 0))) + 1 if global_df else 1.0
        scored.append((f * idf * (1.5 if f >= 2 else 1.0) * (1.15 if len(term) >= 6 else 1.0), term))
    scored.sort(reverse=True)
    return [t for _, t in scored[:top]]
