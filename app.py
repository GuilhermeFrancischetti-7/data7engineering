# -*- coding: utf-8 -*-
"""
Migracao de Dados Senior.

A tela pergunta primeiro DE ONDE vem a migracao, e so entao mostra o que existe
para aquela origem. Hoje so o eSocial tem extracao automatica; nas outras o
aplicativo entrega a planilha de De/Para, que e a mesma nas tres.

Ordem da tela:
  1. tipo de migracao
  2. planilha de De/Para -- sempre em branco, e o cliente quem preenche
  3. arquivos XML (so eSocial)
  4. leiautes a gerar
  5. De/Para preenchido pelo cliente, de volta
  6. gera os .txt do layout Senior, SEM cabecalho, mais o relatorio de pendencias
"""
import io
import json
import os
import zipfile
from datetime import datetime

import streamlit as st

import complementar
import depara
import modelo_depara
import writer
import xml_reader

PASTA = os.path.dirname(os.path.abspath(__file__))
# Leituras salvas: dado pessoal, fica dentro do projeto nesta maquina.
PASTA_LEITURAS = os.path.join(PASTA, "leituras")
CAMINHO_PARAMETROS = os.path.join(PASTA, "parametros.json")

st.set_page_config(page_title="Migracao de Dados Senior", layout="wide")


def _segredo(nome):
    # Sem secrets.toml o Streamlit levanta erro so de ler; localmente e o normal.
    try:
        return st.secrets.get(nome)
    except Exception:
        return None


# Na nuvem (Streamlit Community Cloud) o disco e do servidor, nao de quem usa:
# pasta e caminho de arquivo nao servem. La tudo entra por upload e sai por
# download. Liga com `modo_nuvem = true` nos secrets ou EXTRATOR_NUVEM=1.
NUVEM = bool(_segredo("modo_nuvem")) or os.environ.get("EXTRATOR_NUVEM") == "1"

_SENHA = _segredo("senha")
if _SENHA and not st.session_state.get("autenticado"):
    st.title("Migracao de Dados Senior")
    _digitada = st.text_input("Senha de acesso", type="password")
    if _digitada and _digitada == _SENHA:
        st.session_state["autenticado"] = True
        st.rerun()
    elif _digitada:
        st.error("Senha incorreta.")
    st.stop()
# Sem senha nos secrets o app abre direto; o controle de acesso fica no
# compartilhamento do Streamlit Cloud (so convidados por e-mail).

# Escala tipografica propria, cerca de 30% acima do padrao do Streamlit, e
# contraste alto no claro. O padrao e desenhado para dashboard curto; aqui a
# tela tem muito texto de apoio e tabela densa, e no claro o cinza padrao
# (#31333F) some contra o branco.
#
# Tamanhos em px de proposito: o Streamlit muda a base do rem entre versoes, e
# com rem a escala saia diferente a cada atualizacao.
st.markdown("""
<style>
  html, body, [class*="css"], .stMarkdown, .stMarkdown p, .stMarkdown li,
  [data-testid="stAppViewContainer"] { font-size: 19px; color: #0E1621; }

  h1 { font-size: 36px !important; font-weight: 700 !important;
       letter-spacing: -.02em; color: #0A1119 !important;
       margin-bottom: .25rem !important; }
  h2 { font-size: 25px !important; font-weight: 650 !important;
       color: #0A1119 !important;
       margin-top: 1.8rem !important; margin-bottom: .6rem !important; }
  h3 { font-size: 21px !important; font-weight: 600 !important;
       color: #0A1119 !important; }

  /* legenda: cinza escuro o bastante para leitura confortavel */
  .stCaption, [data-testid="stCaptionContainer"] p { font-size: 17px !important;
       color: #37485A !important; }

  [data-testid="stMetricValue"] { font-size: 31px !important; color: #0A1119; }
  [data-testid="stMetricLabel"] p { font-size: 16px !important; color: #37485A; }

  .stRadio label p, .stCheckbox label p,
  .stSelectbox label p, .stTextInput label p,
  .stFileUploader label p, .stMultiSelect label p { font-size: 19px !important;
       color: #0E1621 !important; font-weight: 500; }

  .stButton button, .stDownloadButton button { font-size: 18px !important;
       font-weight: 600; }
  .stSelectbox div[data-baseweb="select"], .stTextInput input,
  .stMultiSelect div[data-baseweb="select"] { font-size: 18px !important; }

  .stDataFrame, .stDataFrame div { font-size: 17px !important; }
  div[data-testid="stExpander"] summary p { font-size: 19px !important;
       font-weight: 500; }
  .stAlert p { font-size: 18px !important; }
  .stTabs button p { font-size: 18px !important; }

  /* bordas mais firmes: no claro o cinza padrao quase nao aparece */
  .stSelectbox div[data-baseweb="select"] > div,
  .stTextInput input, .stMultiSelect div[data-baseweb="select"] > div {
       border-color: #8FA0B0 !important; }
  div[data-testid="stExpander"] { border-color: #C3CFDA !important; }
</style>
""", unsafe_allow_html=True)


COLUNAS_PENDENCIA = ["layout", "campo", "descricao", "acao", "obrigatorio",
                     "autoria", "motivo", "exemplo", "ocorrencias"]


def _csv_pendencias(pendencias):
    """CSV do relatorio de pendencias, com ';' e BOM para abrir no Excel pt-BR."""
    import csv
    buf = io.StringIO()
    esc = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL,
                     lineterminator="\n")
    esc.writerow(COLUNAS_PENDENCIA)
    for p in sorted(pendencias,
                    key=lambda x: (not x.get("obrigatorio"), -x.get("ocorrencias", 0))):
        esc.writerow([str(p.get(c, "")).replace("\n", " ") for c in COLUNAS_PENDENCIA])
    return ("﻿" + buf.getvalue()).encode("utf-8")


@st.cache_data(show_spinner=False)
def carregar_parametros():
    with open(CAMINHO_PARAMETROS, encoding="utf-8") as f:
        return json.load(f)


try:
    PAR = carregar_parametros()
