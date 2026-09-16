"""Minimal chat. Run: python -m streamlit run app.py"""
import logging
import streamlit as st
from backend import ChatBackend

st.set_page_config(page_title='ClimaCasa', page_icon='❄️', layout='centered')
st.title('❄️ ClimaCasa')
st.caption('Como podemos ajudar com seu ar-condicionado?')

if st.button('Nova conversa'):
    st.session_state.pop('backend', None)
    st.session_state.pop('chat', None)

if 'backend' not in st.session_state:
    st.session_state.backend = ChatBackend()
    st.session_state.chat = []

for message in st.session_state.chat:
    with st.chat_message(message['role']):
        st.markdown(message['content'])

if question := st.chat_input('Digite sua mensagem…'):
    st.session_state.chat.append({'role': 'user', 'content': question})
    with st.chat_message('user'):
        st.markdown(question)
    with st.chat_message('assistant'):
        with st.spinner('Consultando…'):
            try:
                answer = st.session_state.backend.answer(question)
            except Exception as exc:
                logging.getLogger(__name__).error('Chat request failed (%s)', type(exc).__name__)
                st.error('Não consegui concluir agora. Se você estava agendando, confirme o status antes de tentar novamente.')
            else:
                st.markdown(answer)
                st.session_state.chat.append({'role': 'assistant', 'content': answer})
