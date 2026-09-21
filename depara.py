# -*- coding: utf-8 -*-
"""
Gestao das tabelas De/Para.

Tres origens, com regras diferentes:

  De-Para [geral]   -> dominio eSocial -> lista Senior. Vale para qualquer
                       cliente. Tres ja vem prontos na planilha de parametro
                       (TIPCOL, ADMESO, NIVETG); o resto ainda nao foi levantado
                       e por isso entra como PENDENTE, nunca chutado.
  De-Para [cliente] -> depende da codificacao do cliente (codigo de empresa,
                       matricula...). So o cliente pode preencher.
  De-Para [tabela]  -> o codigo vem de outro leiaute da mesma carga; depende da
                       ordem de importacao.

Principio do projeto: este modulo NAO inventa correspondencia. Se nao ha
tabela carregada para um campo, o valor cru do eSocial e mantido na coluna e a
linha vira pendencia com o motivo. Preencher no chute quebraria a importacao de
um jeito silencioso, que e pior do que quebrar de forma visivel.
"""
import io
import json
import os
import re
from collections import OrderedDict

# Separador entre codigo e descricao na lista suspensa ('1 — Colaborador').
SEPARADOR_OPCAO = "—"

CABECALHO_MODELO = ["Leiaute", "Campo Senior", "Descricao do Campo",
                    "Codigo eSocial (encontrado no XML)", "Descricao eSocial",
                    "Ocorrencias na massa", "Codigo Senior (PREENCHER)",
                    "Status", "Como preencher", "Tipo De/Para"]

ACOES_DEPARA = ("DEPARA_GERAL", "DEPARA_CLIENTE", "DEPARA_TABELA")


class Tabelas:
    """Guarda as tabelas De/Para em memoria durante a sessao."""

    def __init__(self, parametros):
        self.parametros = parametros
        # dominio pronto de fabrica: {'TIPCOL': {'101': '1', ...}}
        self.dominio = {}
        self.descricoes = {}
        for alvo, itens in parametros.get("deparas_dominio", {}).items():
            self.dominio[alvo] = {i["esocial"]: i["senior"] for i in itens if i["senior"]}
            self.descricoes[alvo] = {i["esocial"]: i["desc_esocial"] for i in itens}
        # preenchido pelo cliente: {(leiaute, campo): {codigo_esocial: codigo_senior}}
        self.cliente = {}
        # o mesmo, para as linhas que valem para qualquer leiaute
        self.cliente_todos = {}

    # ---- consulta ----------------------------------------------------
    def traduzir(self, modulo, campo, valor):
        """Devolve (valor_traduzido, origem, pendencia_ou_None)."""
        if valor == "":
            return "", None, None

        chave = (modulo, campo)
        if chave in self.cliente and valor in self.cliente[chave]:
            return self.cliente[chave][valor], "tabela do cliente", None

        # o modelo pergunta uma vez so por campo, valendo para todos os
        # leiautes que usam aquele campo (leiaute gravado como '*')
        if campo in self.cliente_todos and valor in self.cliente_todos[campo]:
            return self.cliente_todos[campo][valor], "tabela do cliente", None

        if campo in self.dominio and valor in self.dominio[campo]:
            return self.dominio[campo][valor], "De-Para geral (planilha)", None

        if campo in self.dominio:
            return valor, None, ("Codigo '%s' nao consta no De-Para geral de %s. "
                                 "Valor cru mantido." % (valor, campo))

        return valor, None, ("Sem tabela De/Para carregada para %s. Valor cru "
                             "mantido." % campo)

    def tem_tabela(self, modulo, campo):
        return ((modulo, campo) in self.cliente
                or campo in self.cliente_todos
                or campo in self.dominio)

    def carregar_codigos_colaborador(self, dados_xlsx):
        """Carrega o arquivo de codigos do colaborador -> NUMCAD por CPF.

        Entra como tabela do cliente valendo para todos os leiautes: o NUMCAD e
        o mesmo colaborador em qualquer um deles.
        """
        import depara as _self
        tabela, problemas = _self.carregar_codigos_colaborador(dados_xlsx)
        if tabela:
            self.cliente_todos.setdefault("NUMCAD", {}).update(tabela)
        return len(tabela), problemas

    def carregar_modelo(self, dados_xlsx):
        """Le a planilha nova (modelo por assunto) devolvida pelo cliente."""
        import modelo_depara
        tabela, linhas = modelo_depara.ler_preenchido(dados_xlsx)
        for campo, pares in tabela.items():
            self.cliente_todos.setdefault(campo, {}).update(pares)
        avisos = []
        if not linhas:
            avisos.append("Nenhuma celula preenchida. Os campos continuam com o "
                          "valor cru do eSocial.")
        return sum(len(v) for v in tabela.values()), avisos

    # ---- carga de tabela preenchida pelo cliente ---------------------
    def carregar_planilha(self, dados_xlsx):
        """Le a planilha modelo devolvida preenchida. Devolve (qtd, avisos)."""
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(dados_xlsx), read_only=True, data_only=True)

        chaves = ["Leiaute", "Campo Senior", "Codigo eSocial (encontrado no XML)"]
        # nome atual da coluna de preenchimento e o da versao anterior
        nomes_destino = ["Codigo no Senior", "Codigo Senior (PREENCHER)"]

        # A aba de trabalho nao e necessariamente a primeira (a de instrucoes vem
        # antes), e o cabecalho nao fica na linha 1 (ha a faixa de aviso e o
        # contador acima). Procura a aba e a linha que tem as colunas esperadas.
        linhas = cab = None
        inicio = 0
        for aba in wb.worksheets:
            candidato = [list(r) for r in aba.iter_rows(values_only=True)]
            for i, linha_cab in enumerate(candidato[:12]):
                atual = [str(x).strip() if x is not None else "" for x in linha_cab]
                if all(c in atual for c in chaves) and any(n in atual for n in nomes_destino):
                    linhas, cab, inicio = candidato, atual, i + 1
                    break
            if cab:
                break

        if cab is None:
            wb.close()
            return 0, ["Nao encontrei as colunas esperadas em nenhuma aba. "
                       "Use o modelo baixado pelo proprio app."]

        destino = next(n for n in nomes_destino if n in cab)
        iL, iC, iE, iS = (cab.index(chaves[0]), cab.index(chaves[1]),
                          cab.index(chaves[2]), cab.index(destino))
        qtd, avisos = 0, []
        for r in linhas[inicio:]:
            if not r or iL >= len(r) or r[iL] is None:
                continue
            mod = str(r[iL]).strip()
            mod = mod if mod == "*" else mod[:4]
            campo = str(r[iC]).strip() if iC < len(r) and r[iC] else ""
            cod_e = str(r[iE]).strip() if iE < len(r) and r[iE] else ""
            # a lista suspensa devolve '1 — Colaborador'; guardamos so o codigo.
            # Aceita tambem quem digitou o codigo puro, sem escolher da lista.
            cod_s = codigo_da_opcao(r[iS]) if iS < len(r) else ""
            if not (mod and campo and cod_e):
                continue
            if cod_s == "":
                continue  # nao preenchido -- segue pendente, de proposito
            if mod == "*":
                self.cliente_todos.setdefault(campo, {})[cod_e] = cod_s
            else:
                self.cliente.setdefault((mod, campo), {})[cod_e] = cod_s
            qtd += 1
        wb.close()
        if qtd == 0:
            avisos.append("Nenhuma linha com 'Codigo Senior' preenchido. "
                          "Os campos continuam com o valor cru do eSocial.")
        return qtd, avisos


