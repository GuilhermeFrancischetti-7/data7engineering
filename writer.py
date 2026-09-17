# -*- coding: utf-8 -*-
"""
Monta as linhas no layout Senior a partir dos documentos XML ja lidos.

Motor unico para os 48 leiautes: o que muda de um para o outro esta todo em
parametros.json, nunca em codigo. Cada campo carrega uma acao, e e a acao que
decide o que escrever na coluna:

  DIRETO         copia o valor da tag (datas viram DD/MM/AAAA, decimais viram
                 virgula, texto e truncado no tamanho do layout)
  DEPARA_*       traduz pela tabela De/Para; sem tabela, mantem o valor CRU do
                 eSocial e registra pendencia -- nunca inventa o codigo Senior
  FIXO           constante declarada na planilha de parametro
  SEQUENCIAL     numeracao gerada na carga (CODDEP, SEQALT)
  REGRA          transformacao descrita em texto na planilha; so as regras
                 implementadas em REGRAS_IMPLEMENTADAS rodam, o resto vira
                 pendencia com o texto original, para nao fingir que aplicou
  VAZIO          o mapeamento manda nao preencher
  RELATORIO      o dado existe, mas fora do XML (relatorio do legado)
  SEM_ORIGEM     nao ha tag correspondente no eSocial
  PENDENTE       a planilha ainda nao definiu

O arquivo final sai SEM cabecalho, so as linhas de dados, campos separados por
';' na ordem exata do leiaute.
"""
import re
from datetime import datetime

from depara import _no_repeticao
from xml_reader import alternativas

SEPARADOR = ";"

# Acoes que produzem valor sem consultar o XML.
SEM_LEITURA = {"FIXO", "VAZIO", "RELATORIO", "SEM_ORIGEM", "SEQUENCIAL"}

# Motivo apresentado no relatorio de pendencias, por acao.
MOTIVO = {
    "RELATORIO": "Dado nao esta no XML do eSocial. Fonte: relatorio do sistema legado.",
    "SEM_ORIGEM": "Nao existe tag correspondente no eSocial. Definir fora do extrator.",
    "PENDENTE": "Definicao ainda em aberto na planilha de parametro.",
    "VAZIO": None,  # regra explicita, nao e pendencia
}


