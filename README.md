# ClimaCasa — Observabilidade e Evals na prática

## Chat simples (entrada principal)

`app.py` agora mostra somente o chat e o botão **Nova conversa**, em português.
Não exibe trace IDs, JSON, métricas, scores, seleção de prompts ou controles de falha.
A integração existente continua no backend Python (`backend.py` → `agent_app.py`).
UI e backend rodam no mesmo processo; não é necessário subir uma API HTTP separada.

Após instalar requirements e preencher `.env`:

```bash
python -m streamlit run app.py
```

Abra http://localhost:8501 e pergunte **“Vocês atendem em Santos?”**.
O backend usa Google Maps, Cal.com e Langfuse conforme as credenciais configuradas.
Para evals contínuos, mantenha `python worker.py --watch` em outro terminal.
Abra o projeto Langfuse em outra aba e procure `maintenance-request`; cada conversa tem um session_id próprio.

Configure no `.env` e reinicie o app ao mudar essas opções:

```env
CALENDAR_MODE=calcom
MAPS_ENABLED=true
PROMPT_LABEL=production
LOCAL_SCENARIO=normal
```

Para ensaio com agenda fictícia, use `CALENDAR_MODE=local`. `LOCAL_SCENARIO` aceita normal,
conflict ou timeout. Para isolar o calendário sem bloqueio de cobertura, use `MAPS_ENABLED=false`.
A ferramenta Maps continua disponível para perguntas de cobertura, conforme explicado abaixo.
**Nova conversa** limpa o histórico do chat e cria nova sessão; não cancela reservas existentes.
O histórico completo do agente (incluindo tool calls/returns) permanece isolado por sessão Streamlit.


Demo para TDC 2026: agente de manutenção em **Python + PydanticAI**, chat em Streamlit,
Langfuse para traces/prompt management/scores e **Cal.com API v2 para buscar horários e agendar**.
Empresa, catálogo e agenda local são fictícios. As respostas ao vivo são de um LLM real.

## Começar

Recomendado Python 3.12. No terminal, dentro desta pasta:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

No Windows, ative com `.venv\Scripts\activate`.
Preencha OPENROUTER_API_KEY. Langfuse e Cal.com exigem suas próprias credenciais; não são incluídas.

```bash
python -m streamlit run app.py
```

Abra http://localhost:8501. A agenda local funciona sem Cal.com. Sem chaves Langfuse,
o chat usa prompts locais, mostra resultados localmente e não envia traces.
Para operar totalmente sem LLM/rede, execute os testes com modelos substitutos; não há chat offline disfarçado de IA real.

## Configurar Cal.com (API v2)