except FileNotFoundError:
    st.error("parametros.json nao encontrado. Rode antes:  py gerar_parametros.py")
    st.stop()

MODULOS = PAR["modulos"]

st.title("Migração de Dados Senior")
st.caption("Layout Senior HCM · Administração de Pessoal · %d layouts · %d campos "
           "· parâmetro %s (v%s)"
           % (len(MODULOS), sum(len(m["campos"]) for m in MODULOS.values()),
              PAR["origem"], PAR["versao"]))

# ---------------------------------------------------------------- 1. origem
st.header("1. Tipo de migração")

ORIGENS = {
    "XML do eSocial": {
        "codigo": "eSocial",
        "pronto": True,
        "resumo": "Lê os XMLs do eSocial e adianta o preenchimento dos layouts.",
    },
    "Layout já preenchido": {
        "codigo": "Layout preenchido",
        "pronto": False,
        "resumo": "O cliente entrega o layout Senior já preenchido.",
    },
    "Base Datasul": {
        "codigo": "Datasul",
        "pronto": False,
        "resumo": "Os dados vêm da base Datasul do cliente.",
    },
}

rotulo = st.selectbox(
    "De onde vêm os dados desta migração?",
    options=list(ORIGENS), index=None,
    placeholder="Escolha o tipo de migração para começar",
    help="A extração automática só existe para o eSocial hoje. O De/Para é o "
         "mesmo arquivo nos três casos.")

if not rotulo:
    st.info("Escolha o tipo de migração acima para continuar.")
    st.stop()

ORIGEM = ORIGENS[rotulo]["codigo"]
st.caption(ORIGENS[rotulo]["resumo"])

# ------------------------------------------------------------ 2. De/Para
# O De/Para nao depende de extracao: e o artefato padrao do layout Senior, o
# mesmo para os tres tipos de migracao. Por isso aparece antes de qualquer
# leitura de arquivo, e e a unica coisa disponivel nas origens sem extracao.
if not ORIGENS[rotulo]["pronto"]:
    # So nas origens sem extracao. No XML a planilha em branco nao faz sentido:
    # a etapa 5 monta o De/Para com os codigos achados na massa.
    st.header("2. Planilha de De/Para")
    st.caption("Mesma planilha para qualquer tipo de migração: uma aba por assunto, "
               "o domínio do Senior à esquerda e o código do cliente à direita. "
               "Sai sempre em branco — é o cliente quem preenche.")

    if st.button("Gerar planilha de De/Para", type="primary"):
        with st.spinner("Montando a planilha..."):
            st.session_state["depara_branco"] = modelo_depara.gerar(
                PAR, None, origem=ORIGEM)

    if "depara_branco" in st.session_state:
        arquivo, faltam = st.session_state["depara_branco"]
        st.success("Planilha pronta — %d células para o cliente preencher." % faltam)
        st.download_button(
            "Baixar De-Para_Migracao_Senior.xlsx", arquivo,
            file_name="De-Para_Migracao_Senior.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    st.info("**A extração automática a partir de %s ainda não está pronta.** "
            "Nesta origem o aplicativo entrega apenas a planilha de De/Para "
            "acima." % rotulo)
    st.stop()

# -------------------------------------------- layouts complementares preenchidos
# Caminho de volta: o cliente devolve o xlsx de layouts complementares que o
# proprio extrator gerou, completado, e daqui saem os TXT oficiais. Nao depende
# de ler XML -- o que veio do eSocial ja esta nas linhas do arquivo.
with st.expander("Já tenho os layouts complementares preenchidos — gerar os layouts oficiais do Senior"):
    st.caption("Envie o arquivo gerado pelo botão **Gerar layouts complementares** "
               "depois que o cliente completou. Cada aba vira o TXT do layout, "
               "com as colunas na ordem oficial. Não precisa ler os XMLs de novo.")
    _preenchido = st.file_uploader("Layouts complementares preenchidos (.xlsx)",
                                   type=["xlsx"], key="compl_preenchido")
    _cab_oficial = st.checkbox("Gerar com cabeçalho (só para conferência)",
                               value=False, key="compl_cabecalho")
    if _preenchido and st.button("Gerar layouts oficiais", type="primary"):
        with st.spinner("Lendo o arquivo preenchido..."):
            st.session_state["oficiais"] = (
                _preenchido.name, _cab_oficial,
                complementar.ler_preenchido(_preenchido.getvalue(), PAR))
    if "oficiais" in st.session_state:
        _nome, _cab, _lidos = st.session_state["oficiais"]
        if not _lidos:
            st.error("Nenhuma aba de layout reconhecida em %s. Use o arquivo "
                     "gerado pelo extrator (abas começam pelo código, ex.: "
                     "'1012 Cadastro de Colaborador')." % _nome)
        else:
            _pacote = io.BytesIO()
            with zipfile.ZipFile(_pacote, "w", zipfile.ZIP_DEFLATED) as z:
                for cod, r in sorted(_lidos.items()):
                    if r["linhas"]:
                        z.writestr("%s.txt" % cod, writer.gerar_txt(
                            r["linhas"], writer.ordem_campos(cod, PAR) if _cab else None))
            _com = {c: r for c, r in _lidos.items() if r["linhas"]}
            st.success("%d layout(s) com linhas, %d linha(s) no total. Abas vazias "
                       "não geram arquivo." % (len(_com), sum(len(r["linhas"]) for r in _com.values())))
            st.download_button(
                "Baixar layouts oficiais (.zip)", _pacote.getvalue(),
                file_name="layouts_oficiais_%s.zip" % datetime.now().strftime("%Y%m%d_%H%M"),
                mime="application/zip", width='stretch')
            _atencao = [(c, r) for c, r in sorted(_lidos.items())
                        if r["avisos"] or (r["linhas"] and r["faltas"])]
            if _atencao:
                st.warning("Obrigatórios ainda vazios ou colunas fora do padrão em "
                           "%d layout(s). Os arquivos foram gerados assim mesmo; "
                           "confira antes de importar." % len(_atencao))
                for c, r in _atencao:
                    st.write("**%s — %s**" % (c, MODULOS[c]["nome"]))
                    for a in r["avisos"]:
                        st.write("- " + a)
                    if r["faltas"]:
                        st.write("- Obrigatório vazio: " + ", ".join(
                            "%s (%d linha(s))" % kv for kv in sorted(r["faltas"].items())))

