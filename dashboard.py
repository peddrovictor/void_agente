import json
import streamlit as st
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
import google.generativeai as genai

# ==========================================
# 1. CREDENCIAIS
# ==========================================
META_TOKEN = 'EAAfTAkpZBhzgBQ5OuYmzuVNlbcPCB0yl7MGCi30cqNF1wK6ZBVTi5DnQgrDKnRalOl5ZCllcs43u5PwZApPzYDGEKWd34frfEaRTjdqocLqiZCpyohZCoiNY74pqMZBg7PDZCa08FAlman1nYc2S6WDgHFbm3tNhYQ5Fsq4zEUerqgqDsJkMqmWTEgCwUJry'
GEMINI_KEY = 'AIzaSyCGvTCI13XkJLCBF7ypOk3NBtYe_CXy2PU' 

genai.configure(api_key=GEMINI_KEY)

CONTAS = {
    "1": {"nome": "Mazaki Sushi", "id": "act_264056218021550"},
    "2": {"nome": "45 Burger", "id": "act_872820319884375"},
    "3": {"nome": "Merci Padaria", "id": "act_128740810833653"},
    "4": {"nome": "Premium Burger", "id": "act_766571163079316"}
}

# ==========================================
# 2. INICIALIZAÇÃO DA MEMÓRIA
# ==========================================
if "dados_salvos" not in st.session_state:
    st.session_state.dados_salvos = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# ==========================================
# 3. BACKEND (A Mágica da Granularidade)
# ==========================================
@st.cache_data(show_spinner=False)
def buscar_dados_meta(conta_id, periodo, objetivo):
    try:
        FacebookAdsApi.init(access_token=META_TOKEN)
        account = AdAccount(conta_id)
        
        # MUDANÇA 1: Adicionamos campaign_name e ad_name
        fields = ['campaign_name', 'adset_name', 'ad_name', 'spend', 'actions', 'clicks', 'cpc', 'ctr']
        
        # MUDANÇA 2: Nível de busca no detalhe máximo ('ad')
        params = {'date_preset': periodo, 'level': 'ad'}
        
        insights = account.get_insights(fields=fields, params=params)
        dados, total_gasto, total_resultado = [], 0, 0

        for i in insights:
            gasto = float(i.get('spend', 0))
            acoes = {a['action_type']: float(a['value']) for a in i.get('actions', [])}
            
            if objetivo == 'vendas':
                resultado = acoes.get('purchase', 0)
                if resultado == 0: resultado = acoes.get('offsite_conversion.fb_pixel_purchase', 0)
                custo = gasto / resultado if resultado > 0 else 0
                nome_metrica = "Compras"
            elif objetivo == 'mensagens':
                resultado = acoes.get('onsite_conversion.messaging_conversation_started_7d', 0)
                custo = gasto / resultado if resultado > 0 else 0
                nome_metrica = "Mensagens"
            elif objetivo == 'visitas':
                resultado = int(i.get('clicks', 0))
                custo = float(i.get('cpc', 0))
                nome_metrica = "Cliques"

            total_gasto += gasto
            total_resultado += resultado
            
            # MUDANÇA 3: A tabela agora tem a hierarquia completa
            linha = {
                "Campanha": i.get('campaign_name'),
                "Conjunto": i.get('adset_name'),
                "Anúncio": i.get('ad_name'),
                "Gasto (R$)": round(gasto, 2)
            }
            
            if objetivo == 'visitas':
                linha.update({"Cliques": int(resultado), "CPC (R$)": round(custo, 2), "CTR (%)": round(float(i.get('ctr', 0)), 2)})
            else:
                linha.update({nome_metrica: int(resultado), "Custo / Ação (R$)": round(custo, 2)})

            dados.append(linha)
            
        return dados, total_gasto, total_resultado, nome_metrica
    except Exception as e:
        st.error(f"Erro de conexão com a Meta: {e}")
        return None, 0, 0, ""

