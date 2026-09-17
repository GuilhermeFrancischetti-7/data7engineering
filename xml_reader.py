# -*- coding: utf-8 -*-
"""
Leitor generico de XML do eSocial.

Nao ha codigo especifico por evento aqui. O que o leitor sabe fazer:
  1. achar o no do evento (evtAdmissao, evtDeslig, ...) dentro do envelope,
     que muda conforme a origem do arquivo (lote, retorno de processamento,
     consulta) -- por isso a busca e por tag, nao por posicao fixa;
  2. resolver um caminho da planilha de parametro (ex.:
     'evtAdmissao/trabalhador/cpfTrab') contra esse no;
  3. descobrir sozinho qual no se repete, para os leiautes que geram varias
     linhas por XML (dependente, rubrica de rescisao, item de remuneracao).

O nome do evento (S-2200, S-2299...) vem do proprio parametros.json, deduzido
da coluna 'Caminho no XML'. Assim, quando a planilha passar a mapear um evento
novo, o leitor reconhece o evento sem precisar de alteracao.
"""
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

SEM_NS = re.compile(r"^\{.*?\}")

# Separador de caminhos alternativos dentro de uma mesma celula da planilha.
SEP_ALTERNATIVA = "|"


def alternativas(caminho):
    """Um campo pode declarar mais de um caminho, separados por '|'.

    Existe porque 18 leiautes recebem linha de mais de um evento e o mesmo dado
    mora em lugares diferentes em cada um: a data do 1030 e dtAlteracao no
    S-2206 e dtAdm no S-2200. Serve tambem quando a tag e opcional dentro do
    proprio evento (dtEf aparece em 38 de 60 S-2206; dtAlteracao, em 60).

    A ordem na celula e a ordem de tentativa.
    """
    if not caminho:
        return []
    return [p.strip() for p in caminho.split(SEP_ALTERNATIVA) if p.strip()]


def _limpar_namespace(elem):
    for e in elem.iter():
        e.tag = SEM_NS.sub("", e.tag)
    return elem


def mapa_tag_evento(parametros):
    """tag do evento (evtAdmissao) -> codigo do evento (S-2200).

    Deduzido dos caminhos da planilha: o primeiro segmento de todo caminho e a
    tag raiz do evento, e a coluna Evento diz qual e o codigo.
    """
    # So tag de evento vira raiz. Sem esta guarda, um caminho que a planilha
    # gravou incompleto -- 'codCateg' em vez de 'evtAfastTemp/.../codCateg' --
    # registraria 'codCateg' como raiz de evento, e cada <codCateg> dentro de um
    # S-2200 viraria um S-2230 fantasma.
    #
    # A leitura e em duas passadas por causa dos caminhos alternativos. Num
    # campo como '...dtIniAfast | evtDeslig/...dtDeslig', declarado no S-2230, a
    # segunda alternativa aponta para OUTRO evento. Registrar a raiz dela com o
    # evento declarado no campo faria 'evtDeslig' valer como S-2230, e todo
    # desligamento sumiria dos leiautes que dependem do S-2299.
    #
    # Passada 1: so campos com um caminho unico, onde raiz e evento sao
    # inequivocos. Passada 2: preenche o que faltou, usando apenas a primeira
    # alternativa, que e a principal.
    mapa = {}
    campos = [c for mod in parametros["modulos"].values() for c in mod["campos"]
              if c.get("caminho") and c.get("evento")]

    def registrar(raiz, evento):
        if raiz.startswith("evt"):
            mapa.setdefault(raiz, evento)

    # Passada 0: o campo declara a lista de eventos pareada com a lista de
    # caminhos ('S-2200 | S-2300 | S-2306'). E o unico caso em que a raiz de uma
    # alternativa vem com o evento dito por extenso, entao vale mais que
    # qualquer deducao e vai primeiro. Sem isso nao ha como saber que
    # evtTSVAltContr e o S-2306: ele so aparece como terceira alternativa.
    for c in campos:
        eventos = c.get("eventos") or []
        alts = alternativas(c["caminho"])
        if len(eventos) > 1 and len(eventos) == len(alts):
            for evento, alt in zip(eventos, alts):
                registrar(alt.split("/")[0], evento)

    for exigir_unico in (True, False):
        for c in campos:
            alts = alternativas(c["caminho"])
            if exigir_unico and len(alts) != 1:
                continue
            for alt in (alts if exigir_unico else alts[:1]):
                registrar(alt.split("/")[0], c["evento"])

    # Eventos auxiliares: lidos, mas sem campo declarado em leiaute nenhum. A
    # raiz deles nao aparece em nenhum caminho, entao so a aba 'Eventos
    # auxiliares' da planilha sabe que evtTabRubrica e o S-1010. Sem isto os
    # arquivos cairiam em 'sem evento mapeado' e a descricao das rubricas nao
    # chegaria a planilha de De/Para.
    for raiz, evento in (parametros.get("eventos_auxiliares") or {}).items():
        registrar(raiz, evento)
    return mapa