st.divider()

# ------------------------------------------------------------- 3. leiautes
# A escolha vem ANTES de ler os arquivos, e nao depois. Cada leiaute declara os
# eventos de que precisa, e so esses sao lidos do disco: numa massa de teste com
# 226 mil arquivos, gerar so o 1012 le 20 mil -- 91% a menos. Antes a tela
# perguntava depois de ler tudo, e o trabalho ja tinha sido feito.
st.header("3. Layouts a gerar")

col_a, col_b = st.columns([3, 1])
with col_b:
    marcar_todos = st.checkbox("Selecionar todos", value=True)
with col_a:
    escolhidos = st.multiselect(
        "Layouts",
        options=sorted(MODULOS),
        default=sorted(MODULOS) if marcar_todos else [],
        format_func=lambda c: "%s — %s" % (c, MODULOS[c]["nome"]))

if not escolhidos:
    st.info("Escolha ao menos um layout para continuar.")
    st.stop()


def _eventos_de(cod):
    return {e for c in MODULOS[cod]["campos"] for e in (c.get("eventos") or [])
            if e}


EVENTOS_NECESSARIOS = set()
for _c in escolhidos:
    EVENTOS_NECESSARIOS |= _eventos_de(_c)

st.caption("Precisa dos eventos: %s" % (", ".join(sorted(EVENTOS_NECESSARIOS))
                                        or "nenhum evento mapeado"))

# ---------------------------------------------------------------- 1. arquivos
st.header("4. Arquivos XML")


@st.cache_data(show_spinner=False)
def _zip_massa_demo():
    """Massa sintetica (gerar_massa_demo.py) zipada, para testar sem dado real."""
    import tempfile
    import gerar_massa_demo
    with tempfile.TemporaryDirectory() as tmp:
        arquivos = gerar_massa_demo.gerar(tmp)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for a in arquivos:
                z.write(a, os.path.relpath(a, tmp))
    return buf.getvalue()


with st.expander("Não tem XMLs à mão? Baixe uma massa de demonstração"):
    st.caption("XMLs 100% fictícios, com CPFs e CNPJs gerados. Baixe o ZIP e "
               "envie em \"Upload de arquivos\" logo abaixo.")
    st.download_button("Baixar massa_demo.zip", _zip_massa_demo(),
                       file_name="massa_demo.zip", mime="application/zip")

modo = st.radio(
    "De onde vem a massa",
    (["Upload de arquivos", "Leitura salva"] if NUVEM else
     ["Pasta no disco (recomendado)", "Upload de arquivos", "Leitura salva"]),
    horizontal=True,
    help="A pasta e lida direto do disco, sem passar pelo navegador: nao tem "
         "limite de tamanho e e mais rapido. O app roda nesta maquina, entao o "
         "upload so faria o arquivo dar a volta para voltar ao mesmo disco. "
         "Leitura salva reabre uma leitura gravada antes, sem varrer os XMLs.")

# A massa fica em session_state e so e relida quando a origem muda ou quando o
# botao e apertado. Reler a cada interacao da tela custaria minutos numa massa
# grande, e parar o script quando o botao nao foi clicado apagaria o resultado
# ja carregado no primeiro clique em qualquer outro widget.
if modo.startswith("Pasta"):
    caminho = st.text_input(
        "Caminho da pasta",
        value=st.session_state.get("ultima_pasta", ""),
        placeholder=r"C:\Users\%s\Downloads\xmls_esocial"
                    % os.environ.get("USERNAME", "usuario"),
        help="Cole o caminho da pasta. Subpastas entram junto. "
             "Aceita .xml e .zip; ZIP com subpastas e ZIP dentro de ZIP tambem.")
    recursivo = st.checkbox("Incluir subpastas", value=True)
    origem_atual = ("pasta", caminho.strip(), recursivo,
                    tuple(sorted(EVENTOS_NECESSARIOS)))

    if caminho.strip():
        st.session_state["ultima_pasta"] = caminho
        # A contagem varre a pasta inteira, e o Streamlit reexecuta o script a
        # cada clique. Sem cache, uma massa de 226 mil arquivos custava quase
        # dois minutos POR INTERACAO, so para atualizar o rotulo. Guarda por
        # (caminho, recursivo) e so reconta quando um dos dois muda.
        chave_contagem = (caminho.strip(), recursivo,
                          tuple(sorted(EVENTOS_NECESSARIOS)))
        if st.session_state.get("contagem_de") != chave_contagem:
            try:
                with st.spinner("Contando os arquivos da pasta..."):
                    st.session_state["contagem"] = xml_reader.contar_pasta(
                        caminho, recursivo, EVENTOS_NECESSARIOS)
                st.session_state["contagem_de"] = chave_contagem
            except NotADirectoryError as e:
                st.error(str(e))
                st.stop()
        qtd, tam = st.session_state["contagem"]

        if qtd == 0:
            if recursivo:
                st.warning("Nenhum .xml ou .zip nessa pasta nem nas subpastas.")
            else:
                st.warning("Nenhum .xml ou .zip na raiz dessa pasta. "
                           "Marque **Incluir subpastas** — e comum a massa vir "
                           "separada por evento (S-2200/, S-2230/, ...).")
            st.stop()

        st.info("%s arquivo(s) · %.1f MB — só os eventos que os layouts "
                "escolhidos usam"
                % ("{:,}".format(qtd).replace(",", "."), tam / 1e6))

        if st.button("Ler a pasta", type="primary"):
            barra = st.progress(0.0, text="Lendo...")

            def _passo(n, onde=""):
                barra.progress(
                    min(n / max(qtd, 1), 1.0),
                    text="%s · %s de %s XMLs"
                         % (onde or "lendo",
                            "{:,}".format(n).replace(",", "."),
                            "{:,}".format(qtd).replace(",", ".")))

            st.session_state["massa"] = xml_reader.carregar_documentos(
                parametros=PAR, pasta=caminho, recursivo=recursivo,
                progresso=_passo, eventos=EVENTOS_NECESSARIOS)
            st.session_state["origem_massa"] = origem_atual
            st.session_state["acabou_de_ler"] = True
            barra.empty()
    else:
        origem_atual = None