# ==========================================
# 4. FRONTEND E CHAT
# ==========================================
st.set_page_config(page_title="Void Ads Manager", page_icon="📈", layout="wide")
st.title("📈 Void Ads Manager")

# Filtros
col1, col2, col3 = st.columns(3)
with col1:
    conta_id = st.selectbox("🏢 Cliente / Conta", options=list(CONTAS.keys()), format_func=lambda x: CONTAS[x]['nome'])
with col2:
    periodo_map = {"Hoje": "today", "Ontem": "yesterday", "Últimos 7 dias": "last_7d", "Últimos 30 dias": "last_30d"}
    periodo_selecionado = st.selectbox("📅 Período de Análise", options=list(periodo_map.keys()))
with col3:
    objetivo_map = {"Vendas no Site (Conversão)": "vendas", "Mensagens WhatsApp/Direct": "mensagens", "Visitas e Tráfego": "visitas"}
    objetivo_selecionado = st.selectbox("🎯 Objetivo da Campanha", options=list(objetivo_map.keys()))

st.markdown("---")

if st.button("🚀 Extrair Dados da Meta Ads", type="primary", use_container_width=True):
    id_real = CONTAS[conta_id]['id']
    periodo_real = periodo_map[periodo_selecionado]
    objetivo_real = objetivo_map[objetivo_selecionado]

    with st.spinner('Extraindo dados no nível de criativo...'):
        dados, total_gasto, total_resultado, nome_metrica = buscar_dados_meta(id_real, periodo_real, objetivo_real)
        
        if dados:
            st.session_state.dados_salvos = {
                "dados": dados, "gasto": total_gasto, 
                "resultado": total_resultado, "metrica": nome_metrica,
                "conta": CONTAS[conta_id]['nome']
            }
            st.session_state.chat_history = []
            
            modelos_disp = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            modelo_escolhido = next((m for m in ['models/gemini-2.5-flash', 'models/gemini-1.5-pro-latest'] if m in modelos_disp), modelos_disp[0])
            model = genai.GenerativeModel(modelo_escolhido.replace('models/', ''))
            
            # O prompt agora avisa a IA que ela tem os 3 níveis de dados
            contexto_inicial = (
                f"Você é o Void, estrategista de tráfego sênior. Aqui estão os dados da conta {CONTAS[conta_id]['nome']} "
                f"extraidor no nível de ANÚNCIO (criativo). Os dados mostram a Campanha, o Conjunto e o Anúncio: {json.dumps(dados)}. "
                f"Use essa granularidade para identificar não apenas conjuntos ruins, mas anúncios específicos que estão puxando o CPA/CPC para cima. "
                f"Aguarde a pergunta do usuário."
            )
            
            st.session_state.chat_session = model.start_chat(history=[
                {"role": "user", "parts": [contexto_inicial]},
                {"role": "model", "parts": ["Entendido. Os dados granulares de Campanha, Conjunto e Anúncio estão na minha memória. Pode mandar a sua pergunta!"]}
            ])

if st.session_state.dados_salvos:
    info = st.session_state.dados_salvos
    
    st.subheader(f"📊 Resumo Geral: {info['conta']}")
    m1, m2, m3 = st.columns(3)
    m1.metric(label="Investimento Total", value=f"R$ {info['gasto']:.2f}")
    m2.metric(label=f"Total de {info['metrica']}", value=int(info['resultado']))
    cpa_medio = info['gasto'] / info['resultado'] if info['resultado'] > 0 else 0
    m3.metric(label="Custo Médio", value=f"R$ {cpa_medio:.2f}")

    st.write("### 🗃️ Dados Completos (Campanha > Conjunto > Anúncio)")
    # O dataframe agora exibe as colunas hierárquicas
    st.dataframe(info['dados'], use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("💬 Fale com o Void")

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ex: 'Qual anúncio específico (criativo) está trazendo o CPA mais caro e deve ser pausado?'"):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Void está analisando os criativos..."):
                resposta = st.session_state.chat_session.send_message(prompt).text
                st.markdown(resposta)
        st.session_state.chat_history.append({"role": "assistant", "content": resposta})