def caminhos_incompletos(parametros):
    """Campos cujo caminho na planilha nao comeca pela tag do evento.

    Nao da para montar caminho absoluto com eles: o extrator cai na busca por
    nome de tag e registra pendencia. Listar aqui deixa o problema visivel na
    tela em vez de escondido no resultado.
    """
    fora = []
    for cod, mod in parametros["modulos"].items():
        for c in mod["campos"]:
            caminho = c.get("caminho", "")
            alts = alternativas(caminho)
            if alts and not any(a.split("/")[0].startswith("evt") for a in alts):
                fora.append((cod, c["campo"], c.get("evento", ""), caminho))
    return fora


class Documento:
    """Um no de evento ja localizado dentro de um arquivo XML."""

    def __init__(self, evento, no, arquivo):
        self.evento = evento
        self.no = no
        self.arquivo = arquivo
        # Id do recibo do eSocial: identifica o evento de forma unica. E o que
        # permite descartar o mesmo evento entregue em dois arquivos (pasta
        # duplicada, reenvio, lote que repete o retorno).
        self.id_evento = no.attrib.get("Id") or no.attrib.get("id") or ""
        self._cache_contagem = {}
        self._pais = None

    def ancestral(self, elem, tag):
        """Sobe a arvore a partir de 'elem' ate achar um ancestral com essa tag.

        ElementTree nao guarda ponteiro para o pai, entao o mapa e montado sob
        demanda. Serve para as junco es entre eventos: a linha de rubrica esta em
        detVerbas, mas a chave que liga ao pagamento (ideDmDev) fica no dmDev
        que a contem, varios niveis acima.
        """
        if elem is None:
            return None
        if self._pais is None:
            self._pais = {filho: pai for pai in self.no.iter() for filho in pai}
        atual = self._pais.get(elem)
        while atual is not None:
            if atual.tag == tag:
                return atual
            atual = self._pais.get(atual)
        return None

    # ---- resolucao de caminho ----------------------------------------
    def _relativo(self, caminho):
        """'evtAdmissao/trabalhador/cpfTrab' -> 'trabalhador/cpfTrab'.

        Quando o caminho nao comeca pela tag do evento, ele ja e relativo (ou
        esta incompleto na planilha): procura em qualquer profundidade, com
        './/'. Quem chama registra pendencia nesse caso.
        """
        partes = caminho.split("/")
        if partes and partes[0].startswith("evt"):
            return "/".join(partes[1:]) if len(partes) > 1 else ""
        return ".//" + caminho if caminho else ""

    def valor(self, caminho, base=None):
        """Primeiro valor textual do caminho. '' se a tag nao existir."""
        rel = self._relativo(caminho)
        origem = base if base is not None else self.no
        if not rel:
            return (origem.text or "").strip()
        achado = origem.find(rel)
        if achado is None:
            return ""
        return (achado.text or "").strip()

    def contar(self, caminho):
        if caminho not in self._cache_contagem:
            rel = self._relativo(caminho)
            self._cache_contagem[caminho] = len(self.no.findall(rel)) if rel else 1
        return self._cache_contagem[caminho]

    def instancias(self, caminho):
        rel = self._relativo(caminho)
        return self.no.findall(rel) if rel else [self.no]

    def valor_em(self, caminho, caminho_base, instancia):
        """Valor de um caminho que fica DENTRO de uma instancia repetida."""
        sufixo = caminho[len(caminho_base):].lstrip("/")
        if not sufixo:
            return (instancia.text or "").strip()
        achado = instancia.find(sufixo)
        return (achado.text or "").strip() if achado is not None else ""