def levantar_colaboradores(documentos):
    """CPF -> o que a massa sabe da pessoa, para o De/Para de matricula.

    O NUMCAD e o codigo do colaborador no Senior, e o XML nao tem como saber:
    e o cliente quem responde. Mas sao milhares de pessoas -- na massa de teste, 1.060 --,
    e isso nao cabe na planilha de De/Para por assunto, que e feita para dominio
    de algumas dezenas de codigos.

    Por isso vai num arquivo proprio: uma linha por pessoa, ja com CPF, nome e
    matricula do eSocial, e a coluna do codigo Senior em branco. O cliente
    devolve, e a extracao passa a gravar o codigo dele no lugar do CPF.

    Nome e matricula saem de qualquer evento que os traga -- o S-2200 tem os
    dois, o S-1200 nao tem nenhum -- e por isso a cobertura varia com a massa.
    """
    pessoas = OrderedDict()
    for d in documentos:
        cpf = next(((e.text or "").strip() for e in d.no.iter()
                    if e.tag in ("cpfTrab", "cpfBenef") and e.text), "")
        if not cpf:
            continue
        p = pessoas.setdefault(cpf.zfill(11), {"cpf": cpf.zfill(11)})
        for e in d.no.iter():
            if e.tag == "nmTrab" and e.text and not p.get("nome"):
                p["nome"] = e.text.strip()
            elif e.tag == "matricula" and e.text and not p.get("matricula"):
                p["matricula"] = e.text.strip()
            # Admissao: dtAdm (celetista) ou dtExercicio (estatutario) no S-2200;
            # no S-2300 o inicio do TSV. dtInicio existe em outros eventos com
            # outro sentido, por isso so vale no S-2300.
            elif (not p.get("admissao") and e.text and (
                    (d.evento == "S-2200" and e.tag in ("dtAdm", "dtExercicio"))
                    or (d.evento == "S-2300" and e.tag == "dtInicio"))):
                v = e.text.strip()
                p["admissao"] = ("%s/%s/%s" % (v[8:10], v[5:7], v[:4])
                                 if len(v) == 10 else v)
            elif e.tag in ("localTrabGeral", "ideEstabLot") and not p.get("cnpj"):
                v = (e.findtext("nrInsc") or "").strip()
                if len(v) == 14:
                    p["cnpj"] = v
    return pessoas


