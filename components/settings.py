"""
Settings Component — Per-agent LLM provider/key configuration.
Keys live only in st.session_state — never persisted to disk.
"""

import streamlit as st
from typing import Optional
from utils.llm_factory import (
    create_llm,
    validate_key,
    get_available_providers,
    get_default_model,
    AgentLLMConfig,
    ProviderName,
)


AGENTS = [
    ("researcher", "🔬", "Researcher", "Decomposes query into sub-questions"),
    ("web_searcher", "🔍", "Web Searcher", "Searches and fetches web content"),
    ("analyst", "📊", "Analyst", "Synthesizes findings, scores relevance"),
    ("summarizer", "📝", "Summarizer", "Writes final report with citations"),
]


def init_session_state():
    """Initialize session state for LLM config."""
    if "llm_config" not in st.session_state:
        st.session_state.llm_config = {}
    if "use_global_key" not in st.session_state:
        st.session_state.use_global_key = False
    if "global_key" not in st.session_state:
        st.session_state.global_key = ""
    if "global_provider" not in st.session_state:
        st.session_state.global_provider = "groq"


def render_settings():
    """Render the full settings view."""
    init_session_state()

    st.markdown("## ⚙️ Agent Configuration")
    st.caption("Each agent can use a different provider/model. Keys live **only in this browser session** — nothing is saved to disk.")

    # Global key toggle
    col1, col2 = st.columns([1, 3])
    with col1:
        use_global = st.checkbox(
            "Use one key for all agents",
            value=st.session_state.use_global_key,
            key="use_global_key_toggle",
        )
        st.session_state.use_global_key = use_global

    if use_global:
        with col2:
            providers = get_available_providers()
            if not providers:
                st.error("No LLM providers installed. Check requirements.txt")
                return

            global_provider = st.selectbox(
                "Provider",
                providers,
                index=providers.index(st.session_state.global_provider) if st.session_state.global_provider in providers else 0,
                key="global_provider_select",
            )
            st.session_state.global_provider = global_provider

            default_model = get_default_model(global_provider)
            global_key = st.text_input(
                f"{global_provider.title()} API Key",
                type="password",
                value=st.session_state.global_key,
                placeholder=f"Enter {global_provider} API key...",
                key="global_key_input",
            )
            st.session_state.global_key = global_key

            # Validate global key
            if global_key:
                with st.spinner("Validating key..."):
                    is_valid, error = validate_key(global_provider, global_key, default_model)
                if is_valid:
                    st.success("✅ Key validated")
                else:
                    st.error(f"❌ Invalid key: {error}")

            st.info(f"Default model: `{default_model}` (change per-agent below if needed)")

    st.divider()

    # Per-agent config
    st.markdown("### Per-Agent Settings")
    st.caption("Override provider/model per agent. Global key used if toggle above is ON and agent key is empty.")

    for agent_key, icon, name, desc in AGENTS:
        _render_agent_row(agent_key, icon, name, desc)

    st.divider()
    _render_config_summary()


def _render_agent_row(agent_key: str, icon: str, name: str, desc: str):
    """Render a single agent configuration row."""
    config = st.session_state.llm_config.get(agent_key, AgentLLMConfig())
    providers = get_available_providers()

    with st.container(border=True):
        # Header
        col_icon, col_name, col_status = st.columns([0.5, 3, 1.5])
        with col_icon:
            st.markdown(f"<div style='font-size:1.5rem'>{icon}</div>", unsafe_allow_html=True)
        with col_name:
            st.markdown(f"**{name}**")
            st.caption(desc)
        with col_status:
            _render_status_dot(agent_key, config)

        # Provider + Model
        col_prov, col_model = st.columns(2)
        with col_prov:
            provider = st.selectbox(
                "Provider",
                providers,
                index=providers.index(config.provider) if config.provider in providers else 0,
                key=f"provider_{agent_key}",
                label_visibility="collapsed",
            )
        with col_model:
            default_model = get_default_model(provider)
            model = st.text_input(
                "Model",
                value=config.model or default_model,
                placeholder=default_model,
                key=f"model_{agent_key}",
                label_visibility="collapsed",
            )

        # API Key (hidden if using global)
        if not st.session_state.use_global_key:
            api_key = st.text_input(
                "API Key",
                type="password",
                value=config.api_key,
                placeholder=f"{provider} API key...",
                key=f"key_{agent_key}",
                label_visibility="collapsed",
            )
        else:
            api_key = ""
            st.caption("🔗 Using global key" if st.session_state.global_key else "⚠️ No global key set")

        # Save button
        if st.button("Save", key=f"save_{agent_key}", use_container_width=True):
            new_config = AgentLLMConfig(
                provider=provider,
                api_key=api_key,
                model=model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            st.session_state.llm_config[agent_key] = new_config

            # Validate
            key_to_check = api_key or (st.session_state.global_key if st.session_state.use_global_key else "")
            if key_to_check:
                with st.spinner("Validating..."):
                    is_valid, error = validate_key(provider, key_to_check, model)
                if is_valid:
                    st.success("✅ Saved & validated")
                else:
                    st.error(f"❌ Saved but invalid: {error}")
            else:
                st.warning("⚠️ Saved (no key provided)")
            st.rerun()


def _render_status_dot(agent_key: str, config: AgentLLMConfig):
    """Render validation status dot."""
    key_to_check = config.api_key or (st.session_state.global_key if st.session_state.use_global_key else "")

    if not key_to_check:
        st.markdown(
            '<span class="status-dot untested" title="No key provided"></span> No key',
            unsafe_allow_html=True,
        )
        return

    provider = config.provider
    model = config.model or get_default_model(provider)

    # Check cached validation
    cache_key = f"val_{agent_key}_{provider}_{key_to_check[:8]}"
    if cache_key in st.session_state:
        is_valid, _ = st.session_state[cache_key]
    else:
        is_valid, _ = validate_key(provider, key_to_check, model)
        st.session_state[cache_key] = (is_valid, "")

    if is_valid:
        st.markdown(
            '<span class="status-dot valid" title="Valid key"></span> Valid',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="status-dot invalid" title="Invalid key"></span> Invalid',
            unsafe_allow_html=True,
        )


def _render_config_summary():
    """Show current configuration summary."""
    with st.expander("📋 Configuration Summary", expanded=False):
        if st.session_state.use_global_key:
            st.markdown(f"**Global:** {st.session_state.global_provider} — `{get_default_model(st.session_state.global_provider)}`")
            if st.session_state.global_key:
                st.markdown(f"Key: `{st.session_state.global_key[:8]}...`")
        else:
            for agent_key, _, name, _ in AGENTS:
                config = st.session_state.llm_config.get(agent_key, AgentLLMConfig())
                key_preview = config.api_key[:8] + "..." if config.api_key else "(none)"
                st.markdown(f"**{name}:** {config.provider} — `{config.model or get_default_model(config.provider)}` — Key: `{key_preview}`")


def get_agent_llm(agent_key: str):
    """Get LLM instance for an agent using current session config."""
    return create_llm(
        agent_key,
        use_global_key=st.session_state.use_global_key,
        global_key=st.session_state.global_key,
    )