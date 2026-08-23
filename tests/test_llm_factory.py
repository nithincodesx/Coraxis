"""
Unit tests for LLM factory formatting and key resolution.
Usage: python -m unittest discover tests
"""

import unittest
from utils.llm_factory import format_model_string, get_default_model, _resolve_key, AgentLLMConfig

class TestLLMFactory(unittest.TestCase):

    def test_format_model_string_prefixes(self):
        self.assertEqual(format_model_string("groq", "llama-3.1-8b-instant"), "groq/llama-3.1-8b-instant")
        self.assertEqual(format_model_string("groq", "groq/llama-3.1-8b-instant"), "groq/llama-3.1-8b-instant")
        self.assertEqual(format_model_string("gemini", "gemini-1.5-flash"), "gemini/gemini-1.5-flash")
        self.assertEqual(format_model_string("openai", "gpt-4o-mini"), "openai/gpt-4o-mini")

    def test_default_models(self):
        self.assertEqual(get_default_model("groq"), "llama-3.1-8b-instant")
        self.assertEqual(get_default_model("gemini"), "gemini-1.5-flash")
        self.assertEqual(get_default_model("openai"), "gpt-4o-mini")

    def test_resolve_key_precedence(self):
        cfg = AgentLLMConfig(provider="groq", api_key="agent_key_123")
        # Global key active
        resolved = _resolve_key(cfg, use_global=True, global_key="global_key_999")
        self.assertEqual(resolved, "global_key_999")
        
        # Agent key fallback when global is not used
        resolved_agent = _resolve_key(cfg, use_global=False, global_key="")
        self.assertEqual(resolved_agent, "agent_key_123")

if __name__ == "__main__":
    unittest.main()