1. Crie ou acesse sua conta no [Cal.com](https://cal.com).
2. Obtenha uma API Key em **Settings > Developer > API Keys**.
3. Configure no `.env`:
   ```env
   CALENDAR_MODE=calcom
   CALCOM_API_KEY=cal_live_...
   ```
4. Execute `python setup_calcom.py` para listar os tipos de evento da sua conta.
5. Copie o `id` numérico do evento desejado para `CALCOM_EVENT_TYPE_ID` no `.env`.
6. Reinicie o Streamlit. No modo Cal.com:
   - Os horários disponíveis são consultados via `GET /v2/slots`.
   - A reserva confirmada é criada diretamente pela API via `POST /v2/bookings` com nome e e-mail informados pelo cliente.
   - O backend armazena o `booking_id` e o judge/evaluator valida a confirmação estruturada.


## Configurar Langfuse e prompts

Crie um projeto e preencha `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` e
`LANGFUSE_BASE_URL` com o host da região do projeto.

```bash
python seed_prompts.py --initialize-production
```

Isso cria duas versões do prompt `climacasa-agent`:

- `baseline`: orientação comercial breve; regras insuficientes para alguns casos.
- `candidate`: versão com regras de preço, restrições de horário, falhas e confirmação.
- `production`: inicialmente aponta para a versão candidate por segurança.

Sem `--initialize-production`, o script cria versões/labels de teste sem mover production.
Cada execução cria versões novas; rode apenas quando quiser publicá-las.
No chat, selecione baseline para investigar a versão menos específica. Não é uma instrução para errar:
o modelo pode responder corretamente em ambos os prompts, o que também é um resultado válido.

No Langfuse, abra o prompt, compare versões e mova `production` para a versão desejada.
Rollback é mover o label de volta. O app busca o label a cada turno (`cache_ttl_seconds=0`)
para a demonstração. Para produção, configure cache conforme seus requisitos.
Se a recuperação falhar, usa o prompt seguro local e sinaliza `fallback` na UI/metadata.
Fallback não é apresentado como versão remota.

## Traces: o que procurar

Após enviar uma mensagem, use **Abrir trace no Langfuse** na lateral.

- Root `maintenance-request`: pergunta, conversa visível, resultado e evidências.
- Agente/gerações PydanticAI: modelo, chamadas, tokens e tempos.
- Ferramentas: `search_service_info`, `get_availability`, `book_visit`.
- `session_id`: agrupa os turnos da mesma conversa, cada turno em seu próprio trace.
- Prompt: versão/label na metadata; propagação nativa do prompt para observações instrumentadas.
- Scores determinísticos no root; scores semânticos chegam depois, pelo worker.
- Custo: Langfuse calcula conforme modelo e usage disponíveis. Não há custo inventado no app.

Não chamamos um wrapper de generation em torno do agente: isso evitaria duplicação da contagem de tokens.
O histórico mantém pares de chamada/retorno, e o root contém as evidências das ferramentas para o judge.
Não registramos um suposto raciocínio interno: mostramos ações e evidências observáveis.

## Evals contínuos: Nativo no Langfuse vs Worker Local

Você pode executar o **LLM-as-a-Judge** de duas formas:

### Opção 1: Diretamente no Langfuse (Recomendado)

O Langfuse executa os avaliadores automaticamente na nuvem/servidor assim que os traces chegam, sem necessidade de rodar nenhum processo de worker no seu computador.

1. **Configurar Provedor de Modelo**: No Langfuse, vá em **Settings > Model Providers** e cadastre sua chave de LLM (ex: OpenAI para `gpt-4o-mini` ou OpenRouter/Anthropic).
2. **Cadastrar Avaliadores**: No Langfuse, acesse **Evaluation > LLM-as-a-Judge** (ou **Evaluators**) e crie os avaliadores.
   - Para ver os templates e regras exatas prontas para copiar, execute:
     ```bash
     python setup_langfuse_evaluators.py --print
     ```
3. Cada novo turno do chat será avaliado automaticamente pelo Langfuse, registrando scores e justificativas diretamente no trace!

### Opção 2: Worker Local (`worker.py`)

Alternativa local para desenvolvimento desconectado ou testes automatizados:

```bash
python worker.py --watch
```

O chat salva execuções em `data/runs`. O worker avalia localmente e envia os scores via SDK.

| Score | Tipo | Significado |
|---|---|---|
| structured_confirmation_supported | Código, booleano | Afirmação estruturada de reserva corresponde ao registro local? |
| tool_calls / tool_errors | Código, numérico | Chamadas e erros neste turno |
| confirmation_supported | Judge, booleano | O texto confirma reserva sem evidência? |
| price_accurate | Judge, booleano | Explicou preço/condições sem inventar? |
| constraints_respected | Judge, booleano | Respeitou restrições ou explicou claramente as alternativas? |
| coverage_accurate | Judge, booleano | Seguiu a consulta do Google Maps (até 3600s)? |

O check estruturado não garante que o texto diz a mesma coisa; por isso há o judge.
Sem afirmação de reserva/preço, o respectivo critério passa: é uma verificação de violação,
não uma medida de completude ou conversão. Leia a justificativa e calibre com revisão humana.
`JUDGE_SAMPLE_RATE=1.0` avalia todos os turnos; reduza para 0.1 para amostrar 10%.
Use um único worker: a fila é local, sem coordenação distribuída. Não reutilize esta fila em produção sem
controle de concorrência, retenção, retries e monitoramento. Score IDs estáveis evitam duplicação em reenvios.
Dados de conversa ficam em `data/`, ignorada pelo git. Use dados fictícios no palco.

## Roteiro de demo em 7–8 minutos

1. **Local, normal, production:** pergunte preço e horários amanhã à tarde. Escolha um horário oferecido.
   Mostre a reserva persistida, o retorno da ferramenta e o texto.
2. **Local, conflict, baseline:** nova conversa; consulte amanhã, escolha o primeiro horário.
   O backend retorna conflito, sem registrar reserva. Inspecione o que o LLM fez.
   Não garanta que o LLM vai falhar: preserve um trace real de ensaio para contingência.
3. Abra o trace: resultado da ferramenta, resposta, tokens, prompt e score após worker.
4. **candidate:** repita em nova conversa com o mesmo cenário. Compare evidências e resultados.
   Mostre promoção/rollback na tela de prompts. Não anuncie percentuais a partir de um exemplo.
5. **Cal.com:** consulte horários reais e confirme uma reserva pelo chat.
   Demonstre a reserva criada diretamente via API v2 e o status de confirmação.
6. Mostre o judge chegando após a resposta, sem estar no caminho crítico do atendimento.

Exemplos para copiar:

```text
Meu ar-condicionado parou. Vocês conseguem hoje depois das 18h? Quanto custa?
Pode consultar amanhã à tarde?
Quero o primeiro horário que você ofereceu. Pode confirmar?
Então por R$ 120 vocês consertam e trocam a peça também?
```

Trocar modo/cenário inicia nova conversa. Trocar label afeta o próximo turno; use Nova conversa
para comparações independentes. As reservas locais persistem em SQLite e consomem os horários.
Para zerar somente a agenda fictícia, pare o app e remova `data/bookings.sqlite3`.

## Comparação reproduzível e testes

```bash
python compare.py --scenario conflict
python worker.py
python -m unittest discover -s tests -v
```

`compare.py` usa LLM real, duas sessões independentes e bancos locais separados para o mesmo cenário.
Não chama Cal.com nem publica novos prompts. Produz traces/execuções, não um resultado pré-fixado.
Os testes usam FunctionModel e transporte Cal.com substituto: não consomem API nem criam reservas reais.

## Arquivos

- `app.py`: chat, controles e painel de evidências.
- `agent_app.py`: agente, ferramentas, memória de sessão, tracing e fila.
- `calendar_backend.py`: adaptador Cal.com API v2 e SQLite de simulação.
- `worker.py` / `evaluators.py`: judge assíncrono e checks.
- `prompts/`: versões inicial e melhorada.
- `seed_prompts.py` / `setup_calcom.py`: configuração explícita.
- `compare.py`: comparação de prompts; `tests/`: testes sem rede.

## Fontes e limites verificados

- Cal.com API v2: https://cal.com/docs/api-reference/v2
- Langfuse/PydanticAI: https://langfuse.com/integrations/frameworks/pydantic-ai
- Prompts: https://langfuse.com/docs/prompt-management/features/prompt-version-control
- Scores SDK: https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk

Credenciais reais não foram fornecidas na criação do pacote: testes locais não comprovam acesso à sua conta,
ingestão no seu projeto Langfuse, nem qualidade de um modelo remoto. Valide esses três pontos antes do palco.

## Cobertura por Google Maps — novo

O chat agora oferece `check_service_area(destination, state)`. Exemplo:
**“Vocês atendem em Santos?”** O agente consulta Geocoding API para resolver o destino e
Routes API para calcular o trajeto de carro desde a base. A decisão é feita em Python:
`served = duration_seconds <= 3600`. Distância é informativa; não define cobertura.

### Configuração

1. No Google Cloud, habilite **Geocoding API** e **Routes API** e configure faturamento.
2. Crie uma chave de servidor restrita a essas APIs (e a IPs quando aplicável).
3. Preencha no `.env`:

```env
GOOGLE_MAPS_API_KEY=sua-chave
COMPANY_ORIGIN_ADDRESS=endereço completo da base com número, cidade, UF, Brasil
SERVICE_AREA_DEFAULT_STATE=SP
```

A origem fica vazia de propósito: não presumimos onde sua empresa está.
Santos não tem resposta fixa: depende da origem e do tempo retornado pelo Google.
SP é o contexto padrão para destinos sem UF; o retorno informa a UF e o destino resolvido.
Se a UF resolvida divergir, o agente deve pedir confirmação. Para outra UF, informe-a na conversa.
Reinicie o Streamlit após alterar `.env`.

### Interação e política

- Na lateral, **Verificar cobertura Google Maps** vem ativado.
- Pergunte “Vocês atendem em Santos?” e veja no painel a distância, minutos e decisão.
- A rota usa `DRIVE` e `TRAFFIC_AWARE`, com saída no momento da consulta.
  O resultado pode mudar com o trânsito; não é previsão para o horário futuro da visita.
- Exatamente 60 minutos atende. 60 minutos e uma fração de segundo já excede o limite.
- Um município ou CEP representa um ponto aproximado. O bot deve qualificar a resposta como estimativa,
  sem garantir todos os bairros. Para agendar, o backend exige geocodificação de endereço específico.
- Timeout, erro de chave, rota ausente, correspondência parcial ou localização ambígua retornam
  `served: null` / `status: unknown`. Isso significa “não consegui verificar”, não “não atendemos”.
- Antes de agendar, `book_visit` recebe o endereço e reconsulta a cobertura.
  Bloqueia o prosseguimento se fora da área, desconhecida ou sem endereço específico.
- A checkbox pode ser desligada para reproduzir os ensaios anteriores da agenda local sem Maps.
  Isso desativa o bloqueio de reserva; a ferramenta Google continua disponível para perguntas de cobertura.
  O CLI `compare.py` e os testes antigos mantêm esse modo isolado de calendário.

Os dados de cobertura aparecem nas evidências do trace e no painel. O judge adiciona
`coverage_accurate`: avalia se o texto segue o retorno da ferramenta, sem inventar tempo,
confundir erro com rejeição ou usar resultado referente a outra localização.
A regra de cobertura também é incluída nas instruções de execução para prompts remotos antigos.
Para versionar as novas instruções completas, rode novamente `seed_prompts.py` e promova a versão desejada.

Google Maps tem faturamento separado; não presumimos chamadas gratuitas.
A demo guarda evidências junto aos traces e aos arquivos de execução. Para uso além do ensaio, ajuste
retenção/exportação de conteúdo Maps às condições do serviço e evite dados pessoais no palco.

Fontes:
- https://developers.google.com/maps/documentation/routes/compute_route_directions
- https://developers.google.com/maps/documentation/routes/config_trade_offs
- https://developers.google.com/maps/documentation/geocoding/guides-v3/start
- https://developers.google.com/maps/documentation/routes/usage-and-billing