def ler_xml(conteudo, nome_arquivo, mapa_eventos):
    """Devolve os Documentos (nos de evento) contidos num XML.

    Um arquivo pode conter mais de um evento -- lotes trazem varios.
    """
    if isinstance(conteudo, bytes):
        texto = conteudo.decode("utf-8", errors="replace")
    else:
        texto = conteudo
    texto = texto.lstrip("﻿ \r\n\t")

    try:
        raiz = ET.fromstring(texto)
    except ET.ParseError as e:
        raise ValueError("XML invalido em %s: %s" % (nome_arquivo, e))

    _limpar_namespace(raiz)

    documentos = []
    for elem in raiz.iter():
        if elem.tag in mapa_eventos and _e_no_de_evento(elem):
            documentos.append(Documento(mapa_eventos[elem.tag], elem, nome_arquivo))

    # se a raiz ja for o proprio evento
    if not documentos and raiz.tag in mapa_eventos and _e_no_de_evento(raiz):
        documentos.append(Documento(mapa_eventos[raiz.tag], raiz, nome_arquivo))

    return documentos


def _e_no_de_evento(elem):
    """Distingue o evento de verdade de uma tag homonima que so carrega texto.

    O S-1299 (fechamento do periodo) declara quais eventos houve com flags de
    mesmo nome:

        <infoFech><evtRemun>S</evtRemun><evtPgtos>S</evtPgtos></infoFech>

    Sao respostas 'sim/nao', nao eventos. Como o nome comeca com 'evt', a
    checagem do prefixo nao basta -- cada flag virava um evento fantasma cujo
    conteudo era a letra 'S', e todos os caminhos daquele leiaute davam vazio.

    Evento real sempre tem filhos (ideEvento, ideEmpregador...); a flag e folha.
    """
    return len(elem) > 0


# ---------------------------------------------------------------------
# Entrada de arquivos: XML solto ou ZIP (inclusive ZIP com subpastas e
# ZIP dentro de ZIP, que e como as extracoes costumam chegar).
# ---------------------------------------------------------------------
LIMITE_PROFUNDIDADE_ZIP = 3


def _e_zip(nome, dados):
    return nome.lower().endswith(".zip") or dados[:2] == b"PK"


def expandir_entrada(nome, dados, profundidade=0):
    """Devolve [(nome, bytes)] de todo XML encontrado, entrando em ZIPs.

    Ignora o que nao for .xml. Erros de um arquivo nao derrubam o lote:
    voltam na lista de problemas.
    """
    encontrados, problemas = [], []

    if _e_zip(nome, dados):
        if profundidade >= LIMITE_PROFUNDIDADE_ZIP:
            problemas.append((nome, "ZIP aninhado alem de %d niveis -- ignorado."
                              % LIMITE_PROFUNDIDADE_ZIP))
            return encontrados, problemas
        try:
            with zipfile.ZipFile(io.BytesIO(dados)) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    interno = info.filename
                    # protecao contra caminho malicioso no zip
                    if os.path.isabs(interno) or ".." in interno.replace("\\", "/").split("/"):
                        problemas.append((interno, "Caminho suspeito dentro do ZIP -- ignorado."))
                        continue
                    try:
                        bruto = z.read(info)
                    except Exception as e:
                        problemas.append((interno, "Falha ao ler do ZIP: %s" % e))
                        continue
                    sub_ok, sub_prob = expandir_entrada(interno, bruto, profundidade + 1)
                    encontrados.extend(sub_ok)
                    problemas.extend(sub_prob)
        except zipfile.BadZipFile as e:
            problemas.append((nome, "ZIP corrompido ou nao suportado: %s" % e))
        return encontrados, problemas

    if nome.lower().endswith(".rar"):
        problemas.append((nome, "Arquivo .rar nao e suportado. Reempacote como .zip."))
        return encontrados, problemas

    if nome.lower().endswith(".xml"):
        encontrados.append((nome, dados))
    return encontrados, problemas


