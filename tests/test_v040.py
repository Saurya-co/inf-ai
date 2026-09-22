"""v0.4.0 tests (stdlib unittest — no new deps, APK-safe).

Run: python -m unittest discover -s tests -v
Covers: RAG chunker/TF-IDF/block builder, doc_chunks store, full-text
retention in prepare_doc, KEK rekey chain, app-lock PIN hashing.
"""
import os
import tempfile
import unittest

from app.core import rag as rag_mod
from app.core.attachment_service import doc_block, prepare_doc
from app.core.rag import (
    TfidfIndex,
    build_rag_block,
    chunk_for_rag,
    tokenize,
)
from app.data.app_lock import hash_pin, new_salt, valid_pin, verify_pin
from app.data.chat_store import ChatStore
from app.data.key_store import KeyStore


class TestRagChunker(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(chunk_for_rag(""), [])

    def test_short_single_chunk(self):
        self.assertEqual(len(chunk_for_rag("hello world")), 1)

    def test_overlap_and_coverage(self):
        text = " ".join(f"word{i}" for i in range(2000))
        chunks = chunk_for_rag(text, size=1500, overlap=200)
        self.assertGreater(len(chunks), 3)
        # every word appears in at least one chunk
        joined = " ".join(chunks)
        for i in (0, 500, 1000, 1999):
            self.assertIn(f"word{i}", joined)

    def test_deterministic(self):
        text = " ".join(f"w{i % 50}" for i in range(2000))
        self.assertEqual(chunk_for_rag(text), chunk_for_rag(text))


class TestTfidf(unittest.TestCase):
    DOC = (
        "The project budget allocates fifty thousand to server costs. "
        "Server provisioning happens in March. "
        "The design team prefers blue color palettes for the mobile app. "
        "Mobile navigation uses a bottom bar with three tabs. "
        "Catering for the launch event includes vegan options."
    )

    def test_ranking(self):
        chunks = chunk_for_rag(self.DOC, size=120, overlap=20)
        idx = TfidfIndex(chunks)
        hits = idx.retrieve("server costs budget", k=2)
        self.assertTrue(hits)
        self.assertIn("server", hits[0][2].lower())

    def test_no_match(self):
        idx = TfidfIndex(["cats sit on mats", "dogs dig holes"])
        self.assertEqual(idx.retrieve("quantum entanglement", k=2), [])

    def test_empty_query(self):
        idx = TfidfIndex(["hello world"])
        self.assertEqual(idx.retrieve("   "), [])
        self.assertEqual(idx.retrieve(""), [])

    def test_tokenize_stops(self):
        self.assertNotIn("the", tokenize("the quick fox"))
        self.assertIn("quick", tokenize("the quick fox"))


class TestRagBlock(unittest.TestCase):
    def test_labels_and_budget(self):
        hits = [(0, 0.9, "alpha " * 500), (1, 0.5, "beta " * 500)]
        block, labels = build_rag_block("report.pdf", hits, budget=1000)
        self.assertEqual(labels, ["report.pdf §1"])  # second exceeds budget
        self.assertIn("[report.pdf §1]", block)
        self.assertIn("answer using ONLY", block)


class TestDocRetention(unittest.TestCase):
    def test_full_text_kept_for_rag(self):
        raw = ("lorem ipsum dolor sit amet " * 800).encode()  # ~21k chars
        att = prepare_doc("big.txt", raw)
        self.assertGreater(len(att.text or ""), 12_000)
        self.assertTrue(att.extra.get("truncated"))
        # plain path still injects only the head
        self.assertLessEqual(len(doc_block(att)), 12_000 + 200)

    def test_short_doc_whole(self):
        att = prepare_doc("a.txt", b"hello")
        self.assertFalse(att.extra.get("truncated"))
        self.assertIn("hello", doc_block(att))


class TestDocChunksStore(unittest.TestCase):
    def test_index_roundtrip_and_delete(self):
        store = ChatStore(db_path=":memory:")
        cid = store.create_conversation("T", "gemini", "m")
        n = store.index_doc_chunks(cid, "r.pdf", ["aaa", "bbb"])
        self.assertEqual(n, 2)
        self.assertEqual(store.get_doc_chunks(cid), {"r.pdf": ["aaa", "bbb"]})
        store.index_doc_chunks(cid, "r.pdf", ["ccc"])  # re-index replaces
        self.assertEqual(store.get_doc_chunks(cid), {"r.pdf": ["ccc"]})
        store.delete_conversation(cid)
        self.assertEqual(store.get_doc_chunks(cid), {})
        store.close()


class TestRekeyChain(unittest.TestCase):
    def test_legacy_to_kek(self):
        from app.data.kek_store import fernet_for_kek, legacy_fernet

        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                ks = KeyStore()  # legacy seed fernet
                ks.set_key("groq", "sk-rekey-me")
                with open(ks._path, encoding="utf-8") as fh:
                    raw_before = fh.read()
                self.assertIn("enc:gAAAAA", raw_before)
                new_f = fernet_for_kek(os.urandom(32))
                changed = ks.rekey(new_f)
                self.assertTrue(changed)
                self.assertEqual(ks.get_key("groq"), "sk-rekey-me")
                # idempotent re-run
                self.assertFalse(ks.rekey(new_f))
                # old fernet can no longer read the stored token directly
                from app.data.key_store import _try_decrypt

                stored = ks._mem["multiai.groq.key"]
                self.assertIsNone(_try_decrypt(legacy_fernet(), stored))
            finally:
                os.chdir(old)


class TestAppLock(unittest.TestCase):
    def test_pin_validation(self):
        self.assertTrue(valid_pin("1234"))
        self.assertTrue(valid_pin("12345678"))
        self.assertFalse(valid_pin("123"))
        self.assertFalse(valid_pin("123456789"))
        self.assertFalse(valid_pin("abcd"))
        self.assertFalse(valid_pin("12 34"))

    def test_hash_roundtrip(self):
        salt = new_salt()
        h = hash_pin("5678", salt)
        self.assertTrue(verify_pin("5678", salt, h))
        self.assertFalse(verify_pin("5679", salt, h))
        self.assertFalse(verify_pin("5678", new_salt(), h))


if __name__ == "__main__":
    unittest.main()
