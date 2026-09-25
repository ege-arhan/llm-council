import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend import council, models, storage
from backend import main


class ComboTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_run_reads_the_current_9router_members(self):
        rosters = [
            ["ag/gemini", "nvidia/deepseek"],
            ["ag/gemini", "nvidia/deepseek", {"model": "gh/claude", "enabled": True}],
        ]
        original_client = httpx.AsyncClient

        def make_client(*args, **kwargs):
            def reply(request):
                self.assertEqual(request.url.path, "/api/combos")
                return httpx.Response(200, json={"combos": [{"name": "llm-council", "models": rosters.pop(0)}]})
            return original_client(transport=httpx.MockTransport(reply))

        with patch.object(models.config, "COUNCIL_COMBO", "llm-council"), \
             patch.object(models.config, "CHAIRMAN_MODEL", ""), \
             patch.object(models.config, "NINEROUTER_BASE_URL", "http://127.0.0.1:20128"), \
             patch.object(models.httpx, "AsyncClient", side_effect=make_client):
            self.assertEqual(await models.resolve_council_models(), ["ag/gemini", "nvidia/deepseek"])
            self.assertEqual(await models.resolve_council_models(), ["ag/gemini", "nvidia/deepseek", "gh/claude"])

    async def test_missing_combo_fails_instead_of_using_fallback(self):
        original_client = httpx.AsyncClient
        def make_client(*args, **kwargs):
            return original_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"combos": []})))
        with patch.object(models.config, "COUNCIL_COMBO", "llm-council"), \
             patch.object(models.httpx, "AsyncClient", side_effect=make_client):
            with self.assertRaisesRegex(RuntimeError, "bulunamadı"):
                await models.resolve_council_models()

    async def test_chairman_and_private_exclusions_are_not_debaters(self):
        original_client = httpx.AsyncClient
        def make_client(*args, **kwargs):
            return original_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                "combos": [{"name": "llm-council", "models": ["ag/gemini", "meta/contributor", "gh/claude", "cx/gpt-6-astra"]}]
            })))
        with patch.object(models.config, "COUNCIL_COMBO", "llm-council"), \
             patch.object(models.config, "CHAIRMAN_MODEL", "cx/gpt-6-astra"), \
             patch.object(models.config, "COUNCIL_EXCLUDE_MODELS", ["meta/contributor"]), \
             patch.object(models.config, "COUNCIL_EXCLUDE_PATTERNS", ["contributor"]), \
             patch.object(models.httpx, "AsyncClient", side_effect=make_client):
            self.assertEqual(await models.resolve_council_models(), ["ag/gemini", "gh/claude"])

    async def test_all_members_answer_and_review_independently(self):
        roster = ["ag/gemini", "nvidia/deepseek", "gh/claude"]
        calls = []

        async def parallel(member_models, messages, **kwargs):
            calls.append(list(member_models))
            return {model: {"content": f"{model} answer"} for model in member_models}

        async def judge(model, messages, **kwargs):
            return {"content": "Final synthesis"}

        with patch.object(council, "resolve_council_models", AsyncMock(return_value=roster)), \
             patch.object(council, "query_models_parallel", side_effect=parallel), \
             patch.object(council, "query_model", side_effect=judge):
            first, reviews, final, metadata = await council.run_full_council("Question")
        self.assertEqual(calls, [roster, roster])
        self.assertEqual(len(first), 3)
        self.assertEqual(len(reviews), 3)
        self.assertEqual(final["response"], "Final synthesis")
        self.assertEqual(metadata["configured_models"], roster)

    async def test_failed_member_is_reported_and_not_asked_to_review(self):
        roster = ["ag/gemini", "nvidia/deepseek"]
        calls = []

        async def parallel(member_models, messages, **kwargs):
            calls.append(list(member_models))
            return {model: {"content": "answer"} if model == "ag/gemini" else None for model in member_models}

        with patch.object(council, "resolve_council_models", AsyncMock(return_value=roster)), \
             patch.object(council, "query_models_parallel", side_effect=parallel), \
             patch.object(council, "query_model", AsyncMock(return_value={"content": "synthesis"})):
            _, _, final, metadata = await council.run_full_council("Question")
        self.assertEqual(calls, [roster])
        self.assertEqual(metadata["stage1_failed_models"], ["nvidia/deepseek"])
        self.assertTrue(final["degraded"])

    async def test_failed_chairman_uses_another_successful_member(self):
        answers = [{"model": "ag/gemini", "response": "A"}, {"model": "gh/claude", "response": "B"}]
        async def query(model, messages, **kwargs):
            return None if model == "ag/gemini" else {"content": "Synthesis from Claude"}
        with patch.object(council, "query_model", side_effect=query):
            final = await council.stage3_synthesize_final("Question", answers, [], "ag/gemini")
        self.assertEqual(final["model"], "gh/claude")
        self.assertTrue(final["degraded"])

    def test_follow_up_has_bounded_prior_context(self):
        previous = [
            {"role": "user", "content": "We are comparing two systems"},
            {"role": "assistant", "stage3": {"response": "System A is simpler"}},
        ]
        query = council.contextualize_query(previous, "What about cost?")
        self.assertIn("System A is simpler", query)
        self.assertTrue(query.endswith("What about cost?"))

    def test_rank_labels_work_beyond_26_members(self):
        self.assertEqual(council.response_label(26), "AA")
        self.assertEqual(council.parse_ranking_from_text("FINAL RANKING:\n1. Response AA\n2. Response B"),
                         ["Response AA", "Response B"])

    def test_reviewer_panel_is_bounded_and_provider_diverse(self):
        answers = [{"model": model, "response": "x"} for model in [
            "ag/one", "ag/two", "cx/one", "cx/two", "gh/one", "oc/one", "ocg/one", "nvidia/one", "nvidia/two"
        ]]
        self.assertEqual(council.select_reviewers(answers),
                         ["ag/one", "cx/one", "gh/one", "oc/one", "ocg/one", "nvidia/one"])

    def test_preferred_reviewers_are_selected_when_available(self):
        answers = [{"model": model, "response": "x"} for model in ["ag/fast", "ag/strong", "cx/strong", "ocg/strong", "nvidia/strong"]]
        with patch.object(council, "COUNCIL_MAX_REVIEWERS", 4), \
             patch.object(council, "COUNCIL_REVIEWER_PRIORITY", ["ag/strong", "cx/strong", "ocg/strong", "nvidia/strong"]):
            self.assertEqual(council.select_reviewers(answers), ["ag/strong", "cx/strong", "ocg/strong", "nvidia/strong"])


class StorageTests(unittest.TestCase):
    def test_private_atomic_storage_and_path_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DATA_DIR", directory):
            identifier = str(uuid.uuid4())
            storage.create_conversation(identifier)
            storage.add_assistant_message(identifier, [], [], {"response": "ok"}, {"configured_models": ["a/b"]})
            record = storage.get_conversation(identifier)
            self.assertEqual(record["messages"][0]["metadata"]["configured_models"], ["a/b"])
            self.assertEqual(Path(storage.get_conversation_path(identifier)).stat().st_mode & 0o777, 0o600)
            self.assertIsNone(storage.get_conversation("../../other"))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_agent_endpoint_returns_all_three_stages(self):
        result = ([{"model": "a/one", "response": "A"}], [],
                  {"model": "a/one", "response": "Synthesis"},
                  {"configured_models": ["a/one", "b/two"], "stage1_failed_models": ["b/two"]})
        with patch.object(main, "run_full_council", AsyncMock(return_value=result)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as client:
                response = await client.post("/api/council/ask", json={"content": "Question"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stage3"]["response"], "Synthesis")
        self.assertEqual(response.json()["metadata"]["stage1_failed_models"], ["b/two"])


if __name__ == "__main__":
    unittest.main()