elif modo == "Leitura salva" and NUVEM:
    _enviada = st.file_uploader("Arquivo .leitura", type=["leitura"])
    origem_atual = ("leitura", _enviada.name, _enviada.size) if _enviada else None
    if _enviada:
        man = xml_reader.ler_manifesto(io.BytesIO(_enviada.getvalue()))
        st.info("Gravada em %s · parametro %s" % (man.get("gravado_em"),
                                                 man.get("parametro") or "?"))
        faltando = sorted(set(EVENTOS_NECESSARIOS) - set(man.get("eventos_pedidos")
                                                         or EVENTOS_NECESSARIOS))
        if faltando:
            st.warning("Os layouts escolhidos usam eventos que nao foram lidos "
                       "nesta leitura: %s." % ", ".join(faltando))
        _extras = st.file_uploader(
            "XMLs que faltavam na leitura (opcional)", type=["xml", "zip"],
            accept_multiple_files=True, key="extras_nuvem",
            help="Quando o cliente manda depois os XMLs que nao vieram. Evento "
                 "que ja esta na leitura (mesmo Id) conta uma vez so.")
        origem_atual = origem_atual + (tuple(sorted(f.name for f in _extras or [])),)
        if st.session_state.get("origem_massa") != origem_atual:
            with st.spinner("Carregando a leitura salva..."):
                massa = xml_reader.carregar_leitura(io.BytesIO(_enviada.getvalue()))[:4]
                massa[3]["eventos_pedidos"] = man.get("eventos_pedidos")
                if _extras:
                    massa = xml_reader.juntar_massas(massa, xml_reader.carregar_documentos(
                        arquivos=[(f.name, f.getvalue()) for f in _extras], parametros=PAR))
                st.session_state["massa"] = massa
            st.session_state["origem_massa"] = origem_atual

elif modo == "Leitura salva":
    arquivo_leitura = st.text_input(
        "Caminho do arquivo .leitura",
        value=st.session_state.get("ultima_leitura", ""),
        placeholder=os.path.join(PASTA_LEITURAS, "minha_massa.leitura"),
        help="Arquivo gravado com o botao 'Salvar esta leitura', depois de ler "
             "uma pasta.")
    origem_atual = ("leitura", arquivo_leitura.strip()) if arquivo_leitura.strip() else None
    if origem_atual:
        if not os.path.isfile(arquivo_leitura.strip()):
            st.error("Arquivo nao encontrado.")
            st.stop()
        man = xml_reader.ler_manifesto(arquivo_leitura.strip())
        st.info("Gravada em %s · origem %s · parametro %s · %s eventos"
                % (man.get("gravado_em"), man.get("origem") or "?",
                   man.get("parametro") or "?",
                   "{:,}".format(sum(man.get("estatistica", {}).values())).replace(",", ".")))
        # Evento que a leitura nem pediu e diferente de evento que nao veio na
        # massa: so o primeiro exige ler a pasta de novo.
        pedidos = man.get("eventos_pedidos")
        faltando = (sorted(set(EVENTOS_NECESSARIOS) - set(pedidos))
                    if pedidos is not None else [])
        if faltando:
            st.warning("Os layouts escolhidos usam eventos que nao foram lidos "
                       "nesta leitura: %s. Para eles, leia a pasta de novo."
                       % ", ".join(faltando))
        if man.get("parametro") and man.get("parametro") != PAR.get("origem"):
            st.warning("Leitura feita com %s; o parametro atual e %s. Se a nova "
                       "versao passou a usar outro evento, ele nao esta aqui."
                       % (man.get("parametro"), PAR.get("origem")))
        # O cliente pode nao ter mandado todos os XMLs na primeira vez. Os que
        # chegarem depois somam a leitura salva, sem varrer a massa antiga.
        with st.expander("Acrescentar XMLs que faltavam nesta leitura (opcional)"):
            pasta_extra = st.text_input(
                "Pasta com os XMLs novos", key="pasta_extra",
                help="Subpastas entram junto. Aceita .xml e .zip.")
            enviados_extra = st.file_uploader(
                "ou suba os arquivos", type=["xml", "zip"],
                accept_multiple_files=True, key="upload_extra")
            st.caption("Evento que já está na leitura (mesmo Id de recibo) conta "
                       "uma vez só. Só entram os eventos que os layouts escolhidos usam.")
        pasta_extra = pasta_extra.strip()
        if pasta_extra and not os.path.isdir(pasta_extra):
            st.error("Pasta dos XMLs novos nao encontrada.")
            st.stop()
        origem_atual = origem_atual + (pasta_extra,
                                       tuple(sorted(f.name for f in enviados_extra or [])))
        if st.button("Carregar a leitura", type="primary"):
            st.session_state["ultima_leitura"] = arquivo_leitura
            with st.spinner("Carregando a leitura salva..."):
                *massa, _man = xml_reader.carregar_leitura(arquivo_leitura.strip())
            # Eventos pedidos da leitura somada: os da original mais os da pasta
            # nova. None (leitura sem filtro) continua None. Arquivo enviado nao
            # tem filtro de evento e nao muda a lista.
            _pedidos = _man.get("eventos_pedidos")
            if _pedidos is not None and pasta_extra:
                _pedidos = sorted(set(_pedidos) | set(EVENTOS_NECESSARIOS))
            if pasta_extra:
                with st.spinner("Lendo os XMLs da pasta nova..."):
                    massa = xml_reader.juntar_massas(massa, xml_reader.carregar_documentos(
                        parametros=PAR, pasta=pasta_extra, recursivo=True,
                        eventos=EVENTOS_NECESSARIOS))
            if enviados_extra:
                with st.spinner("Lendo os XMLs enviados..."):
                    massa = xml_reader.juntar_massas(massa, xml_reader.carregar_documentos(
                        arquivos=[(f.name, f.getvalue()) for f in enviados_extra],
                        parametros=PAR))
            massa = tuple(massa)
            massa[3]["eventos_pedidos"] = _pedidos
            st.session_state["massa"] = massa
            st.session_state["origem_massa"] = origem_atual