EXTENSOES_ENTRADA = (".xml", ".zip")


# O eSocial nomeia o arquivo com o evento -- "ID...S-1200.xml" -- e a massa
# costuma vir separada em pastas "S- 1200/". Isso permite descartar arquivo de
# evento que nenhum leiaute escolhido usa SEM ABRIR o arquivo.
#
# Numa massa de teste sao 226 mil arquivos, dos quais 193 mil sao S-1200. Quem vai
# gerar so o 1012 nao precisa de nenhum deles.
#
# A regra e conservadora: so descarta quando o nome ou a pasta dizem o evento de
# forma inequivoca. Nao dizendo, o arquivo e lido -- massa com nome arbitrario
# continua funcionando como antes, so nao ganha a aceleracao.
_EVENTO_NO_NOME = re.compile(r"S-?\s?(\d{4})", re.I)


def evento_pelo_nome(caminho_relativo):
    """Codigo do evento deduzido do nome do arquivo ou da pasta, ou None."""
    achados = _EVENTO_NO_NOME.findall(caminho_relativo)
    codigos = {"S-" + a for a in achados}
    # mais de um codigo diferente no caminho: ambiguo, nao arrisca
    return codigos.pop() if len(codigos) == 1 else None


def varrer_pasta(caminho, recursivo=True, eventos=None):
    """Percorre uma pasta do disco e devolve (nome_relativo, caminho_completo).

    E um gerador: entrega um arquivo por vez em vez de listar a pasta inteira
    na memoria. Numa massa de varios GB e a diferenca entre rodar e estourar.

    Ler direto do disco tambem escapa do limite de upload do navegador -- o app
    roda na propria maquina, entao nao ha motivo para o arquivo dar a volta pelo
    HTTP so para voltar ao mesmo disco.
    """
    caminho = os.path.expanduser(os.path.expandvars(caminho.strip().strip('"')))
    if not os.path.isdir(caminho):
        raise NotADirectoryError("Pasta nao encontrada: %s" % caminho)

    if recursivo:
        for raiz, _dirs, nomes in os.walk(caminho):
            for nome in sorted(nomes):
                if nome.lower().endswith(EXTENSOES_ENTRADA):
                    completo = os.path.join(raiz, nome)
                    rel = os.path.relpath(completo, caminho)
                    if eventos is not None:
                        ev = evento_pelo_nome(rel)
                        if ev is not None and ev not in eventos:
                            continue
                    yield rel, completo
    else:
        for nome in sorted(os.listdir(caminho)):
            completo = os.path.join(caminho, nome)
            if os.path.isfile(completo) and nome.lower().endswith(EXTENSOES_ENTRADA):
                yield nome, completo


def contar_pasta(caminho, recursivo=True, eventos=None):
    """Quantidade e tamanho total, para mostrar antes de processar.

    Com 'eventos', conta so o que sera lido -- o numero na tela passa a ser o
    trabalho real, e nao o tamanho da pasta.
    """
    qtd = tamanho = 0
    for _rel, completo in varrer_pasta(caminho, recursivo, eventos):
        qtd += 1
        try:
            tamanho += os.path.getsize(completo)
        except OSError:
            pass
    return qtd, tamanho


def _entradas_de_pasta(caminho, recursivo=True, eventos=None):
    for rel, completo in varrer_pasta(caminho, recursivo, eventos):
        try:
            with open(completo, "rb") as f:
                yield rel, f.read()
        except OSError as e:
            yield rel, e  # sinaliza a falha sem interromper a varredura