def converter_data(valor):
    """eSocial manda AAAA-MM-DD (as vezes com hora). Senior quer DD/MM/AAAA."""
    if not valor:
        return ""
    bruto = valor[:10]
    try:
        return datetime.strptime(bruto, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return valor


def formatar(valor, campo):
    """Aplica tipo/tamanho do layout Senior ao valor cru."""
    if valor == "":
        return ""

    tipo = (campo.get("tipo") or "").lower()
    nome = campo.get("campo", "")

    if re.match(r"^\d{4}-\d{2}-\d{2}", valor) and (
            "data" in tipo or nome.startswith("DAT") or "data" in (campo.get("descricao") or "").lower()):
        return converter_data(valor)

    # Competencia 'AAAA-MM' (perApur) num campo de data de mascara MM/YYYY.
    if (re.match(r"^\d{4}-\d{2}$", valor) and "data" in tipo
            and (campo.get("mascara") or "").upper() == "MM/YYYY"):
        return "%s/%s" % (valor[5:7], valor[:4])

    if "valor" in tipo or "decimal" in tipo:
        try:
            return ("%.2f" % float(valor)).replace(".", ",")
        except ValueError:
            return valor

    try:
        tam = int(campo.get("tamanho") or 0)
    except (TypeError, ValueError):
        tam = 0
    if tam and "texto" in tipo and len(valor) > tam:
        return valor[:tam]

    return valor


# ---------------------------------------------------------------------
# Regras nomeadas. So entra aqui regra com definicao clara na planilha.
# O que nao estiver implementado NAO e aplicado por aproximacao: vira
# pendencia com o texto original, para a revisao decidir.
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# Juncao entre eventos
#
# Alguns campos so existem cruzando dois eventos. O caso previsto pela
# Fronter: a data de pagamento das verbas rescisorias esta no S-1210, nao no
# S-2299, e os dois se ligam pela tag ideDmDev (identificador do demonstrativo
# de valores devidos) dentro do mesmo CPF.
#
# O indice e montado uma vez por massa e reaproveitado pelos 41 leiautes.
# ---------------------------------------------------------------------
_CACHE_JUNCAO = {}


def indice_pagamentos(documentos):
    """(cpf, ideDmDev) -> data de pagamento, a partir dos S-1210."""
    chave = id(documentos)
    if chave in _CACHE_JUNCAO:
        return _CACHE_JUNCAO[chave]

    indice = {}
    for d in documentos:
        if d.evento != "S-1210":
            continue
        for benef in d.no.findall("ideBenef"):
            cpf = (benef.findtext("cpfBenef") or "").strip()
            for pagamento in benef.findall("infoPgto"):
                data = (pagamento.findtext("dtPgto") or "").strip()
                if not data:
                    continue
                for det in pagamento.findall("detPgtoFl"):
                    ide = (det.findtext("ideDmDev") or "").strip()
                    if ide:
                        indice[(cpf, ide)] = data

    _CACHE_JUNCAO.clear()
    _CACHE_JUNCAO[chave] = indice
    return indice


_CACHE_ESTAB = {}


def indice_estabelecimentos(documentos):
    """CPF -> CNPJ do estabelecimento (14 digitos), o mais recente.

    O NUMEMP e o CNPJ completo, com estabelecimento. Mas metade dos eventos nao
    o carrega: S-2230, S-2240 e S-1210 so tem o ideEmpregador, que e a raiz de 8
    digitos e nao distingue filial. Na massa de teste isso fazia os 592 colaboradores
    sairem com o mesmo 12345678, e as duas filiais sumiam do resultado.

    O CNPJ completo esta em outro evento da mesma pessoa: localTrabGeral no
    vinculo, ideEstabLot na folha e na rescisao. Medido na massa de teste: 100% dos
    CPFs de S-2230 e de S-2240 resolvem por aqui, e 270 dos 283 S-2300 sem
    localTrabGeral.

    Quem passou por mais de uma filial fica com a MAIS RECENTE. A data sai do
    proprio evento, nesta ordem: perApur (competencia da folha), depois a maior
    data ISO do documento, e por fim o carimbo de transmissao do Id -- que todo
    evento tem, no formato ID + tpInsc + nrInsc + AAAAMMDDHHMMSS + sequencial.
    """
    chave = id(documentos)
    if chave in _CACHE_ESTAB:
        return _CACHE_ESTAB[chave]

    def quando(doc):
        per = (doc.no.findtext(".//perApur") or "").strip()
        if per:
            return per if len(per) > 7 else per + "-01"
        datas = [(e.text or "").strip() for e in doc.no.iter()
                 if e.text and re.match(r"^\d{4}-\d{2}-\d{2}$", (e.text or "").strip())]
        if datas:
            return max(datas)
        ide = doc.no.get("Id") or ""
        m = re.match(r"^ID\d{15}(\d{4})(\d{2})(\d{2})", ide)
        return "%s-%s-%s" % m.groups() if m else ""

    melhor = {}
    for d in documentos:
        cnpjs = set()
        for e in d.no.iter():
            if e.tag in ("localTrabGeral", "ideEstabLot"):
                v = (e.findtext("nrInsc") or "").strip()
                if len(v) == 14:
                    cnpjs.add(v)
        if not cnpjs:
            continue
        cpfs = {(e.text or "").strip() for e in d.no.iter()
                if e.tag in ("cpfTrab", "cpfBenef") and e.text}
        if not cpfs:
            continue
        data = quando(d)
        # com dois estabelecimentos no MESMO documento nao da para dizer de quem
        # e cada um: o documento nao amarra CPF a estabelecimento nesse caso.
        if len(cnpjs) > 1:
            continue
        cnpj = cnpjs.pop()
        for cpf in cpfs:
            if cpf not in melhor or data >= melhor[cpf][1]:
                melhor[cpf] = (cnpj, data)

    indice = {cpf: v[0] for cpf, v in melhor.items()}
    _CACHE_ESTAB.clear()
    _CACHE_ESTAB[chave] = indice
    return indice


def _regra_truncar_40(valor, campo, ctx):
    return valor[:40]


def _regra_data_pagamento_s1210(valor, campo, ctx):
    """Data de pagamento do S-1210, associada pelo CPF + ideDmDev.

    O S-1210 so empresta a data: quem gera a linha e a rescisao (S-2299) ou a
    folha (S-1200). O ideDmDev que identifica o demonstrativo fica no dmDev --
    acima da instancia quando a linha e uma rubrica, por isso a subida na
    arvore; sem instancia (mestre de rescisao, calculo), vale o primeiro dmDev
    do evento que tiver pagamento. Sem par no S-1210, vazio: nao ha data para
    inventar.
    """
    doc, inst = ctx["doc"], ctx["inst"]
    cpf_de = {"S-2299": "evtDeslig/ideVinculo/cpfTrab",
              "S-1200": "evtRemun/ideTrabalhador/cpfTrab"}
    if doc.evento not in cpf_de:
        return valor
    cpf = doc.valor(cpf_de[doc.evento])
    indice = ctx["indice_pagamentos"]
    dm = doc.ancestral(inst, "dmDev") if inst is not None else None
    candidatos = [dm] if dm is not None else list(doc.no.iter("dmDev"))
    for dm in candidatos:
        ide = (dm.findtext("ideDmDev") or "").strip()
        if cpf and ide and (cpf, ide) in indice:
            return indice[(cpf, ide)]
    return ""


def _regra_dias_aviso_indenizado(valor, campo, ctx):
    """dtProjFimAPI - dtDeslig, em dias.

    O aviso previo indenizado nao vem como quantidade no eSocial: vem como a
    data projetada de fim. A diferenca para a data de desligamento e o numero
    de dias, que e o que o layout Senior pede.
    """
    doc = ctx["doc"]
    fim = doc.valor("evtDeslig/infoDeslig/dtProjFimAPI")
    ini = doc.valor("evtDeslig/infoDeslig/dtDeslig")
    if not (fim and ini):
        return ""
    try:
        d1 = datetime.strptime(fim[:10], "%Y-%m-%d")
        d0 = datetime.strptime(ini[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    dias = (d1 - d0).days
    return str(dias) if dias > 0 else ""


def _fone_digitos(valor, ctx):
    """Digitos do telefone deste evento: foneFixo e, se vazio, foneCel.

    A planilha aponta os tres campos (DDITEL, DDDTEL, NUMTEL) para o mesmo
    foneFixo, entao os tres chegam aqui com o numero inteiro. Quem separa e a
    regra. O eSocial nao guarda DDI: o numero vem so com DDD + assinante.
    """
    doc = ctx.get("doc")
    d = ""
    if doc is not None:
        for tag in ("foneFixo", "foneCel"):
            d = re.sub(r"\D", "", doc.no.findtext(".//" + tag) or "")
            if d:
                break
    if not d:
        d = re.sub(r"\D", "", valor or "")
    if d.startswith("55") and len(d) > 11:
        d = d[2:]
    return d


def _competencia(valor):
    """'AAAA-MM' (perApur do S-1200) -> (ano, mes), ou None."""
    m = re.match(r"^(\d{4})-(\d{2})$", (valor or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _regra_primeiro_dia_competencia(valor, campo, ctx):
    comp = _competencia(valor)
    return "01/%02d/%04d" % (comp[1], comp[0]) if comp else ""


def _regra_ultimo_dia_competencia(valor, campo, ctx):
    import calendar
    comp = _competencia(valor)
    if not comp:
        return ""
    return "%02d/%02d/%04d" % (calendar.monthrange(comp[0], comp[1])[1], comp[1], comp[0])


_CACHE_TERMINO = {}


def _terminos_afastamento(documentos):
    """cpf -> ([datas de inicio], [datas de termino]) dos S-2230, ordenadas."""
    chave = id(documentos)
    if chave not in _CACHE_TERMINO:
        indice = {}
        for d in documentos:
            if d.evento != "S-2230":
                continue
            cpf = d.valor("evtAfastTemp/ideVinculo/cpfTrab")
            ini = d.valor("evtAfastTemp/infoAfastamento/iniAfastamento/dtIniAfast")
            fim = d.valor("evtAfastTemp/infoAfastamento/fimAfastamento/dtTermAfast")
            inicios, fins = indice.setdefault(cpf, ([], []))
            if ini:
                inicios.append(ini)
            if fim:
                fins.append(fim)
        for inicios, fins in indice.values():
            inicios.sort()
            fins.sort()
        _CACHE_TERMINO.clear()
        _CACHE_TERMINO[chave] = indice
    return _CACHE_TERMINO[chave]


def _regra_dias_ferias(valor, campo, ctx):
    """Dias de ferias: qtDias do recibo (S-1210) ou termino - inicio + 1 (S-2230).

    No S-2230 o termino costuma vir em OUTRO XML, sem o inicio. Casa pelo CPF:
    o primeiro termino a partir do inicio, desde que nao haja outro inicio da
    mesma pessoa antes dele -- senao o termino e do afastamento seguinte.
    Sem termino casado, vazio: nao ha como saber quantos dias foram.
    """
    doc = ctx["doc"]
    if doc.evento == "S-1210":
        return valor
    if doc.evento != "S-2230":
        return ""
    ini = doc.valor("evtAfastTemp/infoAfastamento/iniAfastamento/dtIniAfast")
    fim = doc.valor("evtAfastTemp/infoAfastamento/fimAfastamento/dtTermAfast")
    if ini and not fim:
        cpf = doc.valor("evtAfastTemp/ideVinculo/cpfTrab")
        inicios, fins = _terminos_afastamento(ctx["documentos"]).get(cpf, ([], []))
        proximo_inicio = next((i for i in inicios if i > ini), None)
        fim = next((f for f in fins if f >= ini
                    and (proximo_inicio is None or f < proximo_inicio)), "")
    try:
        d_ini = datetime.strptime(ini[:10], "%Y-%m-%d")
        d_fim = datetime.strptime(fim[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return str((d_fim - d_ini).days + 1)


def _regra_ddi(valor, campo, ctx):
    """DDI fixo do Brasil.

    O eSocial nao transmite DDI em foneFixo/foneCel; a planilha fixa 055, que e
    o que cabe na mascara 999 do campo. Nao ha aqui codigo de pais a buscar.
    """
    return "055"


def _regra_ddd(valor, campo, ctx):
    """Os 2 primeiros digitos, quando o numero tem DDD."""
    d = _fone_digitos(valor, ctx)
    return d[:2] if len(d) >= 10 else ""


def _regra_numero_telefone(valor, campo, ctx):
    """O assinante, sem DDI e sem DDD."""
    d = _fone_digitos(valor, ctx)
    return d[2:] if len(d) >= 10 else d


def _regra_quando_tpinsc(esperado):
    """So preenche quando o tipo de inscricao do estabelecimento for o esperado.

    O 1001 tem tres colunas para a MESMA tag nrInsc: NUMCGC (CNPJ), NCAEPF
    (CAEPF) e NUMCNO (CNO). Qual delas recebe o numero depende do tpInsc que
    vem ao lado dele no ideEstab. Sem essa condicao as tres saiam preenchidas
    com o mesmo valor -- e o CNPJ de 14 digitos ainda estouraria o NUMCNO, que
    tem 12.
    """
    def regra(valor, campo, ctx):
        doc, inst, base = ctx["doc"], ctx["inst"], ctx["base"]
        tp = ""
        for caminho in ("evtTabEstab/infoEstab/inclusao/ideEstab/tpInsc",
                        "evtTabEstab/infoEstab/alteracao/ideEstab/tpInsc"):
            tp = doc.valor(caminho)
            if tp:
                break
        return valor if tp.strip() == esperado else ""
    return regra


_CACHE_CEP = {}


def indice_cep_bairro(documentos):
    """(codMunic, bairro) -> CEP mais frequente na massa.

    O 1011 e uma linha por BAIRRO, mas o eSocial so tem CEP por pessoa: um
    bairro grande aparece com dezenas de CEPs diferentes. Escolher o primeiro
    que aparecer daria um CEP conforme a ordem dos arquivos. O mais frequente e
    estavel e e o que melhor representa o bairro. Empate resolve pelo menor
    CEP, so para a resposta nao mudar entre execucoes.
    """
    chave = id(documentos)
    if chave in _CACHE_CEP:
        return _CACHE_CEP[chave]
    contagem = {}
    for doc in documentos:
        for br in doc.no.iter("brasil"):
            munic = (br.findtext("codMunic") or "").strip()
            bairro = (br.findtext("bairro") or "").strip()
            cep = (br.findtext("cep") or "").strip()
            if not (bairro and cep):
                continue
            contagem.setdefault((munic, bairro), {})
            contagem[(munic, bairro)][cep] =                 contagem[(munic, bairro)].get(cep, 0) + 1
    indice = {k: max(sorted(v), key=lambda c: v[c])
              for k, v in contagem.items()}
    _CACHE_CEP.clear()
    _CACHE_CEP[chave] = indice
    return indice


def _regra_cep_mais_frequente(valor, campo, ctx):
    """CEP que mais se repete no bairro desta linha."""
    doc = ctx["doc"]
    br = next(doc.no.iter("brasil"), None)
    if br is None:
        return ""
    munic = (br.findtext("codMunic") or "").strip()
    bairro = (br.findtext("bairro") or "").strip()
    if not bairro:
        return ""
    return indice_cep_bairro(ctx["documentos"]).get((munic, bairro), valor)


REGRAS_IMPLEMENTADAS = {
    "truncar em 40 caracteres": _regra_truncar_40,
    "dtprojfimapi - dtdeslig = dias de aviso indenizado": _regra_dias_aviso_indenizado,
    "data de pagamento do s-1210, associado pelo idedmdev": _regra_data_pagamento_s1210,
    "desmembrar o telefone; ddi fixo 055": _regra_ddi,
    "2 primeiros dígitos de fonefixo": _regra_ddd,
    "restante de fonefixo (ou fonecel)": _regra_numero_telefone,
    "quando tpinsc=1": _regra_quando_tpinsc("1"),
    "quando tpinsc=3 (caepf)": _regra_quando_tpinsc("3"),
    "quando tpinsc=4 (cno)": _regra_quando_tpinsc("4"),
    "cep mais frequente do bairro": _regra_cep_mais_frequente,
    "1o dia da competência": _regra_primeiro_dia_competencia,
    "dias de férias: qtdias do recibo, ou término - início + 1 do afastamento": _regra_dias_ferias,
    "último dia da competência": _regra_ultimo_dia_competencia,
}


def _aplicar_regra(texto_regra, valor, campo, ctx):
    chave = (texto_regra or "").strip().lower().rstrip(".")
    fn = REGRAS_IMPLEMENTADAS.get(chave)
    if fn:
        return fn(valor, campo, ctx), None
    if chave in ("enviar vazio", ""):
        return "", None
    m = re.match(r'valor fixo\s*"?([^"]*)"?$', chave, re.I)
    if m:
        return m.group(1), None
    return valor, ("Regra nao implementada: \"%s\". Valor cru mantido."
                   % (texto_regra or "").strip())


_MAPA_RAIZ = {}


def _raiz_do_evento(caminho):
    """Codigo do evento a que um caminho pertence, pela tag raiz."""
    return _MAPA_RAIZ.get(caminho.split("/")[0], "")


_CACHE_MATRIZ = {}


def matriz_da_massa(documentos):
    """Raiz de 8 digitos -> CNPJ de 14 da matriz, colhido dos S-1005.

    O S-1000 nao carrega CNPJ completo: o ideEmpregador tem so a raiz de 8. O
    leiaute 1000 e a empresa, e a empresa e a matriz -- o estabelecimento de
    ordem 0001. Ele existe na massa, nos S-1005, entao e leitura, nao invencao.
    Se a matriz nao aparecer, nao se escolhe uma filial no lugar dela.
    """
    chave = id(documentos)
    if chave in _CACHE_MATRIZ:
        return _CACHE_MATRIZ[chave]
    achados = {}
    for doc in documentos:
        for e in doc.no.iter():
            if not e.tag.endswith("nrInsc"):
                continue
            v = (e.text or "").strip()
            if len(v) == 14 and v.isdigit() and v[8:12] == "0001":
                achados[v[:8]] = v
    _CACHE_MATRIZ.clear()
    _CACHE_MATRIZ[chave] = achados
    return achados


_CACHE_EMPRESA = {}


def indice_empresa(documentos):
    """Raiz de 8 digitos -> o documento S-1000 daquela empresa, o mais recente.

    O S-1000 e o cadastro da empresa e nao tem estabelecimento; o S-1005 e o
    estabelecimento e nao tem razao social. O 1001 pede os dois na mesma linha.
    A ponte entre eles e o ideEmpregador/nrInsc, que os dois carregam -- a mesma
    ideia do indice por CPF que ja liga folha e vinculo.
    """
    chave = id(documentos)
    if chave in _CACHE_EMPRESA:
        return _CACHE_EMPRESA[chave]
    achados = {}
    for doc in documentos:
        if doc.evento != "S-1000":
            continue
        raiz = (doc.no.findtext(".//ideEmpregador/nrInsc") or "").strip()
        if raiz:
            achados[raiz] = doc
    _CACHE_EMPRESA.clear()
    _CACHE_EMPRESA[chave] = achados
    return achados


def _estab_do_documento(doc, indice):
    """CNPJ de 14 digitos deste documento, pelo CPF que ele carrega."""
    for e in doc.no.iter():
        if e.tag in ("cpfTrab", "cpfBenef") and (e.text or "").strip():
            achado = indice.get(e.text.strip())
            if achado:
                return achado
    return ""


_OPERACAO = ("inclusao", "alteracao", "exclusao")


def _tentar_operacao(doc, caminho):
    """Mesmo caminho, trocando inclusao <-> alteracao <-> exclusao.

    Os eventos de tabela (S-1000, S-1005, S-1010, S-1020, S-1030, S-1050)
    envolvem o bloco de dados em um destes tres, conforme a operacao daquele
    envio. A planilha declara um so -- na massa cliente piloto 11 dos 13 S-1000 sao
    'alteracao' e o caminho declarado aponta 'inclusao', o que deixava NOMEMP
    vazio. O dado e o mesmo bloco; muda so o nome do envelope.
    """
    partes = caminho.split("/")
    for i, parte in enumerate(partes):
        if parte in _OPERACAO:
            for outra in _OPERACAO:
                if outra == parte:
                    continue
                valor = doc.valor("/".join(partes[:i] + [outra] + partes[i + 1:]))
                if valor:
                    return valor
            break
    return ""


def _resolver(doc, campo, caminho, base, inst):
    """Le o valor do campo neste documento.

    18 dos 48 leiautes recebem linha de mais de um evento (o 1030, por exemplo,
    vem do S-2200 na admissao e do S-2206 a cada alteracao). A planilha declara
    UM caminho aplicado por campo, entao ao montar a linha a partir de um evento
    diferente do declarado o caminho nao serve. A cascata abaixo tenta, nesta
    ordem, e sempre diz qual estrategia usou:

      1. caminho declarado, quando o evento e o mesmo;
      2. mesmo caminho relativo dentro do outro evento -- vale para os blocos
         que o eSocial repete igual entre eventos (ideEmpregador/nrInsc);
      3. a tag que o Fonter mapeou para ESTE evento, localizada pelo nome
         dentro do no do evento; usada so como ultimo recurso e sempre
         registrada como pendencia, porque busca por nome de tag e o que
         tornava o programa legado fragil.

    Nao havendo nenhuma das tres, devolve vazio -- nunca um palpite.
    """
    # A celula pode declarar varios caminhos separados por '|'. Tenta primeiro
    # os que pertencem ao evento DESTE documento -- e assim que um leiaute
    # alimentado por dois eventos consegue preencher a mesma coluna nos dois.
    opcoes = alternativas(caminho)
    if len(opcoes) > 1:
        do_evento = [a for a in opcoes if _raiz_do_evento(a) == doc.evento]
        outras = [a for a in opcoes if a not in do_evento]
        for alt in do_evento:
            valor = (doc.valor_em(alt, base, inst)
                     if base and alt.startswith(base + "/") and inst is not None
                     else doc.valor(alt))
            if valor:
                return valor, "declarado"
        if do_evento:
            return "", "declarado"
        # nenhuma alternativa e deste evento: cai na cascata com a primeira
        caminho = outras[0] if outras else opcoes[0]

    # Aceita qualquer evento declarado no campo, nao so o primeiro da lista.
    mesmo_evento = doc.evento in (campo.get("eventos") or [campo.get("evento")])

    if mesmo_evento:
        if base and caminho.startswith(base + "/") and inst is not None:
            return doc.valor_em(caminho, base, inst), "declarado"
        valor = doc.valor(caminho)
        if not valor:
            valor = _tentar_operacao(doc, caminho)
        return valor, "declarado"

    # 2. mesmo caminho relativo, trocando so a raiz do evento
    partes = caminho.split("/")
    if len(partes) > 1:
        alternativo = doc.no.find("/".join(partes[1:]))
        if alternativo is not None and (alternativo.text or "").strip():
            return (alternativo.text or "").strip(), "caminho equivalente"

    # 3. a MESMA tag do caminho aplicado, achada em outro ponto deste evento.
    #    Vem antes da tag do Fonter de proposito: o eSocial guarda o mesmo dado
    #    sob nomes de bloco diferentes (cpfTrab fica em trabalhador/ no S-2200 e
    #    em ideVinculo/ no S-2206). Preservar a tag aplicada mantem a coluna
    #    coerente entre eventos -- trocar para a tag que o Fonter listou naquele
    #    evento encheria a mesma coluna ora com CPF, ora com matricula.
    tag_aplicada = partes[-1] if partes else ""
    if tag_aplicada:
        achados = [e for e in doc.no.iter()
                   if e.tag == tag_aplicada and (e.text or "").strip()]
        if len(achados) == 1:
            return (achados[0].text or "").strip(), "tag aplicada"

    # 4. ultimo recurso: a tag que o Fonter mapeou para ESTE evento
    tag = (campo.get("tags_evento") or {}).get(doc.evento, "").strip()
    if tag and " " not in tag and tag != tag_aplicada:
        achados = [e for e in doc.no.iter() if e.tag == tag and (e.text or "").strip()]
        if len(achados) == 1:
            return (achados[0].text or "").strip(), "tag Fonter"

    return "", None


def _aplicar_precedencia(mod, docs):
    """Descarta documentos cobertos por um evento de maior precedencia.

    A planilha declara no topo da aba, por exemplo, 'S-2300 > S-2306 por
    cpfTrab': os dois eventos falam do mesmo trabalhador sem vinculo, mas o
    S-2306 e alteracao contratual e nao carrega o bloco trabalhador/, entao
    quem tem S-2300 sai por ele. O S-2306 so entra para quem nao tem S-2300 na
    massa -- sem isso a mesma pessoa saia em duas linhas com a mesma chave, uma
    completa e outra com quatro colunas.

    A regra e de negocio e mora na planilha; aqui so se executa o que ela diz.
    Devolve (documentos filtrados, quantos foram descartados).
    """
    regras = mod.get("precedencia") or []
    if not regras:
        return docs, 0

    descartados = 0
    for regra in regras:
        vence, perde, por = regra["vence"], regra["perde"], regra["por"]
        cobertos = {v for d in docs if d.evento == vence
                    for v in [(d.no.findtext(".//" + por) or "").strip()] if v}
        if not cobertos:
            continue
        restantes = []
        for d in docs:
            if d.evento == perde and (d.no.findtext(".//" + por) or "").strip() in cobertos:
                descartados += 1
                continue
            restantes.append(d)
        docs = restantes
    return docs, descartados


def montar_modulo(codigo, parametros, documentos, tabelas, deduplicar=False):
    """Gera as linhas de UM leiaute.

    Devolve (linhas, pendencias, diagnostico).
      linhas      -> lista de listas, ja na ordem do layout
      pendencias  -> o que precisa de decisao humana
      diagnostico -> contagem para a tela
    """
    global _MAPA_RAIZ
    if not _MAPA_RAIZ:
        import xml_reader as _xr
        _MAPA_RAIZ = _xr.mapa_tag_evento(parametros)

    mod = parametros["modulos"][codigo]
    campos = mod["campos"]
    ordem = [c["campo"] for c in campos]

    # Quais eventos alimentam este leiaute: a uniao do que cada campo declara
    # na coluna Evento. Ela aceita lista ('S-2200 | S-2300 | S-2306'), pareada
    # com a lista de caminhos ao lado -- o 1012 e o primeiro caso em que o MESMO
    # campo vem de tres eventos (admissao, e os dois do trabalhador sem
    # vinculo), e nao havia onde dizer isso escolhendo um so.
    eventos = {e for c in campos for e in (c.get("eventos") or [])
               if e}
    docs = [d for d in documentos if d.evento in eventos]
    docs, por_precedencia = _aplicar_precedencia(mod, docs)

    # Leiaute que so existe para um bloco repetido (o 1031, para dependente) nao
    # deve gerar linha para o documento que nao tem esse bloco. A planilha diz
    # qual bloco e; aqui so se verifica a presenca. Uma raiz de evento diferente
    # da do documento nao se aplica -- o bloco e declarado por evento.
    fixas = mod.get("linhas_fixas") or []
    if fixas:
        # Tabela fixa do Senior: o conteudo nao sai do XML e nao passa por
        # De/Para. Sai sempre igual, independente da massa lida.
        linhas = [[formatar(v, c) for v, c in zip(l, campos)] for l in fixas]
        return linhas, [], {"documentos": 0, "linhas": len(linhas),
                            "eventos": [], "origem": "tabela fixa do Senior"}

    linha_de = mod.get("eventos_linha") or []
    if linha_de:
        docs = [d for d in docs if d.evento in linha_de]

    exigidos = mod.get("exige_bloco") or []
    sem_bloco = 0
    if exigidos:
        restantes = []
        for d in docs:
            do_evento = [b for b in exigidos if _raiz_do_evento(b) == d.evento]
            if do_evento and not any(
                    d.no.find("/".join(b.split("/")[1:])) is not None for b in do_evento):
                sem_bloco += 1
                continue
            restantes.append(d)
        docs = restantes

    # '◆ Filtro: caminho = valor' -- so gera linha o documento daquele evento
    # cujo caminho tem o valor. O 1033 e o caso: afastamento so vira recibo de
    # ferias com codMotAfast 15. Documento de outro evento nao e filtrado.
    filtrados = 0
    for caminho_f, valor_f in mod.get("filtro") or []:
        evento_f = _raiz_do_evento(caminho_f)
        restantes = []
        for d in docs:
            if d.evento == evento_f and d.valor(caminho_f) != valor_f:
                filtrados += 1
                continue
            restantes.append(d)
        docs = restantes

    juncao = indice_pagamentos(documentos)
    estabelecimentos = indice_estabelecimentos(documentos)
    empresas = indice_empresa(documentos)

    linhas = []
    pendencias = {}
    diag = {"documentos": len(docs), "linhas": 0, "eventos": sorted(eventos),
            "descartados_por_precedencia": por_precedencia,
            "descartados_sem_bloco": sem_bloco,
            "descartados_por_filtro": filtrados}

    def anotar(campo, motivo, exemplo=""):
        if not motivo:
            return
        chave = (campo["campo"], motivo)
        if chave not in pendencias:
            pendencias[chave] = {
                "layout": codigo, "campo": campo["campo"],
                "descricao": campo.get("descricao", ""),
                "acao": campo["acao"], "motivo": motivo,
                "obrigatorio": campo.get("obrigatorio", False),
                "autoria": campo.get("autoria", ""),
                "exemplo": exemplo, "ocorrencias": 0,
            }
        pendencias[chave]["ocorrencias"] += 1

    # contadores de sequencial, por chave de agrupamento
    sequenciais = {}

    for doc in docs:
        base, instancias = _no_repeticao(doc, mod, doc.evento)
        repeticoes = instancias if base else [None]

        # O bloco exigido pode estar DENTRO do no que se repete: no S-1210 o
        # infoPgto se repete e so um deles tem detPgtoFer. A instancia sem o
        # bloco nao e o registro do layout (1033: pagamento que nao e ferias).
        bloco_na_instancia = [
            "/".join(b.split("/")[len(base.split("/")):])
            for b in exigidos
            if base and _raiz_do_evento(b) == doc.evento and b.startswith(base + "/")]

        for inst in repeticoes:
            if bloco_na_instancia and inst is not None and not any(
                    inst.find(rel) is not None for rel in bloco_na_instancia):
                continue
            linha = []
            for campo in campos:
                nome = campo["campo"]
                acao = campo["acao"]

                if acao == "VAZIO":
                    linha.append("")
                    continue

                if acao == "FIXO":
                    linha.append(campo.get("arg", ""))
                    continue

                if acao in ("RELATORIO", "SEM_ORIGEM", "PENDENTE"):
                    linha.append("")
                    motivo = MOTIVO.get(acao) or campo.get("arg") or "Sem definicao."
                    anotar(campo, motivo)
                    continue

                if acao == "SEQUENCIAL":
                    natural_de = campo.get("caminho") or ""
                    if natural_de:
                        # Sequencial de CADASTRO: o numero identifica uma coisa
                        # do mundo (um cargo, um sindicato), nao a posicao da
                        # linha. Sai da tabela compartilhada, para que o
                        # historico aponte para o mesmo codigo.
                        natural = chave_natural(
                            doc, _alternativas_do_evento(campo, doc.evento,
                                                         parametros),
                            base, inst)
                        if not natural:
                            # Nenhuma alternativa e deste evento: cai na mesma
                            # cascata que as demais colunas usam para montar
                            # linha a partir de um evento vizinho.
                            natural, _ = _resolver(doc, campo, natural_de,
                                                   base, inst)
                        tabela_seq = tabela_sequencial(codigo, nome, parametros,
                                                       documentos)
                        if not natural:
                            linha.append("")
                            anotar(campo, "Sem valor de origem (%s) neste evento "
                                          "para gerar o sequencial." % natural_de)
                        else:
                            linha.append(formatar(tabela_seq.get(natural, ""), campo))
                        continue
                    # numerado depois, quando todas as linhas existirem: a
                    # sequencia e por colaborador e em ordem de data, o que
                    # so da para saber com o conjunto completo em maos
                    linha.append(None)
                    continue

                # --- daqui para baixo precisa ler o XML ---
                caminho = campo.get("caminho", "")

                # NUMEMP e o CNPJ do estabelecimento, 14 digitos. Tenta o
                # caminho declarado; nao resolvendo -- porque o evento nao tem a
                # tag (S-2230, S-2240, S-1210) ou porque ela e opcional (91% dos
                # S-2300) -- cai na juncao pelo CPF. Nunca no ideEmpregador, que
                # e a raiz de 8 digitos e nao distingue filial.
                # CODFIL e o mesmo dado (o estabelecimento): no 1041 as linhas do
                # S-1210 caiam na raiz pela cascata.
                if nome in ("NUMEMP", "CODFIL") and (acao == "DIRETO" or acao.startswith("DEPARA")):
                    bruto = ""
                    if caminho:
                        bruto, _ = _resolver(doc, campo, caminho, base, inst)
                    # 14 digitos ou nada. A cascata do _resolver procura a tag
                    # nrInsc em qualquer ponto do evento e acaba achando o
                    # ideEmpregador, que e a raiz de 8 -- valor valido e da
                    # granularidade errada, o pior tipo de erro para esta coluna.
                    raiz = bruto if len(bruto) == 8 and bruto.isdigit() else ""
                    if len(bruto) != 14:
                        bruto = _estab_do_documento(doc, estabelecimentos)
                    if len(bruto) != 14 and raiz:
                        # 1000 e a empresa e nao tem CPF para o indice acima:
                        # a matriz vem dos S-1005 da propria massa.
                        bruto = matriz_da_massa(documentos).get(raiz, "")
                        if not bruto:
                            anotar(campo, "Matriz (estabelecimento 0001) da raiz %s nao "
                                          "encontrada em nenhum S-1005 da massa. Enviada "
                                          "a raiz de 8 digitos para o De/Para." % raiz)
                            bruto = raiz
                    if not bruto:
                        linha.append("")
                        anotar(campo, "Estabelecimento nao encontrado neste evento nem "
                                      "pelo CPF em nenhum outro da massa. Coluna vazia.")
                        continue
                    if acao.startswith("DEPARA"):
                        traduzido, origem, aviso = tabelas.traduzir(codigo, nome, bruto)
                        anotar(campo, aviso, bruto)
                        linha.append(traduzido)
                    else:
                        linha.append(formatar(bruto, campo))
                    continue

                # Campo com juncao declarada ('... Leiaute 1012 por cpfTrab'):
                # le SO os caminhos deste evento, sem a cascata -- a busca por
                # nome de tag acharia o codCateg de infoMV/remunOutrEmpr no
                # S-2299, que e a categoria em OUTRO empregador. Nao havendo,
                # busca o mesmo campo no leiaute de origem pela tag de juncao.
                if campo.get("juncao") and acao == "DEPARA_TABELA":
                    bruto = ""
                    for alt in alternativas(caminho):
                        if _raiz_do_evento(alt) != doc.evento:
                            continue
                        bruto = (doc.valor_em(alt, base, inst)
                                 if base and inst is not None and alt.startswith(base + "/")
                                 else doc.valor(alt))
                        if bruto:
                            break
                    if not bruto:
                        chaves = [e for e in doc.no.iter() if e.tag == campo["juncao"]
                                  and (e.text or "").strip()]
                        chave_j = (chaves[0].text or "").strip() if len(
                            {(e.text or "").strip() for e in chaves}) == 1 else ""
                        tabela_j, conflitos = tabela_por_cpf(
                            campo["arg"], nome, campo["juncao"], parametros, documentos)
                        if not chave_j or tabela_j is None:
                            linha.append("")
                            anotar(campo, "Evento sem %s e sem %s unico para buscar no "
                                          "leiaute %s. Coluna vazia."
                                   % (nome, campo["juncao"], campo["arg"]))
                            continue
                        if chave_j in conflitos:
                            linha.append("")
                            anotar(campo, "%s com mais de um %s no leiaute %s. Coluna "
                                          "vazia." % (campo["juncao"], nome, campo["arg"]),
                                   chave_j)
                            continue
                        bruto = tabela_j.get(chave_j, "")
                        if not bruto:
                            linha.append("")
                            anotar(campo, "%s sem %s no leiaute %s. Coluna vazia."
                                   % (campo["juncao"], nome, campo["arg"]), chave_j)
                            continue
                    traduzido, origem, aviso = tabelas.traduzir(codigo, nome, bruto)
                    linha.append(formatar(traduzido, campo))
                    if aviso:
                        anotar(campo, aviso, bruto)
                    continue

                if not caminho:
                    linha.append("")
                    anotar(campo, "Sem caminho no XML definido na planilha de parametro.")
                    continue

                if "+" in caminho:
                    # Chave composta ('perApur+indApuracao'): o 1040 procura o
                    # CODCAL que o 1039 numerou pela MESMA chave. A cascata por
                    # nome de tag nao entende '+'.
                    bruto = chave_natural(doc, _alternativas_do_evento(
                        campo, doc.evento, parametros), base, inst)
                    estrategia = "declarado"
                else:
                    bruto, estrategia = _resolver(doc, campo, caminho, base, inst)
                if (not bruto and doc.evento != "S-1000"
                        and caminho.split("/")[0] == "evtInfoEmpregador"):
                    # Campo da empresa numa linha que nao e do S-1000: busca no
                    # S-1000 da mesma raiz de empregador. E o que junta a razao
                    # social a cada estabelecimento no 1001.
                    raiz = (doc.no.findtext(".//ideEmpregador/nrInsc") or "").strip()
                    dono = empresas.get(raiz)
                    if dono is not None:
                        bruto = dono.valor(caminho) or _tentar_operacao(dono, caminho)
                        if bruto:
                            estrategia = "empresa"
                if estrategia in ("tag aplicada", "tag Fonter"):
                    anotar(campo, "Campo mapeado no evento %s, montado a partir "
                                  "de um %s por %s. Caminho completo neste "
                                  "evento nao esta declarado na planilha. Conferir."
                           % (campo.get("evento"), doc.evento, estrategia), bruto)
                elif estrategia is None and campo.get("evento") != doc.evento:
                    anotar(campo, "Campo mapeado no evento %s e sem equivalente "
                                  "declarado em %s. Coluna vazia nesta linha."
                           % (campo.get("evento"), doc.evento))

                if acao == "DIRETO":
                    linha.append(formatar(bruto, campo))
                    continue

                if acao == "REGRA":
                    contexto = {"doc": doc, "inst": inst, "base": base,
                                "indice_pagamentos": juncao,
                                "documentos": documentos}
                    novo, aviso = _aplicar_regra(campo.get("arg"), bruto, campo, contexto)
                    linha.append(formatar(novo, campo))
                    anotar(campo, aviso, bruto)
                    continue

                if acao == "DEPARA_TABELA" and campo.get("arg"):
                    # 'De-Para [tabela] leiaute N': se o campo N e um sequencial
                    # de cadastro, o codigo ja existe -- e o mesmo numero que o
                    # cadastro gerou. Antes o numero do leiaute era guardado e
                    # ignorado, e o historico caia no De/Para do cliente.
                    tabela_seq = tabela_sequencial(campo["arg"], nome,
                                                   parametros, documentos)
                    if tabela_seq:
                        if bruto in tabela_seq:
                            linha.append(formatar(tabela_seq[bruto], campo))
                        else:
                            linha.append("")
                            anotar(campo, "Valor '%s' nao aparece no leiaute %s, que "
                                          "gera o %s. Sem codigo para referenciar."
                                   % (bruto, campo["arg"], nome), bruto)
                        continue

                if acao in ("DEPARA_GERAL", "DEPARA_CLIENTE", "DEPARA_TABELA"):
                    traduzido, origem, aviso = tabelas.traduzir(codigo, nome, bruto)
                    linha.append(formatar(traduzido, campo))
                    if aviso:
                        anotar(campo, aviso, bruto)
                    continue

                linha.append(formatar(bruto, campo))

            linhas.append(linha)

    # Linha identica em TODAS as colunas nao acrescenta nada e o Senior a
    # rejeita como chave repetida. Acontece nos leiautes de tabela: 592 XMLs
    # citando 119 cargos geravam 592 linhas de cargo, sendo 119 reais. Cortar
    # aqui nao perde informacao -- as linhas descartadas sao copias exatas.
    antes = len(linhas)
    linhas = _remover_linhas_identicas(linhas)
    diag["identicas_removidas"] = antes - len(linhas)

    diag.update(_diagnosticar_chave(linhas, campos))
    if deduplicar:
        antes = len(linhas)
        linhas = _deduplicar_por_chave(linhas, campos)
        diag["duplicadas_removidas"] = antes - len(linhas)

    # Depois de deduplicar: o sequencial de posicao numera o que sobrou, sem
    # buracos deixados por linhas descartadas.
    _numerar_sequenciais(linhas, campos, ordem)

    diag["linhas"] = len(linhas)
    return linhas, list(pendencias.values()), diag


def _remover_linhas_identicas(linhas):
    """Descarta copias exatas, preservando a ordem de aparicao."""
    vistas, saida = set(), []
    for linha in linhas:
        assinatura = tuple(linha)
        if assinatura in vistas:
            continue
        vistas.add(assinatura)
        saida.append(linha)
    return saida


def _indices_chave(campos):
    """Campos que formam a chave, INCLUINDO os sequenciais.

    O sequencial faz parte da chave de verdade: sem CODDEP, dois dependentes do
    mesmo colaborador pareceriam a mesma linha, e a contagem de duplicidade
    acusaria um problema que nao existe. Por isso a medicao roda depois da
    numeracao.
    """
    return [i for i, c in enumerate(campos) if c.get("chave")]


def _diagnosticar_chave(linhas, campos):
    """Conta chave repetida e chave vazia, SEM alterar as linhas.

    O Senior rejeita chave repetida, mas decidir o que fazer com ela (ficar com
    a mais recente, somar, tratar como readmissao) e regra de negocio do
    projeto, nao do extrator. Aqui so se mede e se informa; descartar linha por
    conta propria esconderia dado do cliente.
    """
    idx = _indices_chave(campos)
    if not idx or not linhas:
        return {"chaves_repetidas": 0, "linhas_sem_chave": 0}

    vistos, repetidas, sem_chave = set(), 0, 0
    for linha in linhas:
        chave = tuple(linha[i] for i in idx)
        if not any(v for v in chave):
            sem_chave += 1
            continue
        if chave in vistos:
            repetidas += 1
        vistos.add(chave)
    return {"chaves_repetidas": repetidas, "linhas_sem_chave": sem_chave,
            "campos_chave": [campos[i]["campo"] for i in idx]}


def _deduplicar_por_chave(linhas, campos):
    """Uma linha por chave: a mais recente vence, coluna a coluna.

    So roda se pedido na tela. Antes ficava a ULTIMA linha inteira, e isso
    esvaziava colunas: os eventos de tabela mandam so o que mudou, entao o
    ultimo S-1000 da cliente piloto e uma alteracao sem <contato> e sem <nmRazao> --
    o cadastro da empresa saia com nome e telefone em branco. Coluna omitida
    no evento mais novo nao significa dado apagado no cadastro, entao cada
    coluna guarda o valor mais recente que veio PREENCHIDO.

    Linha sem chave nenhuma e preservada: pode ser dado bom com o campo-chave
    ainda pendente de De/Para, e descartar seria perder informacao do cliente.
    """
    # Sequencial COM caminho entra na chave: ele ja vale como identidade (e o
    # cargo, o sindicato), diferente do sequencial de posicao, que so existe
    # depois e nao identifica nada sozinho.
    def de_posicao(c):
        return c["acao"] == "SEQUENCIAL" and not c.get("caminho")

    idx = [i for i, c in enumerate(campos)
           if c.get("chave") and not de_posicao(c)]

    # Chave que inclui um sequencial de POSICAO nao identifica a linha: o
    # numero e atribuido depois e nao sai do dado. No 1011 a chave e
    # CODCID + CODBAI, entao sobrava so a cidade e os 37 bairros da massa
    # viravam 4 linhas. Nesse caso o que identifica e o resto da linha.
    if any(c.get("chave") and de_posicao(c) for c in campos):
        idx = sorted(set(idx) | {i for i, c in enumerate(campos)
                                 if not de_posicao(c)})
    if not idx:
        return linhas

    vistos, soltas = {}, []
    for linha in linhas:
        chave = tuple(linha[i] for i in idx)
        if not any(v for v in chave):
            soltas.append(linha)
            continue
        anterior = vistos.get(chave)
        if anterior is None:
            vistos[chave] = list(linha)
        else:
            for i, valor in enumerate(linha):
                if valor:
                    anterior[i] = valor
    return list(vistos.values()) + soltas


def _alternativas_do_evento(campo, evento, parametros):
    """Alternativas declaradas no campo que pertencem a ESTE evento."""
    import xml_reader as _xr
    alts = _xr.alternativas(campo.get("caminho", ""))
    mapa = _xr.mapa_tag_evento(parametros)
    proprias = [a for a in alts
                if mapa.get(a.split("+")[0].split("/")[0]) == evento]
    return proprias or ([alts[0]] if len(alts) == 1 else [])


def chave_natural(doc, alternativas_do_evento, base, inst):
    """Primeira alternativa que trouxer valor, na ordem declarada.

    A ordem importa: o codigo do eSocial vem antes do par nome+CBO, para que o
    cargo que TEM codigo seja sempre numerado pelo codigo -- e o historico, que
    so conhece o codigo, consiga encontra-lo.
    """
    for alt in alternativas_do_evento:
        valor = _valor_de_alternativa(doc, alt, base, inst)
        if valor:
            return valor
    return ""


def _valor_de_alternativa(doc, alt, base, inst):
    """Le uma alternativa, que pode ser COMPOSTA por '+'.

    Nem todo cadastro tem codigo no eSocial: metade dos cargos do TSVE vem so
    com nmCargo e CBOCargo. Numerar pelo nome sozinho juntaria 'Prestador de
    Servico Autonomo' com CBO 234520 e com CBO 203505 num cargo so. Declarar
    'nmCargo+CBOCargo' faz a chave ser o par, e cargos que diferem no CBO
    continuam sendo cargos diferentes.
    """
    partes = []
    for pedaco in alt.split("+"):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        if base and instancia_valida(base, pedaco, inst):
            partes.append(doc.valor_em(pedaco, base, inst))
        else:
            partes.append(doc.valor(pedaco) or _tentar_operacao(doc, pedaco))
    partes = [x for x in partes if x]
    return "+".join(partes)


def instancia_valida(base, caminho, inst):
    return inst is not None and caminho.startswith(base + "/")


_CACHE_SEQ = {}


def tabela_sequencial(codigo, nome_campo, parametros, documentos):
    """{valor natural do eSocial -> numero Senior} de um SEQUENCIAL de cadastro.

    O Senior quer codigo proprio (1, 2, 3...) para cargo, sindicato e outras
    empresas, mas o historico precisa apontar para o MESMO codigo: o CODCAR do
    1015 tem de ser o CODCAR que o 1004 gerou. Ate aqui o 'De-Para [tabela]'
    guardava o numero do leiaute de origem e nao fazia nada com ele.

    A numeracao sai do valor natural que identifica o cadastro no eSocial --
    declarado na propria planilha, na coluna de caminho do campo sequencial
    (codCargo no 1004, cnpjSindCategProf no 1009, cnpjInstEnsino no 1003).
    Ordenada pelo valor, nao pela ordem dos arquivos, para que duas execucoes
    sobre a mesma massa deem sempre os mesmos numeros.
    """
    chave = (codigo, nome_campo, id(documentos))
    if chave in _CACHE_SEQ:
        return _CACHE_SEQ[chave]

    import xml_reader as _xr
    mod = (parametros.get("modulos") or {}).get(codigo)
    campos_mod = (mod or {}).get("campos", [])
    campo = next((c for c in campos_mod
                  if c["campo"] == nome_campo
                  and c["acao"] == "SEQUENCIAL" and c.get("caminho")), None)
    if campo is None:
        # O historico costuma usar OUTRO nome para o mesmo codigo: o INSENS do
        # 1055 aponta para o CODOEM do 1003. Havendo um unico sequencial de
        # cadastro no leiaute de origem, e esse.
        candidatos = [c for c in campos_mod
                      if c["acao"] == "SEQUENCIAL" and c.get("caminho")]
        campo = candidatos[0] if len(candidatos) == 1 else None
    if not campo:
        _CACHE_SEQ[chave] = {}
        return {}

    mapa_raiz = _xr.mapa_tag_evento(parametros)
    por_evento = {}
    for d in documentos:
        por_evento.setdefault(d.evento, []).append(d)

    valores = set()
    alts = _xr.alternativas(campo["caminho"])
    for evento in (campo.get("eventos") or [campo.get("evento")]):
        if not evento or evento not in por_evento:
            continue
        proprios = [a for a in alts
                    if mapa_raiz.get(a.split("+")[0].split("/")[0]) == evento]
        if not proprios:
            proprios = [alts[0]] if len(alts) == 1 else []
        for doc in por_evento[evento]:
            base, instancias = _no_repeticao(doc, mod, evento)
            for inst in (instancias if (base and instancias) else [None]):
                v = chave_natural(doc, proprios, base, inst)
                if v:
                    valores.add(v)

    tabela = {v: str(n) for n, v in enumerate(sorted(valores), start=1)}
    _CACHE_SEQ.clear()
    _CACHE_SEQ[chave] = tabela
    return tabela


_CACHE_CPF = {}


def tabela_por_cpf(codigo, nome_campo, tag_cpf, parametros, documentos):
    """{cpf -> valor cru} do campo 'nome_campo' no leiaute 'codigo'.

    E o 'De-Para [tabela] - Leiaute N por <tag>' quando o evento atual nao traz
    o dado no caminho declarado (o S-2299 e o S-2230 da amostra nao tem
    codCateg), mas o leiaute N traz, para a mesma pessoa. Monta, a partir dos
    eventos de N, o valor que cada chave de juncao tem la.

    Devolve (tabela, conflitos). CPF com mais de um valor distinto vai para
    'conflitos' e fica fora da tabela: escolher um seria palpite. (None, None)
    quando o leiaute de origem nao tem o campo ou um campo de CPF com essa tag.
    """
    chave = (codigo, nome_campo, tag_cpf, id(documentos))
    if chave in _CACHE_CPF:
        return _CACHE_CPF[chave]

    import xml_reader as _xr
    campos_mod = ((parametros.get("modulos") or {}).get(codigo) or {}).get("campos", [])
    alvo = next((c for c in campos_mod if c["campo"] == nome_campo
                 and c["acao"] != "SEQUENCIAL" and c.get("caminho")), None)
    # o CPF no leiaute de origem: o campo cujos caminhos terminam na mesma tag
    # E precisa ser OUTRO campo: no 1053, CODESC aponta para o CODESC do 1052 com o
    # proprio codigo de horario no caminho -- ai nao ha busca a fazer, o valor
    # ja e o codigo e segue o De/Para comum.
    # E sem ambiguidade: no 1012, NUMCAD e NUMCPF declaram o mesmo cpfTrab e
    # valem como um so; no 1001, NUMEMP (ideEmpregador) e NUMCGC (ideEstab)
    # terminam os dois em nrInsc com caminhos diferentes -- nao ha como saber
    # qual identifica a linha, entao nao se aplica.
    candidatos = [c for c in campos_mod if c is not alvo and c.get("caminho") and all(
        a.split("/")[-1] == tag_cpf for a in _xr.alternativas(c["caminho"]))]
    fonte_cpf = (candidatos[0] if candidatos and
                 len({c["caminho"] for c in candidatos}) == 1 else None)
    if not (alvo and fonte_cpf):
        # nao se aplica: quem chama segue o De/Para comum
        _CACHE_CPF[chave] = (None, None)
        return _CACHE_CPF[chave]

    mapa_raiz = _xr.mapa_tag_evento(parametros)

    def primeiro(doc, campo):
        for a in _xr.alternativas(campo["caminho"]):
            if mapa_raiz.get(a.split("/")[0]) == doc.evento:
                v = doc.valor(a)
                if v:
                    return v
        return ""

    vistos = {}
    eventos = set(alvo.get("eventos") or [alvo.get("evento")])
    for doc in documentos:
        if doc.evento not in eventos:
            continue
        cpf, valor = primeiro(doc, fonte_cpf), primeiro(doc, alvo)
        if cpf and valor:
            vistos.setdefault(cpf, set()).add(valor)
    tabela = {cpf: next(iter(v)) for cpf, v in vistos.items() if len(v) == 1}
    conflitos = {cpf for cpf, v in vistos.items() if len(v) > 1}
    _CACHE_CPF.clear()
    _CACHE_CPF[chave] = (tabela, conflitos)
    return _CACHE_CPF[chave]


def _numerar_sequenciais(linhas, campos, ordem):
    """Preenche os campos SEQUENCIAL depois que todas as linhas existem.

    A planilha define, por exemplo, que SEQALT (1030) numera as alteracoes de
    salario "da mais antiga para a mais recente, iniciando em 1", e que CODDEP
    (1031) numera os dependentes de cada colaborador. Nos dois casos a
    numeracao e POR COLABORADOR e atravessa varios XMLs -- por isso nao da para
    resolver enquanto se le um documento de cada vez.

    Agrupa pelos campos-chave do leiaute (menos os proprios sequenciais) e,
    havendo campo de data, ordena por ele antes de numerar.
    """
    # Sequencial COM caminho ja foi preenchido linha a linha: ele numera uma
    # coisa do mundo (um cargo, um sindicato) e nao a posicao da linha. Só os
    # sem caminho -- CODDEP, SEQALT, CODBAI -- dependem do conjunto completo.
    idx_seq = [i for i, c in enumerate(campos)
               if c["acao"] == "SEQUENCIAL" and not c.get("caminho")]
    if not idx_seq:
        return

    idx_chave = [i for i, c in enumerate(campos)
                 if c.get("chave") and c["acao"] != "SEQUENCIAL"]
    if not idx_chave:
        idx_chave = [i for i, c in enumerate(campos)
                     if c["campo"] in ("NUMEMP", "TIPCOL", "NUMCAD")]


    idx_data = next((i for i, c in enumerate(campos)
                     if c["campo"].startswith("DAT") and c["acao"] != "SEQUENCIAL"), None)

    def ordenavel(valor):
        """DD/MM/AAAA -> chave ordenavel. Sem data valida, vai para o fim."""
        if not valor:
            return (1, "")
        try:
            d, m, a = str(valor).split("/")
            return (0, "%s%s%s" % (a, m, d))
        except ValueError:
            return (1, str(valor))

    grupos = {}
    for pos, linha in enumerate(linhas):
        chave = tuple(linha[i] for i in idx_chave)
        grupos.setdefault(chave, []).append(pos)

    for posicoes in grupos.values():
        if idx_data is not None:
            posicoes = sorted(posicoes, key=lambda p: ordenavel(linhas[p][idx_data]))
        for n, pos in enumerate(posicoes, start=1):
            for i in idx_seq:
                linhas[pos][i] = str(n)


def gerar_txt(linhas, cabecalho=None):
    """Conteudo do arquivo final.

    Sem cabecalho por padrao: e o que a importacao do Senior espera, e uma
    linha a mais no topo faz o primeiro registro ser recusado.

    Com 'cabecalho', a primeira linha traz o nome dos campos. Serve para
    conferencia -- abrir no Excel e saber que coluna e qual sem contar
    posicao.
    """
    corpo = [SEPARADOR.join(_limpar(v) for v in linha) for linha in linhas]
    if cabecalho:
        corpo.insert(0, SEPARADOR.join(_limpar(v) for v in cabecalho))
    return chr(10).join(corpo)


def _limpar(valor):
    """Um ';' dentro do dado quebraria a coluna; troca por espaco."""
    if valor is None:
        return ""
    return str(valor).replace(SEPARADOR, " ").replace("\n", " ").replace("\r", "").strip()


def ordem_campos(codigo, parametros):
    return [c["campo"] for c in parametros["modulos"][codigo]["campos"]]
