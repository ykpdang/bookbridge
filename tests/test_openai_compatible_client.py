import os
import unittest
from unittest.mock import MagicMock

from src.api.llm_client import create_llm_client
from src.api.ollama_client import OllamaClient
from src.api.openai_compatible_client import OpenAICompatibleClient


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _EnvGuard(unittest.TestCase):
    KEYS = [
        "OLLAMA_ENABLED",
        "LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY",
        "LLM_EMBED_MODEL", "LLM_CHAT_MODEL",
        "OPENAI_API_KEY", "OPENAI_BASE_URL",
    ]

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        for key in self.KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestOpenAICompatibleClient(_EnvGuard):
    def _local_client(self):
        os.environ["LLM_PROVIDER"] = "openai_compatible"
        os.environ["OLLAMA_ENABLED"] = "true"
        os.environ["LLM_BASE_URL"] = "http://llama:8080/v1"
        os.environ["LLM_EMBED_MODEL"] = "embed"
        os.environ["LLM_CHAT_MODEL"] = "chat"
        return OpenAICompatibleClient()

    def test_configured_states_and_auth(self):
        client = self._local_client()
        self.assertTrue(client.is_configured())
        self.assertNotIn("Authorization", client._headers())

        os.environ["LLM_API_KEY"] = "secret"
        self.assertEqual(client._headers()["Authorization"], "Bearer secret")

        os.environ.pop("LLM_API_KEY", None)
        cloud = OpenAICompatibleClient(provider="openai")
        self.assertFalse(cloud.is_configured())
        os.environ["OLLAMA_ENABLED"] = "true"
        os.environ["OPENAI_API_KEY"] = "sk-test"
        self.assertTrue(cloud.is_configured())

    def test_list_models_parses_ids(self):
        client = self._local_client()
        client.session = MagicMock()
        client.session.request.return_value = _FakeResp(200, {"data": [{"id": "chat"}, {"id": "embed"}]})
        self.assertEqual(client.list_models(), ["chat", "embed"])
        self.assertIn("/models", client.session.request.call_args.args[1])

    def test_embed_parses_batch_in_index_order(self):
        client = self._local_client()
        client.session = MagicMock()
        client.session.request.return_value = _FakeResp(
            200,
            {
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )
        self.assertEqual(client.embed(["a", "b"]), [[0.1, 0.2], [0.3, 0.4]])
        payload = client.session.request.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "embed")
        self.assertEqual(payload["input"], ["a", "b"])

    def test_judge_parses_chat_json(self):
        client = self._local_client()
        client.session = MagicMock()
        client.session.request.return_value = _FakeResp(
            200,
            {"choices": [{"message": {"content": '{"choice": 1, "confidence": 90}'}}]},
        )
        self.assertEqual(client.judge("Respond ONLY with JSON"), {"choice": 1, "confidence": 90})
        payload = client.session.request.call_args.kwargs["json"]
        self.assertEqual(payload["response_format"]["type"], "json_object")

    def test_schema_400_falls_back_to_json_object(self):
        client = self._local_client()
        client.session = MagicMock()
        client.session.request.side_effect = [
            _FakeResp(400),
            _FakeResp(200, {"choices": [{"message": {"content": '{"choice": 2}'}}]}),
        ]
        result = client.judge("JSON please", schema={"type": "object"})
        self.assertEqual(result, {"choice": 2})
        self.assertTrue(client._schema_format_unsupported)
        payload = client.session.request.call_args.kwargs["json"]
        self.assertEqual(payload["response_format"]["type"], "json_object")

    def test_bad_payload_and_network_errors_return_none(self):
        client = self._local_client()
        client.session = MagicMock()
        client.session.request.return_value = _FakeResp(200, {"data": []})
        self.assertIsNone(client.embed(["a"]))

        client.session.request.side_effect = RuntimeError("boom")
        self.assertIsNone(client.judge("JSON please"))


class TestLLMFactory(_EnvGuard):
    def test_factory_defaults_to_ollama(self):
        self.assertIsInstance(create_llm_client(), OllamaClient)

    def test_factory_selects_openai_compatible_aliases(self):
        os.environ["LLM_PROVIDER"] = "llama-swap"
        self.assertIsInstance(create_llm_client(), OpenAICompatibleClient)

    def test_factory_selects_openai(self):
        os.environ["LLM_PROVIDER"] = "openai"
        client = create_llm_client()
        self.assertIsInstance(client, OpenAICompatibleClient)
        self.assertEqual(client.provider, "openai")


if __name__ == "__main__":
    unittest.main()