def carregar_codigos_colaborador(dados_xlsx):
    """Le o arquivo de codigos devolvido pelo cliente -> {chave: codigo Senior}.

    Localiza as colunas pelo cabecalho, nao pela posicao: o cliente pode
    reordenar, e um arquivo que ele mesmo montou raramente vem na ordem exata.
    Devolve tambem o que NAO foi possivel usar, para a tela mostrar em vez de
    ignorar em silencio.

    A chave e o CPF **e** a matricula do eSocial, quando o arquivo traz as duas
    colunas: o NUMCAD nem sempre sai do cpfTrab. No 1018, 1020, 1028, 1036 e
    1037 o caminho e 'ideVinculo/matricula', e com tabela so por CPF esses
    cinco leiautes saiam com a matricula crua ('MC000618425') num campo
    numerico de 9 digitos. E a mesma pessoa e o mesmo codigo, so muda por onde
    o evento a identifica.
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(dados_xlsx), read_only=True,
                                data_only=True)
    tabela = {}
    problemas = []
    for ws in wb.worksheets:
        linhas = [list(r) for r in ws.iter_rows(values_only=True)]
        # Cabecalho e a linha com um ROTULO curto de CPF. Exigir que seja curto
        # evita casar com o texto de instrucao do topo, que tambem diz "CPF" e
        # "Senior" -- foi o que aconteceu no primeiro teste.
        hi = None
        for i, r in enumerate(linhas):
            rotulos = [str(x or "").strip().lower() for x in r]
            if any("cpf" in x and len(x) <= 30 for x in rotulos):
                hi = i
                break
        if hi is None:
            continue
        cab = [str(x or "").strip().lower() for x in linhas[hi]]
        curto = [x if len(x) <= 30 else "" for x in cab]
        c_cpf = next(j for j, x in enumerate(curto) if "cpf" in x)
        c_cod = next((j for j, x in enumerate(curto)
                      if "senior" in x or "numcad" in x
                      or "codigo do colaborador" in x
                      or "código do colaborador" in x), None)
        if c_cod is None:
            problemas.append("Aba '%s': achei a coluna do CPF, mas nenhuma "
                             "coluna de codigo do colaborador." % ws.title)
            continue
        c_mat = next((j for j, x in enumerate(curto) if "matr" in x), None)
        for r in linhas[hi + 1:]:
            if not r or c_cpf >= len(r) or r[c_cpf] is None:
                continue
            cpf = str(r[c_cpf]).strip().split(".")[0]
            cpf = "".join(ch for ch in cpf if ch.isdigit()).zfill(11)
            codigo = str(r[c_cod]).strip() if c_cod < len(r) and r[c_cod] is not None else ""
            if not codigo:
                continue
            if len(cpf) == 11:
                tabela[cpf] = codigo
            if c_mat is not None and c_mat < len(r) and r[c_mat] is not None:
                matricula = str(r[c_mat]).strip().split(".")[0]
                # Matricula em branco e comum (quem nunca teve evento com ela).
                # Nao sobrepoe uma chave ja lida: a primeira linha vale, como no CPF.
                if matricula and matricula not in tabela:
                    tabela[matricula] = codigo
    wb.close()
    return tabela, problemas


def indice_rubricas(documentos):
    """(ideTabRubr, codRubr) -> cadastro da rubrica, a partir dos S-1010.

    Nao preenche coluna de leiaute nenhuma: existe para o De/Para do 1040, em
    que o cliente diz a que evento Senior corresponde cada rubrica dele.

    Le do S-1010 e nao do S-1200 de proposito. O S-1200 so tem codigo e
    descricao; sem saber se a rubrica e provento ou desconto, e se incide INSS,
    IRRF e FGTS, o cliente nao consegue parear com seguranca -- duas "horas
    normais" com incidencias diferentes viram eventos Senior diferentes.

    O S-1010 vem em tres operacoes -- inclusao, alteracao e exclusao. Vale o
    cadastro mais recente por iniValid. A exclusao nao traz dadosRubrica e por
    isso nao apaga o que ja foi lido: o codigo continua aparecendo na folha
    antiga, e o cliente ainda precisa mapea-lo.
    """
    indice = {}
    for d in documentos:
        if d.evento != "S-1010":
            continue
        for operacao in d.no.iter():
            if operacao.tag not in ("inclusao", "alteracao"):
                continue
            ide = next((e for e in operacao if e.tag == "ideRubrica"), None)
            dados = next((e for e in operacao if e.tag == "dadosRubrica"), None)
            if ide is None or dados is None:
                continue

            def ler(no, nome):
                return next(((e.text or "").strip() for e in no if e.tag == nome), "")

            chave = (ler(ide, "ideTabRubr"), ler(ide, "codRubr"))
            descricao = ler(dados, "dscRubr")
            if not chave[1] or not descricao:
                continue
            validade = ler(ide, "iniValid")
            anterior = indice.get(chave)
            if anterior is None or validade >= anterior["validade"]:
                indice[chave] = {
                    "descricao": descricao,
                    "natureza": ler(dados, "natRubr"),
                    "tipo": ler(dados, "tpRubr"),
                    "inss": ler(dados, "codIncCP"),
                    "irrf": ler(dados, "codIncIRRF"),
                    "fgts": ler(dados, "codIncFGTS"),
                    "sindical": ler(dados, "codIncSIND"),
                    "validade": validade,
                }
    return indice


def sai_de_sequencial(campo, parametros):
    """O campo e 'De-Para [tabela]' para um sequencial de cadastro do extrator.

    Nesse caso o writer usa o numero que o proprio cadastro gerou (CODCAR do
    1004, CODSIN do 1009, CODBAI do 1011, CODOEM do 1003) e nunca consulta o
    De/Para do cliente. Perguntar ao cliente seria pedir uma resposta que e
    ignorada. A escolha do sequencial e a mesma de writer.tabela_sequencial.
    """
    if campo.get("acao") != "DEPARA_TABELA" or not campo.get("arg"):
        return False
    origem = (parametros.get("modulos") or {}).get(campo["arg"]) or {}
    seq = [c for c in origem.get("campos", [])
           if c["acao"] == "SEQUENCIAL" and c.get("caminho")]
    # Campo com juncao ('... por cpfTrab') NAO sai: o caminho dele e o proprio
    # dado (codCateg) e entra na lista do cliente como qualquer outro.
    return any(c["campo"] == campo["campo"] for c in seq) or len(seq) == 1


def levantar_valores_distintos(documentos, parametros, modulos_alvo):
    """Varre a massa e junta os valores CRUS que cada campo De/Para trouxe.

    E isso que permite entregar ao cliente um De/Para ja com o lado do eSocial
    preenchido -- ele so completa a coluna do codigo Senior, em vez de levantar
    a lista sozinho.

    Le os caminhos ALTERNATIVOS, separados por '|', escolhendo o que pertence ao
    evento do documento -- do mesmo jeito que o writer monta a linha. Sem isso,
    todo campo que ganhou alternativa nas versoes 11 a 13 parava de ser coletado
    em silencio: ESTCIV, TIPSEX, GRAINS, RACCOR e CODNAC vinham vazios, e o
    TIPCOL vinha com CPF, porque a busca caia na tag errada.
    """
    import xml_reader

    mapa_raiz = xml_reader.mapa_tag_evento(parametros)
    achados = OrderedDict()
    por_evento = {}
    for d in documentos:
        por_evento.setdefault(d.evento, []).append(d)

    def caminhos_do_evento(campo, evento):
        """Alternativas declaradas que pertencem a ESTE evento, na ordem."""
        alts = xml_reader.alternativas(campo.get("caminho", ""))
        proprias = [a for a in alts
                    if mapa_raiz.get(a.split("/")[0]) == evento]
        # caminho unico sem raiz reconhecivel continua valendo, como antes
        return proprias or ([alts[0]] if len(alts) == 1 else [])

    for cod in modulos_alvo:
        mod = parametros["modulos"].get(cod)
        if not mod:
            continue
        for campo in mod["campos"]:
            if campo["acao"] not in ACOES_DEPARA or sai_de_sequencial(campo, parametros):
                continue
            for evento in (campo.get("eventos") or [campo.get("evento")]):
                if not evento or evento not in por_evento:
                    continue
                caminhos = caminhos_do_evento(campo, evento)
                if not caminhos:
                    continue
                for doc in por_evento[evento]:
                    base, instancias = _no_repeticao(doc, mod, evento)
                    for caminho in caminhos:
                        if base and instancias and caminho.startswith(base):
                            for inst in instancias:
                                _somar(achados, cod, campo,
                                       doc.valor_em(caminho, base, inst), documentos,
                                       nome_depara(campo, caminho))
                        else:
                            _somar(achados, cod, campo, doc.valor(caminho), documentos,
                                   nome_depara(campo, caminho))
    return achados


def nome_depara(campo, caminho=""):
    """Nome da tabela De/Para deste campo.

    Em regra e o proprio campo Senior: uma pergunta por campo, valendo para
    todos os leiautes. Com 'De-Para [geral] - por caminho' e a TAG lida.

    O eSocial renomeou tags na virada para o S-1.3 e os dominios antigo e novo
    usam os MESMOS numeros com significados diferentes -- no VISEST,
    classTrabEstrang 2 e "Visto temporario" e condIng 2 e "Solicitante de
    refugio". Com uma tabela so, as duas respostas viravam uma e o codigo do
    XML antigo era traduzido pela resposta dada ao novo. A aba do cliente passa
    a ser 'De-Para <tag>'.
    """
    if not campo.get("por_caminho") or not caminho:
        return campo["campo"]
    tag = caminho.split("|")[0].split("+")[0].strip().split("/")[-1]
    return tag or campo["campo"]


def _somar(achados, cod, campo, valor, documentos=None, nome=None):
    if valor == "":
        return
    nome = nome or campo["campo"]
    if campo["campo"] == "NUMEMP" and len(valor) == 8 and valor.isdigit() and documentos:
        # Mesma conversao do writer: a raiz de 8 (1000, 1001, 1002 leem o
        # ideEmpregador) vira a matriz de 14 achada nos S-1005. Sem isso o
        # cliente recebia a raiz para mapear, valor que a exportacao nunca usa.
        import writer
        valor = writer.matriz_da_massa(documentos).get(valor, valor)
    chave = (cod, nome, valor)
    if chave not in achados:
        achados[chave] = {
            "layout": cod, "campo": nome,
            "descricao": campo.get("descricao", ""),
            "tipo": campo.get("tipo_depara", ""),
            "valor": valor, "qtd": 0,
        }
    achados[chave]["qtd"] += 1


def _no_repeticao(doc, mod, evento):
    """Descobre qual no se repete para este leiaute neste documento.

    Estrategia: entre os ancestrais dos caminhos do leiaute, o mais profundo
    que aparece mais de uma vez no XML e o registro que se repete. Se nenhum
    repete, o leiaute gera uma linha so.

    O resultado depende do documento e do leiaute, nao do campo -- mas o
    levantamento do De/Para chama uma vez por CAMPO, e cada chamada varre a
    arvore inteira contando candidatos. Numa massa media isso dava 63 mil
    varreduras e 16 dos 31 segundos da leitura. Guardar no proprio documento
    resolve, e o cache morre junto com ele.
    """
    chave_cache = (mod["codigo"], evento)
    if not hasattr(doc, "_cache_repeticao"):
        doc._cache_repeticao = {}
    if chave_cache in doc._cache_repeticao:
        return doc._cache_repeticao[chave_cache]

    resultado = _calcular_no_repeticao(doc, mod, evento)
    doc._cache_repeticao[chave_cache] = resultado
    return resultado


def _calcular_no_repeticao(doc, mod, evento):
    caminhos = [c["caminho"] for c in mod["campos"]
                if c.get("caminho") and c.get("evento") == evento]
    if not caminhos:
        return None, []

    candidatos = set()
    for c in caminhos:
        partes = c.split("/")
        for i in range(2, len(partes)):
            candidatos.add("/".join(partes[:i]))

    melhor = None
    for cand in sorted(candidatos, key=lambda x: x.count("/"), reverse=True):
        if doc.contar(cand) > 1:
            melhor = cand
            break
    if not melhor:
        return None, []
    return melhor, doc.instancias(melhor)


LIMITE_DOMINIO = 60


def separar_por_cardinalidade(achados, limite=LIMITE_DOMINIO):
    """Divide o que o cliente preenche na mao do que vem da base dele.

    Sao duas coisas diferentes com o mesmo rotulo 'De/Para' na planilha:

      dominio        TIPCOL, ESTCIV, GRAINS... poucas dezenas de codigos fixos.
                     Da para uma pessoa sentar e preencher.
      identificador  NUMCAD, CODESC... um valor por colaborador ou por escala.
                     Numa massa media da milhares de linhas; ninguem preenche
                     isso a mao, sai de consulta na base do cliente.

    Jogar os dois na mesma aba entrega uma planilha de 15 mil linhas que o
    cliente devolve em branco. O corte e pela quantidade de valores distintos.
    """
    por_campo = {}
    for chave, item in achados.items():
        por_campo.setdefault((item["layout"], item["campo"]), []).append(item)

    dominio, identificadores = {}, {}
    for chave, itens in por_campo.items():
        alvo = dominio if len(itens) <= limite else identificadores
        for item in itens:
            alvo[(item["layout"], item["campo"], item["valor"])] = item
    return dominio, identificadores


def _carregar_listas_senior():
    """Dominios do Senior, do listas.json do Validador de Layout.

    E daqui que sai a lista suspensa da planilha: em vez de o cliente digitar um
    codigo de cabeca, ele escolhe entre os valores que o Senior aceita naquele
    campo. Erro de digitacao no De/Para so aparece na hora da importacao, quando
    ja custa caro -- a lista suspensa mata a classe inteira desse erro.
    """
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "listas.json")
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _rotulo_opcao(codigo, descricao):
    """'1' + 'Colaborador' -> '1 — Colaborador'. Vazio vira ''."""
    codigo = (codigo or "").strip()
    descricao = (descricao or "").strip()
    if not codigo:
        return ""
    return "%s %s %s" % (codigo, SEPARADOR_OPCAO, descricao) if descricao else codigo


def codigo_da_opcao(valor, listas_validas=None):
    """Inverso de _rotulo_opcao, tolerante ao que o cliente realmente digitar.

    Aceita '1', '1 — Colaborador', '1 - Colaborador' e ate '1—Colaborador'.
    Se nada casar, devolve o texto limpo: e melhor levar o valor como veio e
    deixar a validacao pegar do que descartar em silencio o que a pessoa quis.
    """
    if valor is None:
        return ""
    texto = str(valor).strip()
    if not texto:
        return ""
    for sep in (SEPARADOR_OPCAO, " - ", "-", ":"):
        if sep in texto:
            candidato = texto.split(sep)[0].strip()
            if candidato:
                if listas_validas is None or candidato in listas_validas:
                    return candidato
                return candidato
    return texto


def _carregar_menus_senior():
    """leiaute -> caminho de menu no Senior, do schema.json do Validador.

    Serve para a instrucao dizer ONDE conferir o codigo, em vez de mandar o
    cliente procurar. Para os campos sem dominio fechado -- que sao a maioria --
    e a unica ajuda concreta que da para oferecer sem inventar tabela.
    """
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.json")
    try:
        with open(caminho, encoding="utf-8") as f:
            esquema = json.load(f)
    except (OSError, ValueError):
        return {}
    return {cod: (dados.get("menu") or "").strip()
            for cod, dados in esquema.items() if dados.get("menu")}


def _instrucao(campo, tipo, tem_lista, leiaute="", menus=None):
    """Texto da coluna 'Como preencher', especifico da linha."""
    menus = menus or {}

    def onde(cod):
        m = menus.get(cod)
        return (" Consulte em: %s." % m) if m else ""

    if tem_lista:
        return ("Escolha na lista suspensa da celula ao lado. Sao exatamente os "
                "valores que o Senior aceita neste campo.")

    t = (tipo or "").lower()

    if "tabela" in t:
        m = re.search(r"leiaute\s*(\d+)", tipo or "", re.I)
        if m:
            return ("Use o codigo que voce definiu no leiaute %s desta mesma "
                    "carga. Aquele leiaute precisa ser importado antes deste.%s"
                    % (m.group(1), onde(m.group(1))))
        return "Use o codigo gerado em outro leiaute desta mesma carga."

    if "cliente" in t:
        return ("Codificacao da SUA empresa: informe o codigo que este item tem "
                "na sua base. Nao existe lista fechada.%s" % onde(leiaute))

    if "geral" in t:
        return ("Codigo do eSocial (coluna ao lado) para o codigo equivalente do "
                "Senior. O layout v2.1 nao declara lista fechada para este campo, "
                "entao confira o cadastro correspondente.%s" % onde(leiaute))

    return ("Informe o codigo Senior correspondente ao valor do eSocial.%s"
            % onde(leiaute))


def _consolidar_por_campo(dominio, lista_do_campo):
    """Junta o mesmo campo+valor que aparece em varios leiautes numa linha so.

    'Cidade 3550308' e Sao Paulo no 1003, no 1011 e no 1013 -- o codigo Senior e
    o mesmo nos tres. Repetir a pergunta tres vezes so cansa quem preenche e
    abre espaco para responder diferente em cada uma. Na massa de teste isso
    tira 31% das linhas.
    """
    juntos = {}
    for item in dominio.values():
        chave = (item["campo"], item["valor"])
        if chave not in juntos:
            juntos[chave] = {
                "campo": item["campo"],
                "descricao": item["descricao"],
                "tipo": item["tipo"],
                "valor": item["valor"],
                "qtd": 0,
                "leiautes": set(),
                "lista": lista_do_campo.get((item["layout"], item["campo"])),
            }
        alvo = juntos[chave]
        alvo["qtd"] += item["qtd"]
        alvo["leiautes"].add(item["layout"])
        if not alvo["lista"]:
            alvo["lista"] = lista_do_campo.get((item["layout"], item["campo"]))
        if not alvo["descricao"]:
            alvo["descricao"] = item["descricao"]
    return juntos


def _ajuda_curta(tipo, tem_lista):
    """Uma linha, no maximo cinco palavras. Sem seta, sem jargao."""
    if tem_lista:
        return ""
    t = (tipo or "").lower()
    if "tabela" in t:
        m = re.search(r"leiaute\s*(\d+)", tipo or "", re.I)
        return ("Mesmo codigo do leiaute %s" % m.group(1)) if m else "Vem de outro leiaute"
    if "cliente" in t:
        return "Codigo do seu sistema"
    return "Ver cadastro no Senior"


def gerar_modelo_xlsx(achados, tabelas, limite=LIMITE_DOMINIO, parametros=None):
    """Planilha para o cliente preencher.

    Feita para quem nao usa Excel: uma aba de trabalho, tres colunas visiveis e
    uma unica instrucao no topo. Tudo que o programa precisa para reler o
    arquivo (leiaute, nome do campo, codigo do eSocial) vai em colunas ocultas,
    fora do caminho de quem preenche.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, Protection
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.utils import get_column_letter

    dominio, identificadores = separar_por_cardinalidade(achados, limite)
    listas_senior = _carregar_listas_senior()

    lista_do_campo = {}
    if parametros:
        for mod in parametros["modulos"].values():
            for c in mod["campos"]:
                if c.get("lista"):
                    lista_do_campo[(mod["codigo"], c["campo"])] = c["lista"]

    itens = _consolidar_por_campo(dominio, lista_do_campo)

    AZUL, AMARELO, VERDE, CINZA, BRANCO = "1F3864", "FFE699", "C6EFCE", "F2F2F2", "FFFFFF"
    FONTE = "Arial"
    s = Side(style="thin", color="BFBFBF")
    borda = Border(left=s, right=s, top=s, bottom=s)

    wb = openpyxl.Workbook()

    # ---------------------------------------------------------------
    # Aba oculta com os dominios, que alimenta as listas suspensas
    # ---------------------------------------------------------------
    wo = wb.create_sheet("Opcoes")
    usadas = sorted({it["lista"] for it in itens.values()
                     if it["lista"] in listas_senior})
    faixa = {}
    for j, nome in enumerate(usadas, start=1):
        col = get_column_letter(j)
        wo.cell(row=1, column=j, value=nome)
        valores = listas_senior.get(nome, [])
        for i, par in enumerate(valores, start=2):
            codigo = par[0] if isinstance(par, (list, tuple)) else str(par)
            desc = par[1] if isinstance(par, (list, tuple)) and len(par) > 1 else ""
            wo.cell(row=i, column=j, value=_rotulo_opcao(codigo, desc))
        if valores:
            faixa[nome] = "Opcoes!$%s$2:$%s$%d" % (col, col, len(valores) + 1)
    wo.sheet_state = "hidden"

    # ---------------------------------------------------------------
    # Aba de trabalho
    # ---------------------------------------------------------------
    ws = wb.active
    ws.title = "Preencher aqui"

    LINHA_CAB = 3
    PRIMEIRA = LINHA_CAB + 1
    total = len(itens)
    ultima = PRIMEIRA + total - 1

    # faixa de aviso no topo
    ws.merge_cells("A1:E1")
    a = ws["A1"]
    a.value = "Preencha somente a coluna AMARELA."
    a.font = Font(name=FONTE, size=16, bold=True, color="FFFFFF")
    a.fill = PatternFill("solid", fgColor=AZUL)
    a.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34

    ws.merge_cells("A2:E2")
    b = ws["A2"]
    b.value = ('="Faltam "&COUNTBLANK(C%d:C%d)&" de %d"' % (PRIMEIRA, ultima, total)) \
        if total else "Nada a preencher"
    b.font = Font(name=FONTE, size=12, bold=True)
    b.fill = PatternFill("solid", fgColor=CINZA)
    b.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 24

    titulos = ["Campo", "O que veio do eSocial", "Codigo no Senior",
               "Ajuda", "Registros"]
    larguras = [34, 48, 30, 26, 11]
    for i, (h, w) in enumerate(zip(titulos, larguras), start=1):
        c = ws.cell(row=LINHA_CAB, column=i, value=h)
        c.font = Font(name=FONTE, size=11, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = borda
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[LINHA_CAB].height = 26

    # colunas ocultas: e por elas que o programa reencontra cada linha
    ocultas = ["Leiaute", "Campo Senior", "Codigo eSocial (encontrado no XML)"]
    for i, h in enumerate(ocultas, start=6):
        col = get_column_letter(i)
        ws.cell(row=LINHA_CAB, column=i, value=h)
        ws.column_dimensions[col].hidden = True

    validacoes = {}
    linha = PRIMEIRA
    campo_anterior = None
    faixa_clara = True

    ordenado = sorted(itens.values(), key=lambda x: (x["descricao"] or x["campo"],
                                                     x["campo"], x["valor"]))
    for it in ordenado:
        if it["campo"] != campo_anterior:
            faixa_clara = not faixa_clara
            campo_anterior = it["campo"]
        fundo = BRANCO if faixa_clara else CINZA

        tem_lista = it["lista"] in faixa
        sugerido, desc_e = "", ""
        if it["campo"] in tabelas.dominio:
            sugerido = tabelas.dominio[it["campo"]].get(it["valor"], "")
            desc_e = tabelas.descricoes.get(it["campo"], {}).get(it["valor"], "")

        preenchido = ""
        if sugerido:
            desc_s = ""
            for par in listas_senior.get(it["lista"] or "", []):
                if (par[0] if isinstance(par, (list, tuple)) else str(par)) == sugerido:
                    desc_s = par[1] if isinstance(par, (list, tuple)) and len(par) > 1 else ""
                    break
            preenchido = _rotulo_opcao(sugerido, desc_s)

        visiveis = [it["descricao"] or it["campo"],
                    _rotulo_opcao(it["valor"], desc_e),
                    preenchido,
                    _ajuda_curta(it["tipo"], tem_lista),
                    it["qtd"]]
        for i, v in enumerate(visiveis, start=1):
            c = ws.cell(row=linha, column=i, value=v)
            c.font = Font(name=FONTE, size=11)
            c.border = borda
            c.alignment = Alignment(vertical="center",
                                    horizontal="center" if i == 5 else "left",
                                    wrap_text=(i in (1, 2)))
            c.fill = PatternFill("solid", fgColor=fundo)
            c.protection = Protection(locked=(i != 3))

        alvo = ws.cell(row=linha, column=3)
        alvo.font = Font(name=FONTE, size=11, bold=True)
        alvo.fill = PatternFill("solid", fgColor=VERDE if preenchido else AMARELO)

        # o que o programa le na volta
        ws.cell(row=linha, column=6, value="*")
        ws.cell(row=linha, column=7, value=it["campo"])
        ws.cell(row=linha, column=8, value=it["valor"])

        ws.row_dimensions[linha].height = 22
        if tem_lista:
            validacoes.setdefault(it["lista"], []).append(linha)
        linha += 1

    for nome_lista, alvos in validacoes.items():
        dv = DataValidation(type="list", formula1="=" + faixa[nome_lista],
                            allow_blank=True, showDropDown=False)
        dv.errorTitle = "Opcao invalida"
        dv.error = "Clique na seta da celula e escolha uma das opcoes."
        dv.promptTitle = "Escolha na lista"
        dv.prompt = "Clique na seta ao lado da celula."
        ws.add_data_validation(dv)
        for l in alvos:
            dv.add(ws.cell(row=l, column=3))

    if total:
        # amarelo enquanto vazio, verde assim que preenche -- sem coluna de status
        ws.conditional_formatting.add(
            "C%d:C%d" % (PRIMEIRA, ultima),
            FormulaRule(formula=["LEN(TRIM($C%d))=0" % PRIMEIRA],
                        fill=PatternFill("solid", fgColor=AMARELO), stopIfTrue=True))
        ws.conditional_formatting.add(
            "C%d:C%d" % (PRIMEIRA, ultima),
            FormulaRule(formula=["LEN(TRIM($C%d))>0" % PRIMEIRA],
                        fill=PatternFill("solid", fgColor=VERDE), stopIfTrue=True))

    ws.freeze_panes = "A%d" % PRIMEIRA
    ws.sheet_view.showGridLines = False
    _liberar_filtro(ws)

    # ---------------------------------------------------------------
    # Instrucoes: curtas
    # ---------------------------------------------------------------
    wi = wb.create_sheet("Instrucoes")
    wi.column_dimensions["A"].width = 76
    wi.sheet_view.showGridLines = False
    passos = [
        ("COMO PREENCHER", "titulo"),
        ("", ""),
        ("1.  Abra a aba  \"Preencher aqui\".", "passo"),
        ("2.  Preencha so a coluna AMARELA.", "passo"),
        ("3.  Se a celula tiver uma seta, clique e escolha da lista.", "passo"),
        ("4.  Se nao tiver seta, digite o codigo.", "passo"),
        ("", ""),
        ("AMARELO = falta preencher", "nota"),
        ("VERDE   = ja esta preenchido", "nota"),
        ("", ""),
        ("No topo da aba aparece quanto ainda falta.", "nota"),
        ("", ""),
        ("Salve e devolva o arquivo. Nao mexa em mais nada.", "titulo"),
    ]
    for i, (txt, tipo) in enumerate(passos, start=2):
        c = wi.cell(row=i, column=1, value=txt)
        if tipo == "titulo":
            c.font = Font(name=FONTE, size=14, bold=True, color=AZUL)
        elif tipo == "passo":
            c.font = Font(name=FONTE, size=13)
        else:
            c.font = Font(name=FONTE, size=12, italic=True)
        wi.row_dimensions[i].height = 26

    # ---------------------------------------------------------------
    # Campos que nao se preenche a mao
    # ---------------------------------------------------------------
    if identificadores:
        wid = wb.create_sheet("Nao preencher")
        wid.sheet_view.showGridLines = False
        wid.merge_cells("A1:C1")
        t = wid["A1"]
        t.value = "Esta aba e so informativa. Nao precisa preencher nada aqui."
        t.font = Font(name=FONTE, size=13, bold=True, color="FFFFFF")
        t.fill = PatternFill("solid", fgColor=AZUL)
        t.alignment = Alignment(horizontal="center", vertical="center")
        wid.row_dimensions[1].height = 30

        for i, (h, w) in enumerate(zip(["Campo", "Quantos valores diferentes",
                                        "Por que nao entra na lista"],
                                       [34, 24, 56]), start=1):
            c = wid.cell(row=2, column=i, value=h)
            c.font = Font(name=FONTE, size=11, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=AZUL)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            wid.column_dimensions[get_column_letter(i)].width = w
        wid.row_dimensions[2].height = 30

        agrupado = {}
        for item in identificadores.values():
            agrupado.setdefault((item["campo"], item["descricao"]), 0)
            agrupado[(item["campo"], item["descricao"])] += 1

        ri = 3
        for (campo, desc), qtd in sorted(agrupado.items()):
            vals = [desc or campo, qtd,
                    "Tem um valor por pessoa ou por registro. Sai da base do "
                    "sistema, nao se digita."]
            for i, v in enumerate(vals, start=1):
                c = wid.cell(row=ri, column=i, value=v)
                c.font = Font(name=FONTE, size=11)
                c.border = borda
                c.alignment = Alignment(vertical="center", wrap_text=(i == 3),
                                        horizontal="center" if i == 2 else "left")
            ri += 1
        wid.freeze_panes = "A3"

    wb.move_sheet("Instrucoes", offset=-wb.index(wb["Instrucoes"]))
    wb.active = wb.index(wb["Instrucoes"])

    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def _liberar_filtro(ws):
    """Cria o filtro da linha acima do congelamento ate o fim, se nao houver.

    As abas saem sem protecao: protegidas, o Excel bloqueava filtro e
    classificacao.
    """
    from openpyxl.utils import get_column_letter
    if not ws.auto_filter.ref and ws.max_row > 1:
        topo = max(1, (ws.freeze_panes and int(re.sub(r"\D", "", ws.freeze_panes)) or 2) - 1)
        ws.auto_filter.ref = "A%d:%s%d" % (topo, get_column_letter(ws.max_column),
                                          ws.max_row)
