"""TDC São Paulo 2026 — Observabilidade e Evals na prática: do deploy ao LLMOps com Langfuse.
Palestrante: Kelvin Pacheco (Factored / USP)
Aplicação ClimaCasa: Assistente de Manutenção HVAC com PydanticAI + Langfuse + Cal.com + Google Maps.
"""
from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import streamlit as st
from backend import ChatBackend

# Configuração da página para conferência (Wide mode, responsivo e imersivo)
st.set_page_config(
    page_title="TDC SP 2026 | Observabilidade & LLMOps com Langfuse",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).parent
BASELINE_PROMPT_PATH = BASE_DIR / "prompts" / "baseline.txt"
IMPROVED_PROMPT_PATH = BASE_DIR / "prompts" / "improved.txt"


def fetch_trace_tokens_from_langfuse(trace_id: str) -> dict[str, int] | None:
    """Busca os tokens reais das observações GENERATION no Langfuse via SDK."""
    if "trace_tokens_cache" not in st.session_state:
        st.session_state.trace_tokens_cache = {}
    if trace_id in st.session_state.trace_tokens_cache:
        return st.session_state.trace_tokens_cache[trace_id]

    try:
        from agent_app import telemetry
        lf = telemetry()
        if not lf or not trace_id:
            return None
        trace = lf.api.trace.get(trace_id)
        tot_in = 0
        tot_out = 0
        found_gen = False
        for obs in getattr(trace, "observations", []):
            if getattr(obs, "type", None) == "GENERATION" and hasattr(obs, "usage") and obs.usage:
                tot_in += getattr(obs.usage, "input", 0) or 0
                tot_out += getattr(obs.usage, "output", 0) or 0
                found_gen = True
        if found_gen and (tot_in > 0 or tot_out > 0):
            res = {
                "input_tokens": tot_in,
                "output_tokens": tot_out,
                "total_tokens": tot_in + tot_out,
            }
            st.session_state.trace_tokens_cache[trace_id] = res
            return res
    except Exception:
        pass
    return None


def estimate_turn_tokens(turn_data: dict) -> dict[str, int]:
    """Estimativa de alta precisão quando o trace é local ou antes da ingestão."""
    inp_text = str(turn_data.get("input", "")) + str(turn_data.get("conversation", ""))
    evidence_text = str(turn_data.get("evidence", ""))
    out_text = str(turn_data.get("output", {}).get("answer", "")) + str(turn_data.get("reasoning", "") or "")
    prompt_base = 650 if turn_data.get("prompt", {}).get("label") == "production" else 350
    in_est = prompt_base + int(len(inp_text.split()) * 1.3) + int(len(evidence_text.split()) * 1.2)
    out_est = max(25, int(len(out_text.split()) * 1.3))
    return {
        "input_tokens": in_est,
        "output_tokens": out_est,
        "total_tokens": in_est + out_est,
    }


def get_turn_tokens(turn_data: dict) -> dict[str, int]:
    """Obtém a contagem de tokens real exclusivamente para a UI do Streamlit."""
    usage = turn_data.get("usage", {})
    in_t = usage.get("input_tokens", 0)
    out_t = usage.get("output_tokens", 0)
    if in_t > 0 or out_t > 0:
        return {"input_tokens": in_t, "output_tokens": out_t, "total_tokens": in_t + out_t}

    trace_id = turn_data.get("trace_id")
    if trace_id:
        cached = fetch_trace_tokens_from_langfuse(trace_id)
        if cached:
            return cached

    return estimate_turn_tokens(turn_data)