def auditar_caminhos(parametros, documentos, limite_raro=5.0):
    """Mede cada caminho declarado contra a massa que acabou de ser lida.

    Caminho que nunca resolve, tendo documentos do proprio evento na massa, e
    quase sempre tag no evento errado. Foi assim que apareceram os erros do
    1014/1025 na v9 e o evento fantasma do S-1200 -- todos passavam despercebidos
    porque campo vazio e resultado legitimo na maior parte dos casos.

    Devolve (nunca_resolvem, raros). 'Raro' pode ser bloco opcional do eSocial
    (dados de estrangeiro, nome social) ou tag errada: quem olha decide.
    """
    por_evento = {}
    for d in documentos:
        por_evento.setdefault(d.evento, []).append(d)

    nunca, raros = [], []
    for cod in sorted(parametros["modulos"]):
        mod = parametros["modulos"][cod]
        for c in mod["campos"]:
            caminho, evento = c.get("caminho", ""), c.get("evento", "")
            if not (caminho and evento):
                continue
            alvo = por_evento.get(evento)
            if not alvo:
                continue  # evento ausente da massa: nao da para julgar
            achou = sum(1 for d in alvo
                        if any(d.valor(a) for a in alternativas(caminho)))
            item = {"layout": cod, "campo": c["campo"], "evento": evento,
                    "caminho": caminho, "documentos": len(alvo), "achou": achou,
                    "pct": 100.0 * achou / len(alvo),
                    "obrigatorio": c.get("obrigatorio", False),
                    "situacao": c.get("situacao", "")}
            if achou == 0:
                nunca.append(item)
            elif item["pct"] < limite_raro:
                raros.append(item)

    raros.sort(key=lambda x: x["pct"])
    return nunca, raros


def carregar_documentos(arquivos=None, parametros=None, pasta=None,
                        recursivo=True, progresso=None, eventos=None):
    """Le a massa e devolve (documentos, problemas, estatistica, resumo).

    Duas entradas possiveis:
      arquivos -> iteravel de (nome, bytes), como vem do upload
      pasta    -> caminho no disco, varrido em streaming

    Os bytes de cada arquivo sao descartados assim que o XML e parseado, entao
    o pico de memoria acompanha o maior arquivo, e nao a massa inteira.
    """
    mapa = mapa_tag_evento(parametros)
    documentos, problemas = [], []
    vistos = set()
    duplicados = 0
    nao_mapeados = []
    lidos = 0

    origem = (_entradas_de_pasta(pasta, recursivo, eventos) if pasta
              else (arquivos or []))

    for nome, dados in origem:
        if isinstance(dados, Exception):
            problemas.append((nome, "Falha ao abrir: %s" % dados))
            continue

        encontrados, prob = expandir_entrada(nome, dados)
        problemas.extend(prob)
        del dados  # nao segura o arquivo original enquanto processa o conteudo

        for nome_xml, bruto in encontrados:
            lidos += 1
            if progresso and lidos % 200 == 0:
                # Alem do numero, diz ONDE esta. Numa massa de 226 mil arquivos
                # a barra ficava minutos parada no mesmo texto, sem dizer se
                # estava no S-2200 ou ainda nos 193 mil do S-1200.
                progresso(lidos, evento_pelo_nome(nome_xml) or
                          os.path.dirname(nome_xml) or "")
            try:
                docs = ler_xml(bruto, nome_xml, mapa)
            except ValueError as e:
                problemas.append((nome_xml, str(e)))
                continue
            if not docs:
                # Nao e erro: e evento que a planilha de parametro ainda nao
                # mapeia (S-1010, S-2220, S-2250...). Vira aviso, nao problema.
                nao_mapeados.append(nome_xml)
                continue
            for d in docs:
                if d.id_evento:
                    if d.id_evento in vistos:
                        duplicados += 1
                        continue
                    vistos.add(d.id_evento)
                documentos.append(d)

    estatistica = {}
    for d in documentos:
        estatistica[d.evento] = estatistica.get(d.evento, 0) + 1

    resumo = {
        "xmls_lidos": lidos,
        "duplicados_descartados": duplicados,
        "sem_evento_mapeado": nao_mapeados,
    }
    return documentos, problemas, estatistica, resumo


# ---- leitura salva ----------------------------------------------------
# O De/Para do cliente volta dias depois da leitura. Sem isto, gerar os layouts
# exigia varrer a massa de novo -- horas no piloto. O arquivo guarda o no de
# cada evento ja selecionado e sem namespace, exatamente o que o Documento
# segura; ao carregar, os documentos voltam identicos e writer, De/Para e
# testes funcionam sem saber de onde vieram.
#
# E um .zip com manifesto.json + eventos.jsonl (uma linha por evento). Contem
# o mesmo dado pessoal dos XMLs: fica na maquina, como a massa.
FORMATO_LEITURA = 1