else:
    enviados = st.file_uploader(
        "XMLs do eSocial — arquivos soltos, um ZIP, varios ZIPs, ou ZIP com subpastas",
        type=["xml", "zip"], accept_multiple_files=True)
    origem_atual = ("upload", tuple(sorted(f.name for f in enviados))) if enviados else None

    if enviados and st.session_state.get("origem_massa") != origem_atual:
        with st.spinner("Lendo os XMLs..."):
            st.session_state["massa"] = xml_reader.carregar_documentos(
                arquivos=[(f.name, f.getvalue()) for f in enviados], parametros=PAR)
            st.session_state["origem_massa"] = origem_atual

if "massa" not in st.session_state:
    st.info("Informe a pasta e clique em **Ler a pasta**, ou suba os arquivos."
            if modo.startswith("Pasta") else
            "Informe o arquivo e clique em **Carregar a leitura**."
            if modo == "Leitura salva" else
            "Suba pelo menos um arquivo." if NUVEM else
            "Suba pelo menos um arquivo, ou use o modo pasta acima.")
    st.stop()

documentos, problemas, estatistica, resumo = st.session_state["massa"]

if origem_atual and st.session_state.get("origem_massa") != origem_atual:
    st.warning("A origem mudou desde a ultima leitura. O que esta na tela ainda "
               "e a massa anterior — clique em **Ler a pasta** para atualizar.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("XMLs encontrados", resumo["xmls_lidos"])
c2.metric("Eventos lidos", len(documentos))
c3.metric("Duplicados descartados", resumo["duplicados_descartados"])
c4.metric("Sem evento mapeado", len(resumo["sem_evento_mapeado"]))
if resumo.get("acrescentados") is not None:
    st.info("%d evento(s) novo(s) acrescentado(s) à leitura salva. Salve a leitura "
            "de novo (abaixo) para não precisar ler esses XMLs outra vez."
            % resumo["acrescentados"])

if not documentos:
    st.error("Nenhum evento reconhecido nos arquivos enviados.")
    st.stop()

_incompletos = xml_reader.caminhos_incompletos(PAR)
if _incompletos:
    with st.expander("%d campo(s) com caminho incompleto na planilha de parametro"
                     % len(_incompletos)):
        st.caption("O caminho nao comeca pela tag do evento, entao nao da para "
                   "montar o caminho absoluto. O extrator procura a tag pelo "
                   "nome dentro do evento e registra pendencia. Corrigir na "
                   "planilha resolve.")
        for cod, campo, ev, cam in _incompletos:
            st.write("- **%s %s** (%s) — `%s`" % (cod, campo, ev, cam))

st.write("**Eventos encontrados:** " +
         " · ".join("%s (%d)" % (k, v) for k, v in sorted(estatistica.items())))

# Salvar so faz sentido para uma leitura de verdade: regravar uma leitura salva
# so copiaria o arquivo.
# Leitura salva com XMLs acrescentados tambem e leitura nova.
_om = st.session_state.get("origem_massa") or ("",)
if _om[0] in ("pasta", "upload") or (
        _om[0] == "leitura" and (st.session_state.get("massa") or [0, 0, 0, {}])[3].get("acrescentados")):
    with st.expander("Salvar esta leitura para usar depois"):
        st.caption("Grava os eventos lidos num arquivo .leitura. Quando o De/Para "
                   "preenchido voltar, escolha **Leitura salva** acima e gere os "
                   "layouts sem ler os XMLs de novo. O arquivo tem o mesmo dado "
                   "pessoal dos XMLs: nao tire da maquina.")
        _origem = st.session_state["origem_massa"]
        _nome = "%s_%s.leitura" % (
            os.path.basename(str(_origem[1]).rstrip("\\/")) or "leitura"
            if _origem[0] == "pasta" else
            os.path.splitext(os.path.basename(str(_origem[1])))[0] + "_acrescida"
            if _origem[0] == "leitura" else "upload",
            datetime.now().strftime("%Y%m%d_%H%M"))
        if NUVEM:
            import tempfile
            if st.button("Preparar arquivo .leitura"):
                with st.spinner("Gravando..."), tempfile.TemporaryDirectory() as _tmp:
                    _arq = os.path.join(_tmp, _nome)
                    xml_reader.salvar_leitura(_arq, st.session_state["massa"], PAR,
                                              origem="upload",
                                              eventos_pedidos=resumo.get("eventos_pedidos"))
                    with open(_arq, "rb") as _f:
                        st.session_state["leitura_bytes"] = (_nome, _f.read())
            if "leitura_bytes" in st.session_state:
                st.download_button("Baixar %s" % st.session_state["leitura_bytes"][0],
                                   st.session_state["leitura_bytes"][1],
                                   file_name=st.session_state["leitura_bytes"][0])
            destino = None
        else:
            destino = st.text_input("Gravar em",
                                    value=os.path.join(PASTA_LEITURAS, _nome))
        if destino is not None and st.button("Salvar esta leitura"):
            with st.spinner("Gravando..."):
                xml_reader.salvar_leitura(
                    destino.strip(), st.session_state["massa"], PAR,
                    origem=str(_origem[1]) if _origem[0] in ("pasta", "leitura") else "upload",
                    eventos_pedidos=(sorted(_origem[3]) if _origem[0] == "pasta"
                                     and len(_origem) > 3 else
                                     resumo.get("eventos_pedidos")
                                     if _origem[0] == "leitura" else None))
            st.success("Leitura salva em %s (%.1f MB)."
                       % (destino.strip(), os.path.getsize(destino.strip()) / 1e6))

# Antes a tela filtrava os leiautes pelos eventos encontrados. Agora a escolha
# vem antes da leitura, entao o aviso e o inverso: o que foi escolhido e nao
# tem dado nesta massa.
_sem_dado = [c for c in escolhidos
             if _eventos_de(c) and not (_eventos_de(c) & set(estatistica))]
if _sem_dado:
    with st.expander("%d layout(s) escolhido(s) sem evento correspondente "
                     "nesta massa" % len(_sem_dado)):
        st.caption("Saem vazios. Ou o evento nao veio na massa, ou o layout se "
                   "preenche fora do XML.")
        for c in _sem_dado:
            st.write("- **%s** %s — precisa de: %s"
                     % (c, MODULOS[c]["nome"], ", ".join(sorted(_eventos_de(c)))))

if resumo["duplicados_descartados"]:
    st.caption("Duplicados sao eventos com o mesmo Id de recibo do eSocial, "
               "entregues em mais de um arquivo. Conta so uma vez.")

if resumo["sem_evento_mapeado"]:
    with st.expander("%d XML(s) sem evento mapeado na planilha de parametro"
                     % len(resumo["sem_evento_mapeado"])):
        st.caption("Nao e erro: sao eventos que a v%s ainda nao mapeia "
                   "(S-1010, S-2220, S-2250...). Foram ignorados." % PAR["versao"])
        st.code("\n".join(resumo["sem_evento_mapeado"][:200]))

if problemas:
    with st.expander("%d arquivo(s) com problema de leitura" % len(problemas)):
        for nome, motivo in problemas[:200]:
            st.write("- `%s` — %s" % (nome, motivo))

# A caixa de "parametros fixos" (NUMEMP, TABEVE, CODFIL) saiu da tela.
# Era um valor unico carimbado em toda linha de todo leiaute, e ganhava do
# De/Para, do XML e da regra. Numa massa com mais de uma empresa ou filial isso
# manda a carga inteira para o codigo errado, sem erro na tela -- a massa de teste
# tem duas filiais, e preencher a caixa jogaria 134 pessoas para a filial errada.
# Esses tres campos ja sao De/Para do cliente e aparecem na aba "Codigos da
# empresa" da planilha, com cada CNPJ encontrado no XML esperando o codigo
# Senior ao lado. Um lugar so para a mesma decisao.
# A importacao do Senior recusa o primeiro registro se houver cabecalho, entao
# o padrao e sem. A opcao existe para conferencia: aberto no Excel, saber que
# coluna e qual sem contar posicao.
com_cabecalho = st.checkbox(
    "Gerar os arquivos com cabeçalho (só para conferência)",
    value=False,
    help="A importação do Senior espera o arquivo SEM cabeçalho. Ligue apenas "
         "para conferir o conteúdo; não use o arquivo assim na carga.")

deduplicar = st.checkbox(
    "Remover linhas com chave repetida (fica a ultima)",
    value=False,
    help="Desligado por padrao. O Senior rejeita chave repetida, mas decidir o "
         "que fazer com ela e regra de negocio do projeto -- pode ser readmissao "
         "legitima. Ligue so depois de olhar o diagnostico.")

# ------------------------------------------------------------- 4. De/Para
st.header("5. De/Para preenchido pelo cliente")

tabelas = depara.Tabelas(PAR)
st.caption("Ja vem prontos da planilha: " +
           ", ".join("%s (%d codigos)" % (k, len(v)) for k, v in tabelas.dominio.items()) +
           ". O restante e o cliente que preenche.")

cd1, cd2 = st.columns(2)

with cd1:
    st.subheader("Baixar modelo para o cliente")
    st.caption("Uma aba por assunto (Pessoa, Contrato, Afastamento...), o "
               "dominio do Senior inteiro com descricao, e a pergunta na "
               "direcao que o cliente sabe responder: **o Senior aceita isto — "
               "como se chama no seu sistema?** Mais um Indice para achar "
               "qualquer campo.")
    def _montar_depara(alvo):
        with st.spinner("Montando a planilha..."):
            achados = depara.levantar_valores_distintos(documentos, PAR, alvo)
            # A descricao das rubricas vem do S-1010 e nao preenche coluna de
            # leiaute nenhuma -- serve para o cliente saber o que e o codigo 101
            # na hora de mapear CODEVE.
            rubricas = depara.indice_rubricas(documentos)
            arquivo, faltam = modelo_depara.gerar(PAR, achados, origem=ORIGEM,
                                                  rubricas=rubricas,
                                                  leiautes=alvo)
        st.session_state["qtd_rubricas"] = len(rubricas)
        st.session_state["modelo_depara"] = arquivo
        st.session_state["qtd_depara"] = faltam
        # A planilha cobre os leiautes ESCOLHIDOS, nao os 48. Varrer a massa
        # atras de campos De/Para de leiaute que nao vai ser gerado -- e cujo
        # evento nem foi lido -- e trabalho jogado fora.
        st.session_state["depara_da_massa"] = (
            st.session_state.get("origem_massa"), tuple(sorted(alvo)))

    # Sai pronto sozinho, sem esperar clique -- mas NAO na mesma passada que le
    # a pasta. Montar a planilha ali dentro fazia o "Ler a pasta" devolver o
    # dobro do tempo, com a barra ainda dizendo "Lendo...". Aqui a leitura
    # termina e mostra os numeros dela; a planilha e montada na passada
    # seguinte, com o proprio aviso de progresso.
    _assinatura_depara = (st.session_state.get("origem_massa"),
                          tuple(sorted(escolhidos)))
    if st.session_state.get("depara_da_massa") != _assinatura_depara:
        if st.session_state.pop("acabou_de_ler", False):
            # Nao monta na mesma passada que leu a pasta: o Streamlit renderiza
            # de cima para baixo, e montar aqui devolveria o "Ler a pasta" so
            # depois da planilha pronta -- foi o que deixou a leitura lenta.
            # Aqui a leitura termina e mostra os numeros dela; a planilha sai na
            # proxima passada, que qualquer clique dispara, com o proprio aviso.
            st.info("A planilha de De/Para com sugestão de preenchimento é "
                    "montada assim que você continuar — ou clique abaixo para "
                    "montar agora.")
            if st.button("Montar a planilha de De/Para agora", width='stretch'):
                _montar_depara(escolhidos)
        else:
            _montar_depara(escolhidos)

    if st.button("Refazer a planilha de De/Para", width='stretch'):
        _montar_depara(escolhidos)
    if "modelo_depara" in st.session_state:
        st.success("%d celulas para o cliente preencher."
                   % st.session_state["qtd_depara"])
        st.caption("O que ja se sabe do padrao eSocial vem preenchido em verde, "
                   "para conferencia. Campos com valor por pessoa (CPF, matricula) "
                   "aparecem como resumo, sem listar valor a valor.")
        if st.session_state.get("qtd_rubricas"):
            st.caption("Descricao de %d rubricas lida do S-1010 e levada para o "
                       "De/Para de CODEVE, para o cliente reconhecer o codigo."
                       % st.session_state["qtd_rubricas"])
        st.download_button(
            "Baixar De-Para_para_preencher.xlsx",
            st.session_state["modelo_depara"],
            file_name="De-Para_Migracao_Senior.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch')

    # O codigo do colaborador vai num arquivo a parte: e uma linha por pessoa,
    # e nao um dominio de algumas dezenas de codigos. Misturar as duas coisas
    # tornaria a planilha de De/Para impraticavel -- na massa de teste seriam
    # 1.060 linhas dentro dela.
    st.divider()
    st.subheader("Códigos do colaborador")
    st.caption("Uma linha por pessoa, com CPF, nome e matrícula do eSocial. "
               "O cliente informa o código que cada colaborador terá no Senior, "
               "e a extração passa a gravar esse código no NUMCAD em vez do CPF.")
    if st.button("Gerar planilha de códigos do colaborador", width='stretch'):
        with st.spinner("Levantando os colaboradores..."):
            pessoas = depara.levantar_colaboradores(documentos)
            arquivo, quantos = modelo_depara.gerar_codigos_colaborador(pessoas)
        st.session_state["codigos_colab"] = arquivo
        st.session_state["qtd_colab"] = quantos
    if "codigos_colab" in st.session_state:
        st.success("%d colaborador(es) na planilha."
                   % st.session_state["qtd_colab"])
        st.download_button(
            "Baixar Codigos_do_colaborador.xlsx",
            st.session_state["codigos_colab"],
            file_name="Codigos_do_colaborador.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch')

with cd2:
    st.subheader("Subir De/Para preenchido")
    st.caption("Suba aqui o mesmo arquivo depois de preenchido. "
               "Linha em branco continua pendente -- nada e chutado.")
    preenchido = st.file_uploader("De/Para preenchido", type=["xlsx"],
                                  key="up_depara")
    if preenchido:
        qtd, avisos = tabelas.carregar_modelo(preenchido.getvalue())
        if qtd:
            st.success("%d traducoes carregadas." % qtd)
        for a in avisos:
            st.warning(a)

    st.divider()
    st.caption("E aqui a planilha de códigos do colaborador, depois de "
               "preenchida. A ligação é pelo CPF.")
    colab = st.file_uploader("Códigos do colaborador preenchidos",
                             type=["xlsx"], key="up_colab")
    if colab:
        qtd, problemas = tabelas.carregar_codigos_colaborador(colab.getvalue())
        if qtd:
            st.success("%d código(s) de colaborador carregado(s)." % qtd)
        else:
            st.warning("Nenhum código lido. Confira se a planilha tem uma "
                       "coluna de CPF e uma de código no Senior preenchidas.")
        for pr in problemas:
            st.warning(pr)

# ------------------------------------------------------------- 5. gerar
st.header("6. Gerar os layouts")

if not escolhidos:
    st.info("Escolha ao menos um layout na secao 3.")
    st.stop()

if st.button("Gerar layouts Senior", type="primary", width='stretch'):
    resultados, todas_pendencias = {}, []
    barra = st.progress(0.0, text="Montando as linhas...")

    for i, cod in enumerate(escolhidos, start=1):
        linhas, pend, diag = writer.montar_modulo(
            cod, PAR, documentos, tabelas, deduplicar=deduplicar)
        resultados[cod] = {"linhas": linhas, "diag": diag}
        todas_pendencias.extend(pend)
        barra.progress(i / len(escolhidos), text="%s — %s" % (cod, MODULOS[cod]["nome"]))
    barra.empty()

    st.session_state["resultados"] = resultados
    st.session_state["pendencias"] = todas_pendencias
    # resultado novo invalida o complementar montado do anterior
    st.session_state.pop("complementar", None)

if "resultados" in st.session_state:
    resultados = st.session_state["resultados"]
    pendencias = st.session_state["pendencias"]

    total_linhas = sum(len(r["linhas"]) for r in resultados.values())
    repetidas = sum(r["diag"].get("chaves_repetidas", 0) for r in resultados.values())
    identicas = sum(r["diag"].get("identicas_removidas", 0) for r in resultados.values())

    def _n(v):
        return "{:,}".format(v).replace(",", ".")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Layouts gerados", len(resultados))
    m2.metric("Linhas no total", _n(total_linhas))
    m3.metric("Copias exatas removidas", _n(identicas))
    m4.metric("Chaves repetidas", _n(repetidas))

    if identicas:
        st.caption("Copias exatas sao linhas iguais em todas as colunas. "
                   "Acontece nos layouts de tabela: varios colaboradores citam "
                   "o mesmo cargo, bairro ou sindicato, e a tabela precisa de "
                   "uma linha por item, nao uma por colaborador.")

    if repetidas and not deduplicar:
        piores = sorted(((r["diag"].get("chaves_repetidas", 0), cod)
                         for cod, r in resultados.items()), reverse=True)[:3]
        detalhe = ", ".join("%s (%s)" % (c, _n(q)) for q, c in piores if q)
        st.warning("**%s linha(s) com chave repetida** — concentradas em %s. "
                   "O Senior rejeita chave duplicada. Quase sempre a causa e um "
                   "campo da chave saindo vazio: veja na aba Diagnostico quais "
                   "campos formam a chave e confira no relatorio de pendencias "
                   "por que estao em branco." % (_n(repetidas), detalhe))

    aba1, aba2, aba3, aba4 = st.tabs(["Arquivos", "Pendencias", "Diagnostico",
                                      "Auditoria do mapeamento"])

    with aba1:
        carimbo = datetime.now().strftime("%Y%m%d_%H%M")
        pacote = io.BytesIO()
        with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED) as z:
            for cod, r in sorted(resultados.items()):
                conteudo = writer.gerar_txt(
                    r["linhas"],
                    writer.ordem_campos(cod, PAR) if com_cabecalho else None)
                z.writestr("%s.txt" % cod, conteudo)
            if pendencias:
                z.writestr("_pendencias.csv", _csv_pendencias(pendencias))
        st.download_button(
            "Baixar todos os layouts (.zip)", pacote.getvalue(),
            file_name="layouts_senior_%s.zip" % carimbo,
            mime="application/zip", type="primary", width='stretch')

        # O mesmo resultado, em Excel, para o cliente completar o que o eSocial
        # nao traz. Quem preenche cada campo: complementar.papel.
        # Os layouts 100% complementares saem com uma linha por colaborador do
        # 1012; se o 1012 nao foi escolhido, gera so para isso.
        # Por botao e guardado na sessao: o Streamlit roda a pagina inteira a
        # cada clique (inclusive o de baixar), e no piloto remontar o Excel a
        # cada interacao levava minutos.
        if st.button("Gerar layouts complementares (.xlsx)", width='stretch'):
            with st.spinner("Montando os layouts complementares..."):
                linhas_1012 = (resultados.get("1012") or {}).get("linhas")
                if linhas_1012 is None:
                    linhas_1012 = writer.montar_modulo("1012", PAR, documentos, tabelas,
                                                       deduplicar=True)[0]
                st.session_state["complementar"] = (
                    complementar.gerar(resultados, PAR, linhas_1012), carimbo)
        if "complementar" in st.session_state:
            (compl, resumo_compl), carimbo_compl = st.session_state["complementar"]
            st.download_button(
                "Baixar layouts complementares (.xlsx)", compl,
                file_name="layouts_complementares_%s.xlsx" % carimbo_compl,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width='stretch')
            st.caption("Uma aba por layout com os dados já extraídos e o De/Para aplicado. "
                       "Colunas amarelas: o cliente preenche (%d no total). Células laranja: "
                       "obrigatório que não veio no XML (%d)." % (
                           sum(v[1] for v in resumo_compl.values()),
                           sum(v[2] for v in resumo_compl.values())))

        st.divider()
        for cod, r in sorted(resultados.items()):
            linhas = r["linhas"]
            conteudo = writer.gerar_txt(
                linhas, writer.ordem_campos(cod, PAR) if com_cabecalho else None)
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write("**%s** — %s" % (cod, MODULOS[cod]["nome"]))
            c2.write("%d linhas" % len(linhas))
            c3.download_button("Baixar", conteudo, file_name="%s.txt" % cod,
                               mime="text/plain", key="dl_%s" % cod)
            if linhas:
                with st.expander("Ver as 3 primeiras linhas de %s" % cod):
                    st.caption("Ordem das colunas: " +
                               ";".join(writer.ordem_campos(cod, PAR)))
                    st.code("\n".join(conteudo.split("\n")[:3]), language=None)

    with aba2:
        if not pendencias:
            st.success("Nenhuma pendencia.")
        else:
            st.caption("Cada linha e um campo que precisa de decisao humana. "
                       "'Obrigatorio' marca o que o Senior exige e hoje sai vazio.")
            import pandas as pd
            df = pd.DataFrame(pendencias)
            df = df[["layout", "campo", "descricao", "acao", "obrigatorio",
                     "autoria", "motivo", "exemplo", "ocorrencias"]]
            df = df.sort_values(["obrigatorio", "ocorrencias"], ascending=[False, False])
            st.dataframe(df, width='stretch', height=420)
            st.download_button("Baixar pendencias (.csv)", _csv_pendencias(pendencias),
                               file_name="pendencias.csv", mime="text/csv")

    with aba3:
        import pandas as pd
        linhas_diag = []
        for cod, r in sorted(resultados.items()):
            d = r["diag"]
            linhas_diag.append({
                "layout": cod,
                "nome": MODULOS[cod]["nome"],
                "eventos": ", ".join(d.get("eventos", [])),
                "documentos": d.get("documentos", 0),
                "linhas": len(r["linhas"]),
                "copias exatas removidas": d.get("identicas_removidas", 0),
                "chaves repetidas": d.get("chaves_repetidas", 0),
                "linhas sem chave": d.get("linhas_sem_chave", 0),
                "campos chave": ", ".join(d.get("campos_chave", [])),
            })
        st.dataframe(pd.DataFrame(linhas_diag), width='stretch', height=520)

    with aba4:
        st.caption("Confere cada caminho declarado na planilha contra a massa "
                   "lida. Caminho que nunca resolve, havendo documentos do "
                   "proprio evento, e quase sempre tag no evento errado — "
                   "campo vazio sozinho nao denuncia, porque vazio tambem e "
                   "resultado legitimo.")
        nunca, raros = xml_reader.auditar_caminhos(PAR, documentos)
        import pandas as pd

        a1, a2 = st.columns(2)
        a1.metric("Caminhos que nunca resolvem", len(nunca))
        a2.metric("Resolvem em menos de 5%", len(raros))

        st.markdown("**Nunca resolvem** — revisar na planilha de parametro")
        if nunca:
            st.dataframe(pd.DataFrame(nunca)[
                ["layout", "campo", "evento", "caminho", "documentos",
                 "obrigatorio", "situacao"]], width="stretch")
        else:
            st.success("Todos os caminhos declarados resolvem em pelo menos um documento.")

        st.markdown("**Resolvem em menos de 5% dos documentos** — pode ser bloco "
                    "opcional do eSocial (estrangeiro, nome social) ou tag errada")
        if raros:
            df = pd.DataFrame(raros)
            df["pct"] = df["pct"].map(lambda v: "%.1f%%" % v)
            st.dataframe(df[["layout", "campo", "evento", "caminho", "achou",
                             "documentos", "pct", "situacao"]], width="stretch")
        else:
            st.info("Nenhum caminho nessa faixa.")