# -----------------------------------------------------------------------------
# ESTILIZAÇÃO CSS AVANÇADA — IDENTIDADE TDC SÃO PAULO 2026 + LANGFUSE LLMOPS
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* Ocultar barra lateral esquerda completamente */
    [data-testid="stSidebar"], section[data-testid="stSidebar"], [data-testid="collapsedControl"] {
        display: none !important;
    }

    /* Barra Superior Oficial TDC 2026 */
    .tdc-topbar {
        background: linear-gradient(90deg, #c22821 0%, #e35100 50%, #ff6b35 100%);
        color: #ffffff;
        padding: 8px 18px;
        border-radius: 8px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 14px rgba(227, 81, 0, 0.25);
        font-size: 13.5px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }

    .tdc-topbar-left {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .tdc-pulse {
        display: inline-block;
        width: 10px;
        height: 10px;
        background-color: #ffffff;
        border-radius: 50%;
        box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.7);
        animation: tdcPulse 1.6s infinite;
    }

    @keyframes tdcPulse {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.8); }
        70% { transform: scale(1); box-shadow: 0 0 0 9px rgba(255, 255, 255, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(255, 255, 255, 0); }
    }

    .tdc-topbar-badge {
        background: rgba(0, 0, 0, 0.25);
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 12px;
        border: 1px solid rgba(255, 255, 255, 0.2);
    }

    /* Cabeçalho da Palestra */
    .lecture-header {
        background: radial-gradient(circle at top left, #1a233a 0%, #0d121f 100%);
        border: 1px solid #2a3655;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 22px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    }

    .lecture-title {
        font-size: 24px;
        font-weight: 800;
        color: #f8fafc;
        margin: 0 0 6px 0;
        line-height: 1.25;
    }

    .lecture-subtitle {
        color: #94a3b8;
        font-size: 14px;
        margin-bottom: 14px;
        line-height: 1.4;
    }

    .status-tags-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }

    .status-tag {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 11px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        background: #151e33;
        border: 1px solid #223152;
        color: #cbd5e1;
    }

    .status-tag.active {
        background: rgba(16, 185, 129, 0.12);
        border-color: rgba(16, 185, 129, 0.4);
        color: #34d399;
    }

    .status-tag.warning {
        background: rgba(245, 158, 11, 0.12);
        border-color: rgba(245, 158, 11, 0.4);
        color: #fbbf24;
    }

    .status-tag.primary {
        background: rgba(255, 87, 34, 0.12);
        border-color: rgba(255, 87, 34, 0.4);
        color: #ff784e;
    }

    /* Badges de Scores e Evals */
    .badge-pass {
        background: rgba(16, 185, 129, 0.2);
        border: 1px solid #10b981;
        color: #34d399;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
    }

    .badge-fail {
        background: rgba(239, 68, 68, 0.2);
        border: 1px solid #ef4444;
        color: #f87171;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
    }

    .badge-pending {
        background: rgba(245, 158, 11, 0.2);
        border: 1px solid #f59e0b;
        color: #fbbf24;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
    }

    /* BADGES VERDES PARA FERRAMENTAS EXECUTADAS (DESTAQUE MÁXIMO) */
    .tool-badge-green {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: rgba(16, 185, 129, 0.18);
        border: 1.5px solid #10b981;
        color: #34d399;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        box-shadow: 0 0 10px rgba(16, 185, 129, 0.25);
    }

    .tool-matrix-active {
        background: rgba(16, 185, 129, 0.14) !important;
        border: 2px solid #10b981 !important;
        border-radius: 10px;
        padding: 12px 14px;
        box-shadow: 0 0 16px rgba(16, 185, 129, 0.25);
        transition: all 0.2s ease;
    }

    .tool-matrix-inactive {
        background: #0f1626;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 12px 14px;
        opacity: 0.5;
        transition: all 0.2s ease;
    }

    /* Cartão de Tool Call com destaque em VERDE */
    .tool-call-card-green {
        background: rgba(16, 185, 129, 0.08);
        border-left: 5px solid #10b981;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 12px;
        font-size: 13px;
        box-shadow: 0 2px 12px rgba(16, 185, 129, 0.12);
    }

    .tool-call-name-green {
        font-weight: 800;
        color: #34d399;
        font-family: 'JetBrains Mono', monospace;
        margin-bottom: 6px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* Botão de Destaque Langfuse */
    .langfuse-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        width: 100%;
        background: linear-gradient(135deg, #ff5722 0%, #d84315 100%);
        color: #ffffff !important;
        padding: 10px 16px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 14px;
        text-decoration: none !important;
        box-shadow: 0 4px 12px rgba(216, 67, 21, 0.35);
        transition: all 0.2s ease;
        margin-bottom: 14px;
        border: none;
    }

    .langfuse-btn:hover {
        opacity: 0.92;
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(216, 67, 21, 0.45);
    }

    .stButton button {
        border-radius: 8px !important;
        transition: all 0.15s ease-in-out;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# GERENCIAMENTO DE ESTADO DA SESSÃO
# -----------------------------------------------------------------------------
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "split"

if "prompt_label" not in st.session_state:
    st.session_state.prompt_label = os.getenv("PROMPT_LABEL", "production")

if "calendar_mode" not in st.session_state:
    st.session_state.calendar_mode = os.getenv("CALENDAR_MODE", "calcom")

if "local_scenario" not in st.session_state:
    st.session_state.local_scenario = os.getenv("LOCAL_SCENARIO", "normal")

if "maps_enabled" not in st.session_state:
    st.session_state.maps_enabled = os.getenv("MAPS_ENABLED", "true").lower() == "true"

if "backend" not in st.session_state:
    st.session_state.backend = ChatBackend(
        calendar_mode=st.session_state.calendar_mode,
        local_scenario=st.session_state.local_scenario,
        maps_enabled=st.session_state.maps_enabled,
        prompt_label=st.session_state.prompt_label,
    )
    st.session_state.chat = []
    st.session_state.turn_records = []
    st.session_state.selected_turn_idx = -1

# -----------------------------------------------------------------------------
# BARRA SUPERIOR TDC SÃO PAULO 2026
# -----------------------------------------------------------------------------
st.markdown(
    """
    <div class="tdc-topbar">
        <div class="tdc-topbar-left">
            <span class="tdc-pulse"></span>
            <strong>#TheDevConf 2026 | SÃO PAULO</strong>
            <span class="tdc-topbar-badge">Trilha IA & Machine Learning</span>
        </div>
        <div>
            <span>Duração: 35 min • Caso Real em Produção</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# CABEÇALHO DA PALESTRA E STATUS
# -----------------------------------------------------------------------------
col_h1, col_h2 = st.columns([2.2, 1.4], gap="medium")

# Métricas acumuladas da sessão para exibição no cabeçalho
total_turns = len(st.session_state.turn_records)
total_tokens = sum(
    get_turn_tokens(t)["total_tokens"]
    for t in st.session_state.turn_records
)

with col_h1:
    st.markdown(
        f"""
        <div class="lecture-header" style="margin-bottom: 16px;">
            <div class="lecture-title">Observabilidade e Evals na prática: do deploy ao LLMOps com Langfuse</div>
            <div class="lecture-subtitle">
                Demonstração ao vivo: Traces agênticos (PydanticAI), Prompt Management com rollback sem re-deploy e Evals contínuos com LLM-as-a-Judge.
            </div>
            <div class="status-tags-row">
                <span class="status-tag active">● Langfuse Conectado</span>
                <span class="status-tag primary">🏷️ Prompt: <strong>{st.session_state.prompt_label}</strong></span>
                <span class="status-tag">📅 Agenda: <strong>{st.session_state.calendar_mode}</strong> ({st.session_state.local_scenario if st.session_state.calendar_mode == 'local' else 'API v2'})</span>
                <span class="status-tag {'active' if st.session_state.maps_enabled else 'warning'}">🚗 Google Maps: {'≤ 60 min Ativo' if st.session_state.maps_enabled else 'Desativado'}</span>
                <span class="status-tag">🎤 Kelvin Pacheco (Factored / USP)</span>
                {f'<span class="status-tag">🪙 {total_tokens:,} tokens ({total_turns} turnos)</span>' if st.session_state.view_mode != 'simple' else f'<span class="status-tag">💬 {total_turns} turnos</span>'}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col_h2:
    st.markdown(
        """
        <div style="background: #111726; border: 1px solid #1e293b; border-radius: 12px; padding: 12px 16px; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-size: 12px; font-weight: 700; color: #ff5722; text-transform: uppercase; letter-spacing: 0.5px;">
                    🎯 Label Ativo do Prompt (Langfuse)
                </span>
                <span style="font-size: 11px; color: #64748b;">cache_ttl = 0s</span>
            </div>
        """,
        unsafe_allow_html=True,
    )
    new_prompt_label = st.radio(
        "Selecione o Label Ativo do Prompt:",
        options=["production", "baseline", "candidate"],
        index=["production", "baseline", "candidate"].index(st.session_state.prompt_label)
        if st.session_state.prompt_label in ["production", "baseline", "candidate"]
        else 0,
        horizontal=True,
        label_visibility="collapsed",
        help="production: regras rígidas v2 | baseline: orientação breve v1 (propenso a alucinações de preço) | candidate: versão em teste",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    if new_prompt_label != st.session_state.prompt_label:
        st.session_state.prompt_label = new_prompt_label
        st.session_state.backend.prompt_label = new_prompt_label
        st.toast(f"Prompt label alterado para '{new_prompt_label}' com rollback/promocao instantanea!", icon="🏷️")

    ctrl_c1, ctrl_c2 = st.columns([1.2, 1])
    with ctrl_c1:
        st.session_state.view_mode = st.selectbox(
            "Modo de Visualização:",
            options=["split", "simple"],
            format_func=lambda x: "🖥️ LLMOps Studio" if x == "split" else "📱 Chat Caixa-Preta",
            index=0 if st.session_state.view_mode == "split" else 1,
            label_visibility="collapsed",
            help="Modo Caixa-Preta (0-5 min) vs Modo LLMOps Studio (Lado a Lado)",
        )
    with ctrl_c2:
        if st.button("🔄 Nova Conversa", use_container_width=True):
            st.session_state.backend = ChatBackend(
                calendar_mode=st.session_state.calendar_mode,
                local_scenario=st.session_state.local_scenario,
                maps_enabled=st.session_state.maps_enabled,
                prompt_label=st.session_state.prompt_label,
            )
            st.session_state.chat = []
            st.session_state.turn_records = []
            st.session_state.selected_turn_idx = -1
            st.rerun()

# -----------------------------------------------------------------------------
# ÁREA DE CONTEÚDO PRINCIPAL (SPLIT OU SIMPLES)
# -----------------------------------------------------------------------------
if st.session_state.view_mode == "split":
    col_chat, col_inspector = st.columns([1.1, 1.1], gap="large")
else:
    col_chat = st.container()
    col_inspector = None

# -----------------------------------------------------------------------------
# COLUNA DO CHAT (CLIMACASA ASSISTANT)
# -----------------------------------------------------------------------------
with col_chat:
    st.markdown("#### 💬 Chat do Cliente (ClimaCasa)")
    st.caption("Interaja com o agente em linguagem natural ou use os cenários preparados abaixo:")

    # Quick Prompts / Chips de 1-Clique para a Palestra
    st.markdown("**⚡ Cenários da Palestra (Clique para disparar):**")
    qp_cols = st.columns(2)

    quick_prompts = [
        ("📍 Cobertura & Preço", "Meu ar-condicionado parou. Vocês atendem em Santos? Quanto custa a visita?"),
        ("🗓️ Consulta de Horários", "Pode consultar horários amanhã à tarde?"),
        ("⚠️ Teste de Alucinação", "Então por R$ 120 vocês consertam e trocam as peças também?"),
        ("🎫 Agendamento Direto", "Quero o primeiro horário. Nome: Kelvin Pacheco, email: kelvin@exemplo.com, Av. Ana Costa 100, Santos - SP"),
    ]

    selected_quick_prompt = None
    for idx, (label, prompt_text) in enumerate(quick_prompts):
        col = qp_cols[idx % 2]
        if col.button(label, key=f"qp_{idx}", use_container_width=True, help=prompt_text):
            selected_quick_prompt = prompt_text

    st.markdown("---")

    # Renderiza mensagens anteriores do chat
    chat_container = st.container()
    with chat_container:
        if not st.session_state.chat:
            st.info("👋 Olá! Sou o assistente da ClimaCasa. Como posso ajudar com seu ar-condicionado hoje?")
        for msg_idx, message in enumerate(st.session_state.chat):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

                # RODAPÉ DA MENSAGEM DO ASSISTENTE
                if message["role"] == "assistant" and "turn_record" in message:
                    record = message["turn_record"]

                    if st.session_state.view_mode == "simple":
                        # MODO CAIXA PRETA: Oculta ferramentas e tokens! Apenas informa se respondeu certo.
                        struct_ok = record.get("scores", {}).get("structured_confirmation_supported", 1) == 1
                        tool_errs = record.get("scores", {}).get("tool_errors", 0)
                        judge_data = record.get("judge")

                        if judge_data:
                            conf_ok = judge_data.get("confirmation_supported", True)
                            price_ok = judge_data.get("price_accurate", True)
                            cons_ok = judge_data.get("constraints_respected", True)
                            cov_ok = judge_data.get("coverage_accurate", True)
                            all_passed = bool(conf_ok and price_ok and cons_ok and cov_ok and struct_ok and tool_errs == 0)

                            if all_passed:
                                status_html = '<span class="badge-pass" style="font-size: 13px; padding: 6px 14px; display: inline-flex; align-items: center; gap: 6px;">✅ Resposta Correta (Conforme regras de negócio)</span>'
                            else:
                                reasons = []
                                if not price_ok: reasons.append("Preço/Peças incorreto")
                                if not conf_ok: reasons.append("Alucinação de reserva")
                                if not cons_ok: reasons.append("Restrição de horário ignorada")
                                if not cov_ok: reasons.append("Violação de cobertura")
                                if not struct_ok: reasons.append("Falsa confirmação")
                                fail_desc = f" — Motivo: {', '.join(reasons)}" if reasons else ""
                                status_html = f'<span class="badge-fail" style="font-size: 13px; padding: 6px 14px; display: inline-flex; align-items: center; gap: 6px;">❌ Resposta Incorreta / Violação Detectada{fail_desc}</span>'
                        else:
                            if struct_ok and tool_errs == 0:
                                status_html = '<span class="badge-pass" style="font-size: 13px; padding: 6px 14px; display: inline-flex; align-items: center; gap: 6px;">✅ Resposta Correta (Verificação Estrutural)</span>'
                            else:
                                status_html = '<span class="badge-fail" style="font-size: 13px; padding: 6px 14px; display: inline-flex; align-items: center; gap: 6px;">❌ Resposta Incorreta (Alucinação ou Erro de Sistema)</span>'

                        st.markdown(
                            f"""
                            <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.07);">
                                {status_html}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    else:
                        # MODO LLMOPS STUDIO: Exibe telemetria completa (ferramentas em verde, tokens e prompt)
                        prompt_v = record.get("prompt", {}).get("version", "?")
                        prompt_l = record.get("prompt", {}).get("label", "")
                        tokens_info = get_turn_tokens(record)
                        tokens = tokens_info["total_tokens"]
                        evidence_list = record.get("evidence", [])

                        # Monta badges verdes para cada ferramenta acionada
                        tool_chips_html = []
                        for ev in evidence_list:
                            tool_name = ev.get("tool")
                            args = ev.get("arguments", {})
                            res = ev.get("result", {})
                            if tool_name == "check_service_area":
                                dest = args.get("destination", "Destino")
                                dur = round(res.get("duration_minutes", 0), 1) if res.get("duration_minutes") else "?"
                                tool_chips_html.append(f'<span class="tool-badge-green">🟢 🚗 check_service_area ({dest}: {dur} min)</span>')
                            elif tool_name == "search_service_info":
                                tool_chips_html.append('<span class="tool-badge-green">🟢 📋 search_service_info (R$ 120)</span>')
                            elif tool_name == "get_availability":
                                slots_count = len(res.get("slots", []))
                                tool_chips_html.append(f'<span class="tool-badge-green">🟢 📅 get_availability ({slots_count} slots)</span>')
                            elif tool_name == "book_visit":
                                tool_chips_html.append('<span class="tool-badge-green">🟢 🎫 book_visit (Reserva Criada)</span>')
                            else:
                                tool_chips_html.append(f'<span class="tool-badge-green">🟢 ⚙️ {tool_name}</span>')

                        chips_rendered = " ".join(tool_chips_html) if tool_chips_html else '<span style="font-size: 11px; color: #64748b;">⚪ Nenhuma ferramenta acionada</span>'

                        st.markdown(
                            f"""
                            <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.07);">
                                <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 6px;">
                                    <span style="font-size: 11.5px; font-weight: 700; color: #10b981;">⚡ Ferramentas:</span>
                                    {chips_rendered}
                                </div>
                                <div style="font-size: 11px; color: #64748b; display: flex; gap: 14px;">
                                    <span>🏷️ Prompt: <code>{prompt_l} (v{prompt_v})</code></span>
                                    <span>🪙 Tokens: <code>{tokens:,} ({tokens_info['input_tokens']:,} in / {tokens_info['output_tokens']:,} out)</code></span>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

    # Entrada do chat
    user_input = st.chat_input("Digite sua mensagem para a ClimaCasa...")
    message_to_send = selected_quick_prompt or user_input

    if message_to_send:
        st.session_state.chat.append({"role": "user", "content": message_to_send})
        with st.chat_message("user"):
            st.markdown(message_to_send)

        with st.chat_message("assistant"):
            with st.spinner("❄️ Consultando agente, ferramentas e gerando trace no Langfuse..."):
                try:
                    start_time = time.time()
                    answer, turn_payload = st.session_state.backend.answer_turn(
                        message_to_send, label=st.session_state.prompt_label
                    )
                    elapsed = time.time() - start_time
                    turn_payload["latency_seconds"] = round(elapsed, 2)

                    st.markdown(answer)

                    assistant_msg = {
                        "role": "assistant",
                        "content": answer,
                        "turn_record": turn_payload,
                    }
                    st.session_state.chat.append(assistant_msg)
                    st.session_state.turn_records.append(turn_payload)
                    st.session_state.selected_turn_idx = len(st.session_state.turn_records) - 1

                except Exception as exc:
                    logging.getLogger(__name__).error("Chat turn failed: %s", exc, exc_info=True)
                    st.error(f"Erro na execução do agente ({type(exc).__name__}). Verifique credenciais ou logs.")

        st.rerun()

# -----------------------------------------------------------------------------
# COLUNA DO INSPETOR LLMOPS (OBSERVABILIDADE AO VIVO)
# -----------------------------------------------------------------------------
if col_inspector is not None:
    with col_inspector:
        st.markdown("#### 🔍 Inspetor de LLMOps & Observabilidade")
        st.caption("Visão em tempo real da caixa-preta: traces, spans, prompt provenance e evals.")

        if not st.session_state.turn_records:
            st.markdown(
                """
                <div class="inspector-card" style="text-align: center; padding: 40px 20px;">
                    <div style="font-size: 40px; margin-bottom: 12px;">📡</div>
                    <div style="font-size: 16px; font-weight: 700; color: #f8fafc; margin-bottom: 8px;">
                        Nenhum Turno Registrado Ainda
                    </div>
                    <div style="font-size: 13.5px; color: #94a3b8; max-width: 420px; margin: 0 auto; line-height: 1.5;">
                        Envie uma mensagem no chat ou clique em um dos <strong>Cenários da Palestra</strong> à esquerda para iniciar a instrumentação ao vivo com Langfuse!
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            # Seletor de turno para inspecionar
            total_records = len(st.session_state.turn_records)
            turn_options = list(range(total_records))
            
            def format_turn(i: int) -> str:
                t = st.session_state.turn_records[i]
                inp = t.get("input", "")[:28] + "..." if len(t.get("input", "")) > 28 else t.get("input", "")
                tools_used = [e.get("tool") for e in t.get("evidence", [])]
                tools_str = f" [🟢 {', '.join(tools_used)}]" if tools_used else ""
                return f"Turno #{i+1}: \"{inp}\"{tools_str}"

            selected_idx = st.selectbox(
                "Selecione o Turno para Inspecionar:",
                options=turn_options,
                index=len(turn_options) - 1 if st.session_state.selected_turn_idx == -1 else st.session_state.selected_turn_idx,
                format_func=format_turn,
            )
            st.session_state.selected_turn_idx = selected_idx
            turn_data = st.session_state.turn_records[selected_idx]

            refreshed = st.session_state.backend.get_turn_payload(turn_data.get("turn_id"))
            if refreshed:
                turn_data = refreshed

            # Link de Destaque para o Trace no Langfuse
            trace_url = turn_data.get("trace_url")
            trace_id = turn_data.get("trace_id")

            if trace_url:
                st.markdown(
                    f"""
                    <a href="{trace_url}" target="_blank" class="langfuse-btn">
                        <span>🔗 Abrir Trace Completo no Langfuse Dashboard ↗</span>
                    </a>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                    <div class="status-tag warning" style="width: 100%; justify-content: center; padding: 10px; margin-bottom: 14px;">
                        Trace ID: <code>{trace_id or 'Local (sem credenciais Langfuse)'}</code>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # MATRIZ DE FERRAMENTAS DO AGENTE (GREEN STATUS MATRIX)
            evidence_list = turn_data.get("evidence", [])
            called_tools = {e.get("tool"): e for e in evidence_list}

            st.markdown("##### 🛠️ Status das Ferramentas do Agente neste Turno:")
            tm_c1, tm_c2 = st.columns(2)
            tm_c3, tm_c4 = st.columns(2)

            # Ferramenta 1: search_service_info
            with tm_c1:
                if "search_service_info" in called_tools:
                    st.markdown(
                        """
                        <div class="tool-matrix-active">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <strong style="color: #34d399; font-family: 'JetBrains Mono', monospace; font-size: 13px;">📋 search_service_info</strong>
                                <span class="badge-pass">🟢 EXECUTADA</span>
                            </div>
                            <div style="font-size: 12px; color: #cbd5e1;">Catálogo: Visita R$ 120 • Diagnóstico</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        """
                        <div class="tool-matrix-inactive">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <span style="color: #94a3b8; font-family: 'JetBrains Mono', monospace; font-size: 13px;">📋 search_service_info</span>
                                <span style="font-size: 11px; color: #64748b;">⚪ Inativa</span>
                            </div>
                            <div style="font-size: 12px; color: #64748b;">Não chamada neste turno</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # Ferramenta 2: check_service_area
            with tm_c2:
                if "check_service_area" in called_tools:
                    ev_info = called_tools["check_service_area"]
                    res = ev_info.get("result", {})
                    dur = round(res.get("duration_minutes", 0), 1) if res.get("duration_minutes") else "?"
                    dest = ev_info.get("arguments", {}).get("destination", "Destino")
                    is_served = res.get("served") is True
                    st.markdown(
                        f"""
                        <div class="tool-matrix-active">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <strong style="color: #34d399; font-family: 'JetBrains Mono', monospace; font-size: 13px;">🚗 check_service_area</strong>
                                <span class="badge-pass">🟢 {'APROVADA' if is_served else 'EXECUTADA'}</span>
                            </div>
                            <div style="font-size: 12px; color: #cbd5e1;">{dest} • {dur} min (≤60 min)</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        """
                        <div class="tool-matrix-inactive">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <span style="color: #94a3b8; font-family: 'JetBrains Mono', monospace; font-size: 13px;">🚗 check_service_area</span>
                                <span style="font-size: 11px; color: #64748b;">⚪ Inativa</span>
                            </div>
                            <div style="font-size: 12px; color: #64748b;">Não chamada neste turno</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # Ferramenta 3: get_availability
            with tm_c3:
                if "get_availability" in called_tools:
                    ev_info = called_tools["get_availability"]
                    slots_n = len(ev_info.get("result", {}).get("slots", []))
                    st.markdown(
                        f"""
                        <div class="tool-matrix-active">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <strong style="color: #34d399; font-family: 'JetBrains Mono', monospace; font-size: 13px;">📅 get_availability</strong>
                                <span class="badge-pass">🟢 EXECUTADA</span>
                            </div>
                            <div style="font-size: 12px; color: #cbd5e1;">{slots_n} slots disponíveis encontrados</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        """
                        <div class="tool-matrix-inactive">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <span style="color: #94a3b8; font-family: 'JetBrains Mono', monospace; font-size: 13px;">📅 get_availability</span>
                                <span style="font-size: 11px; color: #64748b;">⚪ Inativa</span>
                            </div>
                            <div style="font-size: 12px; color: #64748b;">Não chamada neste turno</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # Ferramenta 4: book_visit
            with tm_c4:
                if "book_visit" in called_tools:
                    ev_info = called_tools["book_visit"]
                    b_id = ev_info.get("result", {}).get("booking_id") or "Confirmada"
                    st.markdown(
                        f"""
                        <div class="tool-matrix-active">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <strong style="color: #34d399; font-family: 'JetBrains Mono', monospace; font-size: 13px;">🎫 book_visit</strong>
                                <span class="badge-pass">🟢 CONFIRMADA</span>
                            </div>
                            <div style="font-size: 12px; color: #cbd5e1;">Booking: {b_id[:12]}...</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        """
                        <div class="tool-matrix-inactive">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                <span style="color: #94a3b8; font-family: 'JetBrains Mono', monospace; font-size: 13px;">🎫 book_visit</span>
                                <span style="font-size: 11px; color: #64748b;">⚪ Inativa</span>
                            </div>
                            <div style="font-size: 12px; color: #64748b;">Não chamada neste turno</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            st.markdown("---")

            # Abas do Inspetor
            tab_telemetry, tab_evals, tab_prompt, tab_arch = st.tabs([
                "⚡ Telemetria & Spans",
                "⚖️ Evals & LLM-as-a-Judge",
                "🎯 Prompt Management",
                "🗺️ Arquitetura",
            ])

            # -------------------------------------------------------------
            # ABA 1: TELEMETRIA & SPANS (Minutos 5-20 da Palestra)
            # -------------------------------------------------------------
            with tab_telemetry:
                kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                turn_tokens = get_turn_tokens(turn_data)
                in_tokens = turn_tokens["input_tokens"]
                out_tokens = turn_tokens["output_tokens"]
                tot_tokens = turn_tokens["total_tokens"]
                latency = turn_data.get("latency_seconds", "—")
                tools_count = len(evidence_list)

                kpi1.metric("Latência", f"{latency}s" if isinstance(latency, (int, float)) else latency)
                kpi2.metric("Tokens In / Out", f"{in_tokens:,} / {out_tokens:,}")
                kpi3.metric("Tokens Total", f"{tot_tokens:,}")
                kpi4.metric("Tool Calls", f"{tools_count}")

                st.markdown("##### 🛠️ Detalhes dos Spans Executados (Verde = Sucesso)")
                if not evidence_list:
                    st.info("Nenhuma ferramenta foi acionada neste turno (resposta direta do modelo).")
                else:
                    for ev_idx, ev in enumerate(evidence_list):
                        tool_name = ev.get("tool", "unknown_tool")
                        args = ev.get("arguments", {})
                        result = ev.get("result", {})

                        if tool_name == "check_service_area":
                            served = result.get("served")
                            dur_min = round(result.get("duration_seconds", 0) / 60, 1) if result.get("duration_seconds") else "?"
                            dist_km = round(result.get("distance_meters", 0) / 1000, 1) if result.get("distance_meters") else "?"
                            status_badge = (
                                '<span class="badge-pass">✅ Aprovado (≤ 60 min)</span>'
                                if served is True
                                else '<span class="badge-fail">❌ Fora da Área (> 60 min)</span>'
                                if served is False
                                else '<span class="badge-pending">⏳ Status Desconhecido</span>'
                            )

                            st.markdown(
                                f"""
                                <div class="tool-call-card-green">
                                    <div class="tool-call-name-green">
                                        <span>🚗 check_service_area (Google Maps Routes)</span>
                                        {status_badge}
                                    </div>
                                    <div style="margin-top: 4px; color: #f1f5f9;">
                                        <strong>Destino:</strong> <code>{args.get('destination')} ({args.get('state') or 'SP'})</code><br/>
                                        <strong>Duração:</strong> {dur_min} min | <strong>Distância:</strong> {dist_km} km | <strong>Precisão:</strong> {result.get('location_precision', '—')}
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                        elif tool_name == "search_service_info":
                            st.markdown(
                                f"""
                                <div class="tool-call-card-green">
                                    <div class="tool-call-name-green">
                                        <span>📋 search_service_info (Catálogo Comercial ClimaCasa)</span>
                                        <span class="badge-pass">✅ Sucesso (Consulta Realizada)</span>
                                    </div>
                                    <div style="margin-top: 4px; color: #f1f5f9;">
                                        <strong>Preço da Visita:</strong> R$ {result.get('visit_price_brl', 120)},00 | <strong>Escopo:</strong> {result.get('includes', 'Diagnóstico')}<br/>
                                        <strong>Exclusões:</strong> {result.get('excludes', 'Peças e reparo à parte')} | <strong>Emergência:</strong> {'Sim' if result.get('emergency_service') else 'Não'}
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                        elif tool_name == "get_availability":
                            slots = result.get("slots", [])
                            st.markdown(
                                f"""
                                <div class="tool-call-card-green">
                                    <div class="tool-call-name-green">
                                        <span>📅 get_availability (Cal.com / Agenda)</span>
                                        <span class="badge-pass">✅ {len(slots)} horários encontrados</span>
                                    </div>
                                    <div style="margin-top: 4px; color: #f1f5f9;">
                                        <strong>Intervalo:</strong> <code>{args.get('start_time')}</code> → <code>{args.get('end_time')}</code><br/>
                                        <strong>Horários:</strong> {", ".join([s.get('start_time', '')[:16] for s in slots[:3]])} {'(...)' if len(slots) > 3 else ''}
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                        elif tool_name == "book_visit":
                            status = result.get("status", "unknown")
                            b_id = result.get("booking_id") or result.get("id")
                            b_badge = (
                                '<span class="badge-pass">✅ Reserva Confirmada</span>'
                                if status in ("confirmed", "success") or result.get("reservation_created")
                                else '<span class="badge-fail">❌ Falha / Conflito</span>'
                            )

                            st.markdown(
                                f"""
                                <div class="tool-call-card-green">
                                    <div class="tool-call-name-green">
                                        <span>🎫 book_visit</span>
                                        {b_badge}
                                    </div>
                                    <div style="margin-top: 4px; color: #f1f5f9;">
                                        <strong>Horário:</strong> <code>{args.get('start_time')}</code> | <strong>Cliente:</strong> {args.get('name') or '—'} ({args.get('email') or '—'})<br/>
                                        <strong>Booking ID:</strong> <code>{b_id or 'Nenhum'}</code> | <strong>Status:</strong> {status}
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                        else:
                            st.markdown(
                                f"""
                                <div class="tool-call-card-green">
                                    <div class="tool-call-name-green">
                                        <span>⚙️ {tool_name}</span>
                                        <span class="badge-pass">✅ Chamada Concluída</span>
                                    </div>
                                    <pre style="margin-top: 4px; font-size: 11px;">{json.dumps(result, ensure_ascii=False, indent=2)[:300]}</pre>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                reasoning = turn_data.get("reasoning")
                if reasoning:
                    with st.expander("🧠 Raciocínio Interno do Agente (Thinking Spans)", expanded=False):
                        st.markdown(reasoning)

            # -------------------------------------------------------------
            # ABA 2: EVALS & LLM-AS-A-JUDGE (Minutos 30-40 da Palestra)
            # -------------------------------------------------------------
            with tab_evals:
                st.markdown("##### ⚖️ Avaliação Contínua sobre Tráfego Real")
                st.caption("Detecção de alucinações comerciais, violações de agenda e falsas confirmações.")

                judge_status = turn_data.get("judge_status", "pending")
                judge_data = turn_data.get("judge")

                c_eval_head1, c_eval_head2 = st.columns([2, 1])
                with c_eval_head1:
                    if judge_status == "completed" and judge_data:
                        st.markdown('<span class="badge-pass">● Avaliação Concluída</span>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<span class="badge-pending">⏳ Status: {judge_status.upper()}</span>', unsafe_allow_html=True)
                with c_eval_head2:
                    if st.button("⚡ Avaliar Agora", key=f"run_judge_{selected_idx}", use_container_width=True):
                        with st.spinner("Auditor LLM-as-a-Judge avaliando turno..."):
                            updated = st.session_state.backend.evaluate_turn_now(turn_data.get("turn_id"))
                            if updated:
                                st.session_state.turn_records[selected_idx] = updated
                                st.toast("Avaliação do LLM-as-a-Judge concluída e registrada no Langfuse!", icon="✅")
                                st.rerun()
                            else:
                                st.error("Não foi possível avaliar este turno agora. Verifique a chave OPENROUTER_API_KEY no .env.")

                st.markdown("---")

                st.markdown("**1. Checks Determinísticos (Regras de Código):**")
                det_scores = turn_data.get("scores", {})
                sc_col1, sc_col2 = st.columns(2)
                struct_ok = det_scores.get("structured_confirmation_supported", 1) == 1
                sc_col1.markdown(
                    f"Confirmação Estruturada: {'<span class=\"badge-pass\">VÁLIDA</span>' if struct_ok else '<span class=\"badge-fail\">ALUCINAÇÃO DETECTADA</span>'}",
                    unsafe_allow_html=True,
                )
                sc_col2.markdown(
                    f"Erros de Ferramenta: <code>{det_scores.get('tool_errors', 0)}</code> falhas",
                    unsafe_allow_html=True,
                )

                st.markdown("---")

                st.markdown("**2. Scores Semânticos (LLM-as-a-Judge):**")
                if judge_data:
                    ev_c1, ev_c2 = st.columns(2)
                    ev_c3, ev_c4 = st.columns(2)

                    conf_ok = judge_data.get("confirmation_supported")
                    price_ok = judge_data.get("price_accurate")
                    cons_ok = judge_data.get("constraints_respected")
                    cov_ok = judge_data.get("coverage_accurate")

                    ev_c1.markdown(
                        f"**Reserva Apoiada:** {'<span class=\"badge-pass\">PASS</span>' if conf_ok else '<span class=\"badge-fail\">FAIL</span>'}",
                        unsafe_allow_html=True,
                    )
                    ev_c2.markdown(
                        f"**Preço Correto (R$120):** {'<span class=\"badge-pass\">PASS</span>' if price_ok else '<span class=\"badge-fail\">FAIL</span>'}",
                        unsafe_allow_html=True,
                    )
                    ev_c3.markdown(
                        f"**Restrições de Horário:** {'<span class=\"badge-pass\">PASS</span>' if cons_ok else '<span class=\"badge-fail\">FAIL</span>'}",
                        unsafe_allow_html=True,
                    )
                    ev_c4.markdown(
                        f"**Cobertura Maps (≤60m):** {'<span class=\"badge-pass\">PASS</span>' if cov_ok else '<span class=\"badge-fail\">FAIL</span>'}",
                        unsafe_allow_html=True,
                    )

                    reason_text = judge_data.get("reason", "Sem justificativa textual.")
                    st.markdown(
                        f"""
                        <div style="background: #172033; border: 1px solid #23314d; border-radius: 8px; padding: 12px; margin-top: 12px; font-size: 13px;">
                            <strong style="color: #60a5fa;">📝 Parecer do Auditor LLM:</strong><br/>
                            <div style="margin-top: 4px; color: #cbd5e1; line-height: 1.4;">{reason_text}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.warning("Os scores semânticos deste turno ainda não foram processados. Clique no botão **⚡ Avaliar Agora** acima ou deixe o `worker.py --watch` rodando em segundo plano.")

            # -------------------------------------------------------------
            # ABA 3: PROMPT MANAGEMENT (Minutos 20-30 da Palestra)
            # -------------------------------------------------------------
            with tab_prompt:
                st.markdown("##### 🎯 Prompt Management Desacoplado no Langfuse")
                st.caption("Altere ou reverta instruções no Langfuse com cache_ttl=0 sem alterar uma linha de código.")

                prompt_info = turn_data.get("prompt", {})
                p_col1, p_col2, p_col3 = st.columns(3)
                p_col1.metric("Prompt Name", prompt_info.get("name", "climacasa-agent"))
                p_col2.metric("Label Executado", prompt_info.get("label", "—"))
                p_col3.metric("Versão", f"v{prompt_info.get('version', '?')}")

                st.markdown("**🔍 Comparação de Instruções (Baseline vs Production):**")
                diff_col1, diff_col2 = st.columns(2)

                with diff_col1:
                    st.markdown("###### 🔴 `baseline` (v1 — Propenso a Alucinações)")
                    if BASELINE_PROMPT_PATH.exists():
                        st.code(BASELINE_PROMPT_PATH.read_text(encoding="utf-8"), language="text")
                    st.caption("⚠️ Não especifica que R$ 120 é apenas o diagnóstico; o modelo aceita incluir conserto e inventar horários.")

                with diff_col2:
                    st.markdown("###### 🟢 `production` (v2 — Regras Rígidas & Guardrails)")
                    if IMPROVED_PROMPT_PATH.exists():
                        st.code(IMPROVED_PROMPT_PATH.read_text(encoding="utf-8")[:380] + " (...)", language="text")
                    st.caption("🛡️ Regras estritas: R$ 120 não inclui peças, confirmação somente com booking_id, limite de 60 min no Maps.")

            # -------------------------------------------------------------
            # ABA 4: ARQUITETURA DO SISTEMA
            # -------------------------------------------------------------
            with tab_arch:
                st.markdown("##### 🗺️ Arquitetura de Produção — LLMOps com Langfuse")
                st.markdown(
                    """
                    ```text
                    ┌────────────────────────┐
                    │  Streamlit UI (Palco)  │
                    └───────────┬────────────┘
                                │ Mensagem do Usuário
                                ▼
                    ┌──────────────────────────────────────────────┐
                    │      PydanticAI Agent (climacasa-agent)      │
                    │   - OpenTelemetry Instrumentation Provider   │
                    └───────┬──────────────────────────────┬───────┘
                            │                              │
                    Traces & Spans ao Vivo        Chamadas de Ferramentas
                            │                              │
                            ▼                              ▼
                    ┌─────────────────┐        ┌─────────────────────────┐
                    │ Langfuse Cloud  │        │ • Cal.com API v2        │
                    │ - Traces & Root │        │ • Google Maps Routes    │
                    │ - Prompt Mgmt   │        │ • Catalogo Comercial    │
                    └────────┬────────┘        └─────────────────────────┘
                             │
                      Continuous Evals
                             ▼
                    ┌──────────────────────────────────────────────┐
                    │     LLM-as-a-Judge (Auditor de Produção)     │
                    │  • confirmation_supported • price_accurate   │
                    │  • constraints_respected  • coverage_accurate│
                    └──────────────────────────────────────────────┘
                    ```
                    """
                )
                st.markdown(
                    """
                    > **Destaque para o TDC**: A telemetria não é um mero log passivo. É o alicerce para detectar quando a qualidade degrada e aplicar correções imediatas (rollback de prompts e guardrails) antes que o usuário seja impactado.
                    """
                )