def salvar_leitura(destino, massa, parametros, origem="", eventos_pedidos=None):
    """Grava (documentos, problemas, estatistica, resumo) em 'destino'.

    eventos_pedidos: o filtro de eventos usado na leitura da pasta. Guardado
    para distinguir, ao reabrir, evento que nao foi lido de evento que nao
    veio na massa. None = leitura sem filtro (upload).
    """
    import datetime
    import json
    documentos, problemas, estatistica, resumo = massa
    manifesto = {
        "formato": FORMATO_LEITURA,
        "gravado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "origem": origem,
        "parametro": parametros.get("origem", ""),
        "eventos": sorted(estatistica),
        "eventos_pedidos": eventos_pedidos,
        "estatistica": estatistica,
        "resumo": resumo,
        "problemas": [list(p) for p in problemas],
    }
    pasta = os.path.dirname(os.path.abspath(destino))
    os.makedirs(pasta, exist_ok=True)
    temporario = destino + ".parcial"
    with zipfile.ZipFile(temporario, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=1))
        with z.open("eventos.jsonl", "w", force_zip64=True) as f:
            for d in documentos:
                linha = {"evento": d.evento, "arquivo": d.arquivo,
                         "xml": ET.tostring(d.no, encoding="unicode")}
                f.write((json.dumps(linha, ensure_ascii=False) + "\n").encode("utf-8"))
    # so troca o arquivo quando terminou: interrompido no meio nao deixa uma
    # leitura truncada com cara de completa
    os.replace(temporario, destino)
    return manifesto


def ler_manifesto(caminho):
    import json
    with zipfile.ZipFile(caminho) as z:
        return json.loads(z.read("manifesto.json").decode("utf-8"))


def carregar_leitura(caminho, progresso=None):
    """Devolve (documentos, problemas, estatistica, resumo, manifesto)."""
    import json
    manifesto = ler_manifesto(caminho)
    if manifesto.get("formato") != FORMATO_LEITURA:
        raise ValueError("Leitura salva em formato %s; este extrator le o %s. "
                         "Leia a pasta de novo." % (manifesto.get("formato"),
                                                    FORMATO_LEITURA))
    documentos = []
    with zipfile.ZipFile(caminho) as z, z.open("eventos.jsonl") as f:
        for n, linha in enumerate(io.TextIOWrapper(f, encoding="utf-8"), start=1):
            item = json.loads(linha)
            documentos.append(Documento(item["evento"], ET.fromstring(item["xml"]),
                                        item["arquivo"]))
            if progresso and n % 2000 == 0:
                progresso(n, item["evento"])
    problemas = [tuple(p) for p in manifesto.get("problemas", [])]
    return (documentos, problemas, manifesto.get("estatistica", {}),
            manifesto.get("resumo", {}), manifesto)


def juntar_massas(base, extra):
    """Soma duas massas (documentos, problemas, estatistica, resumo).

    Caso real: a leitura salva foi feita e depois o cliente manda os XMLs que
    faltavam. O evento repetido (mesmo Id de recibo) conta uma vez so, como na
    leitura de uma pasta: vale o da base.
    """
    docs_b, prob_b, _, res_b = base
    docs_e, prob_e, _, res_e = extra
    vistos = {d.id_evento for d in docs_b if d.id_evento}
    documentos = list(docs_b)
    repetidos = 0
    for d in docs_e:
        if d.id_evento and d.id_evento in vistos:
            repetidos += 1
            continue
        if d.id_evento:
            vistos.add(d.id_evento)
        documentos.append(d)
    estatistica = {}
    for d in documentos:
        estatistica[d.evento] = estatistica.get(d.evento, 0) + 1
    resumo = {
        "xmls_lidos": res_b.get("xmls_lidos", 0) + res_e.get("xmls_lidos", 0),
        "duplicados_descartados": (res_b.get("duplicados_descartados", 0)
                                   + res_e.get("duplicados_descartados", 0) + repetidos),
        "sem_evento_mapeado": (list(res_b.get("sem_evento_mapeado", []))
                               + list(res_e.get("sem_evento_mapeado", []))),
        "acrescentados": len(documentos) - len(docs_b),
    }
    return documentos, list(prob_b) + list(prob_e), estatistica, resumo
