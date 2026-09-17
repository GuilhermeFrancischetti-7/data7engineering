# -*- coding: utf-8 -*-
"""
Planilha de De/Para para o cliente preencher.

Modelo definido com o time, a partir de um piloto feito a mao. Duas decisoes
mudam tudo em relacao a versao anterior:

1. A PERGUNTA E AO CONTRARIO. Antes: "o codigo eSocial e 101, qual o codigo
   Senior?" -- exige que o cliente conheca o Senior, que ele ainda nao usa.
   Agora: mostra o que o Senior aceita ("1 = Empregado", "2 = Terceiro") e
   pergunta o que corresponde a isso NO SISTEMA DELE. E a unica pergunta que o
   cliente tem como responder sozinho.

2. AGRUPADO POR ASSUNTO, NAO POR LEIAUTE. Um mesmo dominio serve varios
   leiautes (TIPCOL aparece em 22). Perguntar por leiaute faz a pessoa
   responder a mesma coisa varias vezes e se perder. Cada assunto vira uma aba,
   e o Indice diz em qual aba cada campo esta.

O dominio Senior aparece INTEIRO, com descricao -- nao so os codigos achados na
massa. Sem ver as opcoes, nao da para decidir.

3. A PLANILHA NAO DEPENDE DA EXTRACAO. Ela e o artefato padrao do layout
   Senior: todo cliente recebe a mesma, com os mesmos campos e as mesmas abas,
   tenha havido extracao de XML ou nao. Quando ha XML, a extracao ADIANTA parte
   do preenchimento -- as celulas ja resolvidas chegam em verde e o cliente so
   confere. Sem XML, a mesma planilha vem em branco.

   Por isso 'achados' e opcional em toda a montagem: ele enriquece, nunca
   define o que aparece.
"""

# Linhas em branco oferecidas quando nao ha valores vindos do XML, para o
# cliente listar os codigos que usa.
LINHAS_EM_BRANCO = 12
import io
import json
import os
from collections import OrderedDict

import depara

PASTA = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------
# Agrupamento por assunto. A ordem aqui e a ordem das abas.
# Cada item e uma lista fechada do Senior (L*) ou um campo sem lista.
# ---------------------------------------------------------------------
TEMAS = [
    ("1. Pessoa", "Dados pessoais do colaborador e dependentes", [
        "LTipSex", "LEstCiv", "LRacCor", "LVisEst", "LGraPar", "LTipDepeSo",
        "LGraIns", "LCodNac", "LCodPai", "LCodDef", "LIMIRF", "LIMSAF",
    ]),
    ("2. Contrato", "Vinculo, categoria e salario", [
        "LTipCol", "LTipCon", "LCatSef", "LCateSo", "LAdmeSo", "LTipAdm",
        "LTipSal", "LTipoCAEPF", "LApoEsp", "LNivEtg", "LCodVin", "LTipIns",
    ]),
    ("3. Afastamento e Rescisao", "Motivos de afastamento e desligamento", [
        "LAviPre", "LOrgCla", "LSitAfa", "LCauDem",
    ]),
    ("4. Jornada", "Escala, horario e jornada", [
        "LTipoJornada", "LTipoIntervaloJornada", "SEQREG",
    ]),
    ("5. Folha", "Calculo e eventos de folha", [
        "LTipCal",
    ]),
    ("6. Endereco", "Localidade e logradouro", [
        "LTipLgd", "LEstFed", "CODCID", "CODBAI",
    ]),
    ("7. Sim ou Nao", "Campos de marcacao", [
        "LSimNao",
    ]),
]

# Campos que sao codigo proprio da empresa: nao ha dominio Senior a mostrar.
# Vao para uma aba separada, com a pergunta na direcao natural deles.
ABA_EMPRESA = "8. Codigos da empresa"

# A fronteira entre dominio, que o cliente mapeia a mao, e identificador, que
# sai de consulta na base dele. Acima disso o bloco vira um aviso em vez de
# linhas.
#
# Os valores distintos medidos na massa de teste mostram onde ela fica: CODEVE 78,
# CODCCU 87, depois um vao ate CADATU e FICREG com 496, CODESC e CODHOR com 847,
# NUMCAD com 1.179. O limite cai dentro desse vao.
#
# Vale para TODOS os campos: exececao por campo ja existiu aqui e foi tirada.
LIMITE_VALORES = 100

AZUL = "1F3864"
AMARELO = "FFE699"
VERDE = "C6EFCE"
CINZA = "EDF1F5"
BRANCO = "FFFFFF"
FONTE = "Arial"


def _carregar(nome):
    with open(os.path.join(PASTA, nome), encoding="utf-8") as f:
        return json.load(f)


def _amigavel(descricao, campo):
    """Titulo do bloco: a descricao do layout, sem o jargao do codigo."""
    d = (descricao or "").strip()
    return d if d else campo


def levantar(parametros, achados=None, leiautes=None):
    """Organiza o que precisa ser perguntado, por assunto.

    achados: saida de depara.levantar_valores_distintos, usada para mostrar ao
    cliente os codigos que REALMENTE aparecem no XML dele.

    O dominio do Senior e padrao e aparece SEMPRE, inteiro, para todos os
    campos -- e o mesmo em qualquer cliente e em qualquer carga. O que varia com
    os leiautes escolhidos e o PREENCHIMENTO sugerido: os codigos que o XML
    trouxe, que so existem para o leiaute que foi lido.
    """
    achados = achados or {}
    listas = _carregar("listas.json")
    # dominios que so existem do lado Senior (os 382 eventos do CODEVE)
    so_senior = parametros.get("listas_senior") or {}

    # campo -> {lista, descricao, leiautes, tipo}
    campos = OrderedDict()
    for cod in sorted(parametros["modulos"]):
        for c in parametros["modulos"][cod]["campos"]:
            if not c["acao"].startswith("DEPARA"):
                continue
            # Sem pergunta real: o historico que aponta para um sequencial nosso
            # usa o numero gerado, e campo sem caminho nao tem valor a traduzir.
            if depara.sai_de_sequencial(c, parametros) or not c.get("caminho"):
                continue
            reg = campos.setdefault(c["campo"], {
                "campo": c["campo"], "descricao": c.get("descricao", ""),
                "lista": c.get("lista") if c.get("lista") in listas else None,
                "leiautes": [], "tipo": c.get("tipo_depara", ""),
                # mascara do campo Senior: diz o formato esperado sem o cliente
                # ter que abrir o layout para descobrir
                # a aba "Mascara De-Para" tem precedencia: e ela que resolve
                # os campos cujos leiautes declaram mascaras diferentes
                "mascara": (parametros.get("mascaras_depara") or {}).get(
                    c["campo"], c.get("mascara", "")),
                # De-Para geral ja pronto na planilha de parametro, quando existe
                "sugestao": (parametros.get("deparas_dominio") or {}).get(c["campo"], []),
            })
            reg["leiautes"].append(cod)
            if not reg["lista"] and c.get("lista") in listas:
                reg["lista"] = c["lista"]
            if not reg["descricao"]:
                reg["descricao"] = c.get("descricao", "")
            if not reg.get("mascara"):
                reg["mascara"] = c.get("mascara", "")

    # valores vistos na massa, por campo
    vistos = {}
    for item in achados.values():
        vistos.setdefault(item["campo"], {}).setdefault(item["valor"], 0)
        vistos[item["campo"]][item["valor"]] += item["qtd"]
    for nome, reg in campos.items():
        reg["vistos"] = vistos.get(nome, {})

    # distribui nos temas
    usados = set()
    blocos_por_aba = OrderedDict()
    for aba, subtitulo, chaves in TEMAS:
        blocos = []
        for chave in chaves:
            if chave in listas:                      # lista fechada
                alvo = [r for r in campos.values() if r["lista"] == chave]
                if not alvo:
                    continue
                for r in alvo:
                    usados.add(r["campo"])
                blocos.append({
                    "titulo": _amigavel(alvo[0]["descricao"], alvo[0]["campo"]),
                    "campos": sorted({r["campo"] for r in alvo}),
                    "leiautes": sorted({l for r in alvo for l in r["leiautes"]}),
                    "lista": chave,
                    "opcoes": [(str(p[0]), str(p[1]) if len(p) > 1 else "")
                               for p in listas[chave]],
                    "vistos": vistos.get(alvo[0]["campo"], {}),
                    "mascara": alvo[0].get("mascara", ""),
                    "sugestao": alvo[0].get("sugestao", []),
                })
            elif chave in campos:                    # campo sem lista fechada
                r = campos[chave]
                usados.add(chave)
                opcoes_senior = [(str(i["codigo"]), i.get("descricao", ""))
                                 for i in so_senior.get(chave, [])]
                blocos.append({
                    "titulo": _amigavel(r["descricao"], r["campo"]),
                    "campos": [r["campo"]], "leiautes": sorted(set(r["leiautes"])),
                    "lista": None, "opcoes": opcoes_senior,
                    "vistos": vistos.get(chave, {}),
                    "mascara": r.get("mascara", ""),
                    "sugestao": r.get("sugestao", []),
                })
        if blocos:
            blocos_por_aba[(aba, subtitulo)] = blocos

    # CODEVE sai da aba da empresa: tem aba propria, com as colunas do S-1010
    usados.add("CODEVE")

    # o que sobrou e codigo proprio da empresa
    sobrou = [r for nome, r in campos.items() if nome not in usados]
    return blocos_por_aba, sobrou, campos


def gerar(parametros, achados=None, origem='eSocial', rubricas=None,
          leiautes=None):
    """Monta a planilha completa e devolve os bytes do .xlsx.

    A coluna do codigo legado sai SEMPRE em branco -- e o cliente quem responde.
    O que a extracao adianta e o outro lado: quando ha XML, os codigos que
    aparecem nos arquivos dele ja vem listados, para ele so dizer o equivalente
    no Senior em vez de levantar a lista sozinho.

    origem: de onde vem a migracao. Muda o texto das instrucoes.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, Protection
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.utils import get_column_letter

    achados = achados or {}
    com_xml = bool(achados)

    # Descricao das rubricas, lida do S-1010. CODEVE e TABEVE sao os unicos
    # De/Para em que o cliente enxerga so um numero -- "101" nao diz nada.
    # Com "101 - Salario Normal" ele preenche sem sair da planilha.
    #
    # A chave do indice e (tabela, codigo); os achados guardam so o codigo. Um
    # mesmo codigo em duas tabelas de rubrica pode ter descricoes diferentes;
    # nesse caso mostra as duas, separadas por " / ", em vez de escolher uma.
    # Descricao oficial do codigo eSocial, por campo. Vem das tabelas do
    # gov.br guardadas em tabelas_esocial.json; a planilha de parametro diz qual
    # tabela vale para cada campo. Enche a coluna Observacao, que antes ficava
    # vazia ao lado de um codigo como "15" que nao diz nada a quem preenche.
    descricoes = {}
    tabelas = _carregar("tabelas_esocial.json")
    for campo, numero in (parametros.get("tabelas_por_campo") or {}).items():
        itens = (tabelas.get(numero) or {}).get("itens") or []
        if not itens:
            continue
        # o XML manda o codigo com e sem zero a esquerda conforme o campo;
        # indexa das duas formas para casar em qualquer caso
        mapa = {}
        for i in itens:
            c = str(i["codigo"]).strip()
            mapa[c] = i["descricao"]
            mapa.setdefault(c.lstrip("0") or "0", i["descricao"])
            mapa.setdefault(c.zfill(2), i["descricao"])
            mapa.setdefault(c.zfill(3), i["descricao"])
        descricoes[campo] = mapa

    # O resto dos codigos nao esta em tabela numerada: esta nos "Valores
    # validos" do proprio campo no leiaute (estCiv, tpContr, undSalFixo...).
    # dominios_esocial.json guarda esses valores pelo id da pagina do gov.br
    # (2200_trabalhador_estCiv), que e o caminho da planilha sem a raiz.
    # Tabela numerada, quando existe, continua valendo primeiro.
    try:
        dominios = _carregar("dominios_esocial.json").get("campos") or {}
    except OSError:
        dominios = {}
    for mod in (parametros.get("modulos") or {}).values():
        for c in mod.get("campos") or []:
            campo = c.get("campo")
            if not campo or not c.get("caminho"):
                continue
            eventos = [e.replace("S-", "") for e in c.get("eventos") or []]
            mapa = descricoes.setdefault(campo, {})
            for caminho in c["caminho"].split("|"):
                for parte in caminho.split("+"):
                    resto = "_".join(parte.strip().split("/")[1:])
                    if not resto:
                        continue
                    ids = [k for k in dominios if k[5:] == resto]
                    ids.sort(key=lambda k: k[:4] not in eventos)
                    for k in ids[:1]:
                        valores = dominios[k]["valores"] or (
                            tabelas.get(dominios[k].get("tabela")) or {}
                        ).get("itens") or []
                        for v in valores:
                            mapa.setdefault(v["codigo"], v["descricao"])
            if not mapa:
                del descricoes[campo]

    if rubricas:
        por_codigo = {}
        for (_tab, codigo), r in rubricas.items():
            por_codigo.setdefault(codigo, []).append(r["descricao"])
        descricoes["CODEVE"] = {c: " / ".join(sorted(set(v)))
                                for c, v in por_codigo.items()}
    # Dominios que so existem do lado Senior: os 382 eventos padrao (CODEVE) e a
    # tabela de tipo de rubrica do eSocial, usada so para rotular.
    listas_senior = parametros.get("listas_senior") or {}

    blocos_por_aba, empresa, campos = levantar(parametros, achados, leiautes)

    s = Side(style="thin", color="C6CFD8")
    borda = Border(left=s, right=s, top=s, bottom=s)
    wb = openpyxl.Workbook()

    indice = []          # (campo, descricao, leiautes, aba)
    total_preencher = 0

    def faixa(ws, texto, sub, largura=4):
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=largura)
        c = ws.cell(row=1, column=1, value=texto)
        c.font = Font(name=FONTE, size=15, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[1].height = 32
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=largura)
        c2 = ws.cell(row=2, column=2 - 1, value=sub)
        c2.font = Font(name=FONTE, size=10, italic=True, color="44586B")
        c2.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[2].height = 20

    # ---------------- abas por assunto ----------------
    for (aba, subtitulo), blocos in blocos_por_aba.items():
        ws = wb.create_sheet(aba[:31])
        ws.sheet_view.showGridLines = False
        for col, larg in zip("ABCD", (18, 52, 40, 30)):
            ws.column_dimensions[col].width = larg
        # E e F guardam o campo e a direcao da pergunta; ocultas, e o que
        # permite reler o arquivo depois de preenchido
        for col in ("E", "F"):
            ws.column_dimensions[col].hidden = True
        faixa(ws, aba.split(". ", 1)[-1], subtitulo)

        linha = 4
        for b in blocos:
            for campo in b["campos"]:
                # um bloco pode juntar campos que compartilham a mesma lista
                # (BENREA, DEFFIS e FLEESO usam LSimNao). No indice cada um
                # aparece com a SUA descricao -- repetir a do primeiro fazia o
                # FLEESO, que e sobre flexibilidade de horario, ser listado como
                # "Deficiente Habilitado ou Reabilitado".
                proprio = campos.get(campo, {}).get("descricao", "")
                indice.append((campo, _amigavel(proprio, campo) if proprio
                               else b["titulo"], b["leiautes"], aba))

            # cabecalho do bloco
            ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=4)
            c = ws.cell(row=linha, column=1, value="  " + b["titulo"])
            c.font = Font(name=FONTE, size=12, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="2E5A78")
            c.alignment = Alignment(vertical="center")
            ws.row_dimensions[linha].height = 26
            linha += 1

            ctx = "campo %s%s · usado no%s layout%s %s" % (
                ", ".join(b["campos"]),
                # a mascara do layout Senior evita o cliente descobrir o formato
                # depois, quando a importacao recusar o valor
                (" · formato do código Senior %s" % b["mascara"]) if b.get("mascara") else "",
                "s" if len(b["leiautes"]) > 1 else "",
                "s" if len(b["leiautes"]) > 1 else "",
                ", ".join(b["leiautes"][:8]) + ("…" if len(b["leiautes"]) > 8 else ""))
            ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=4)
            c = ws.cell(row=linha, column=1, value="  " + ctx)
            c.font = Font(name=FONTE, size=9, italic=True, color="6B7C8C")
            linha += 1

            # A mascara vai no cabecalho da coluna que o cliente digita. Na
            # linha de contexto ela existia mas passava batido, e formato errado
            # so aparece na importacao, depois de a planilha ja ter voltado.
            titulos = [_titulo_senior(b.get("mascara")), "O que significa",
                       "Como é no seu sistema", "Observação"]
            for j, t in enumerate(titulos, start=1):
                c = ws.cell(row=linha, column=j, value=t)
                c.font = Font(name=FONTE, size=10, bold=True)
                c.fill = PatternFill("solid", fgColor=CINZA)
                c.border = borda
                c.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[linha].height = 22
            linha += 1

            # Todo bloco tem as duas metades, e nesta ordem:
            #
            #   1. o que apareceu NOS XMLS do cliente, com a descricao oficial
            #      do eSocial -- e a linha que ele responde;
            #   2. o dominio do Senior inteiro, para consulta.
            #
            # A lista do Senior e uma so e nao depende de cliente nem de carga,
            # entao aparece sempre, mesmo que nenhum codigo do eSocial tenha
            # equivalente nela. E o codigo achado no XML entra sempre, mesmo sem
            # equivalente do outro lado -- e justamente esse o caso que precisa
            # de decisao humana.
            desc = next((descricoes[c] for c in b["campos"] if c in descricoes), {})
            sugerido = {i["esocial"]: (i["senior"], i["desc_senior"])
                        for i in (b.get("sugestao") or [])}
            achou = [v for v, _ in sorted(b["vistos"].items(), key=lambda x: -x[1])]
            if origem != "eSocial":
                achou = []          # sem XML nao ha o que adiantar

            if achou:
                for valor in achou:
                    senior, desc_senior = sugerido.get(valor, ("", ""))
                    ws.cell(row=linha, column=1, value=senior or None)
                    ws.cell(row=linha, column=2, value=desc_senior or None)
                    ws.cell(row=linha, column=3, value=valor)
                    ws.cell(row=linha, column=4, value=desc.get(valor) or None)
                    for j in range(1, 5):
                        cel = ws.cell(row=linha, column=j)
                        cel.font = Font(name=FONTE, size=10)
                        cel.border = borda
                        cel.alignment = Alignment(vertical="center",
                                                  wrap_text=(j in (2, 4)))
                        cel.protection = Protection(locked=(j != 1))
                    ws.cell(row=linha, column=1).fill = PatternFill(
                        "solid", fgColor=VERDE if senior else AMARELO)
                    ws.cell(row=linha, column=5, value=",".join(b["campos"]))
                    ws.cell(row=linha, column=6, value="lista")
                    total_preencher += 0 if senior else 1
                    linha += 1
                verdes = sum(1 for v in achou if sugerido.get(v, ("",))[0])
                ws.merge_cells(start_row=linha, start_column=1,
                               end_row=linha, end_column=4)
                c = ws.cell(row=linha, column=1, value=(
                    "  %d código(s) encontrado(s) nos seus XMLs. Em verde, o que "
                    "já sabemos do padrão eSocial — confira. Em amarelo, o que "
                    "só você sabe responder." % len(achou)))
                c.font = Font(name=FONTE, size=9, italic=True, color="6B7C8C")
                linha += 2
            else:
                for _ in range(LINHAS_EM_BRANCO):
                    for j in range(1, 5):
                        cel = ws.cell(row=linha, column=j)
                        cel.font = Font(name=FONTE, size=10)
                        cel.border = borda
                        cel.protection = Protection(locked=False)
                    for j in (1, 3):
                        ws.cell(row=linha, column=j).fill = PatternFill(
                            "solid", fgColor=AMARELO)
                    ws.cell(row=linha, column=5, value=",".join(b["campos"]))
                    ws.cell(row=linha, column=6, value="lista")
                    total_preencher += 1
                    linha += 1
                linha += 1

            if b["opcoes"]:
                ws.merge_cells(start_row=linha, start_column=1,
                               end_row=linha, end_column=4)
                c = ws.cell(row=linha, column=1, value=(
                    "  Códigos do Senior — só para consulta"))
                c.font = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="6B7C8C")
                linha += 1
                for codigo, texto_op in b["opcoes"]:
                    ws.cell(row=linha, column=1, value=codigo)
                    ws.cell(row=linha, column=2, value=texto_op)
                    for j in range(1, 5):
                        cel = ws.cell(row=linha, column=j)
                        cel.font = Font(name=FONTE, size=10, color="44546A")
                        cel.border = borda
                        cel.alignment = Alignment(vertical="center",
                                                  wrap_text=(j == 2))
                        cel.protection = Protection(locked=True)
                    linha += 1

            linha += 1  # respiro entre blocos

        ws.freeze_panes = "A4"
        _liberar_filtro(ws)

    # ---------------- aba dos codigos da empresa ----------------
    if empresa:
        ws = wb.create_sheet(ABA_EMPRESA[:31])
        ws.sheet_view.showGridLines = False
        for col, larg in zip("ABCD", (22, 46, 26, 34)):
            ws.column_dimensions[col].width = larg
        for col in ("E", "F"):
            ws.column_dimensions[col].hidden = True
        faixa(ws, "Códigos da empresa",
              "Aqui não há lista do Senior: são códigos que a sua empresa define")

        linha = 4
        for r in sorted(empresa, key=lambda x: x["campo"]):
            indice.append((r["campo"], _amigavel(r["descricao"], r["campo"]),
                           sorted(set(r["leiautes"])), ABA_EMPRESA))
            ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=4)
            c = ws.cell(row=linha, column=1,
                        value="  %s   (%s%s)" % (
                            _amigavel(r["descricao"], r["campo"]), r["campo"],
                            " · formato do código Senior %s" % r["mascara"] if r.get("mascara") else ""))
            c.font = Font(name=FONTE, size=12, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="2E5A78")
            c.alignment = Alignment(vertical="center")
            ws.row_dimensions[linha].height = 26
            linha += 1

            linha = _bloco_empresa(ws, linha, r, borda,
                                   descricoes.get(r["campo"]))
        ws.freeze_panes = "A4"
        _liberar_filtro(ws)

    # ---------------- aba dos eventos da folha ----------------
    # Precisa de colunas que as demais nao tem -- tipo e incidencias do S-1010,
    # e o codigo do sistema antigo alem do codigo eSocial -- entao nao cabe no
    # formato de quatro colunas das outras abas.
    if rubricas and listas_senior.get("CODEVE"):
        reg = campos.get("CODEVE", {})
        titulo, quantos = _aba_eventos_folha(
            wb, "CODEVE", rubricas, listas_senior["CODEVE"],
            reg.get("mascara", ""), borda,
            Font, PatternFill, Alignment, Protection,
            {i["codigo"]: i.get("descricao", "") for i in listas_senior.get("TPRUBR", [])})
        total_preencher += quantos
        indice.append(("CODEVE", _amigavel(reg.get("descricao", ""), "CODEVE"),
                       sorted(set(reg.get("leiautes", []))), titulo))

    # ---------------- indice ----------------
    wi = wb.create_sheet("Índice de campos")
    wi.sheet_view.showGridLines = False
    for col, larg in zip("ABCD", (14, 44, 34, 26)):
        wi.column_dimensions[col].width = larg
    faixa(wi, "Índice de campos", "Procure o campo e veja em qual aba preenchê-lo")
    for j, t in enumerate(["Campo", "O que é", "Layouts que usam", "Preencher na aba"], start=1):
        c = wi.cell(row=4, column=j, value=t)
        c.font = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.border = borda
        c.alignment = Alignment(horizontal="center", vertical="center")
    r = 5
    for campo, titulo, leiautes, aba in sorted(indice):
        for j, v in enumerate([campo, titulo, ", ".join(leiautes), aba], start=1):
            c = wi.cell(row=r, column=j, value=v)
            c.font = Font(name=FONTE, size=10)
            c.border = borda
            c.alignment = Alignment(vertical="center", wrap_text=(j in (2, 3)))
        r += 1
    wi.freeze_panes = "A5"
    wi.auto_filter.ref = "A4:D%d" % (r - 1)

    # ---------------- comece aqui ----------------
    wc = wb.active
    wc.title = "Comece aqui"
    wc.sheet_view.showGridLines = False
    wc.column_dimensions["A"].width = 96
    texto_origem = {
        "eSocial": ("O QUE JÁ ADIANTAMOS",
                    "Lemos os XMLs do eSocial da sua empresa.",
                    "Onde foi possível, os códigos que você usa hoje já vêm listados."),
        "Layout preenchido": ("MIGRAÇÃO A PARTIR DO LAYOUT",
                              "Os dados virão do layout que a sua empresa já preencheu.",
                              "Este De/Para começa em branco."),
        "Datasul": ("MIGRAÇÃO A PARTIR DO DATASUL",
                    "Os dados virão da base Datasul da sua empresa.",
                    "Este De/Para começa em branco."),
    }.get(origem, ("", "", ""))

    passos = [
        ("PREENCHIMENTO DO DE/PARA", "titulo"),
        ("", ""),
        ("Este arquivo liga os códigos do seu sistema atual aos códigos do Senior.", "texto"),
        ("", ""),
    ] + ([
        (texto_origem[0], "sub"),
        (texto_origem[1], "texto"),
        (texto_origem[2], "texto"),
        ("", ""),
    ] if texto_origem[0] else []) + [
        ("COMO PREENCHER", "sub"),
        ("Preencha somente as células AMARELAS.", "passo"),
        ("À esquerda fica sempre o código do Senior.", "passo"),
        ("À direita, escreva o código equivalente no seu sistema.", "passo"),
        ("Vários códigos seus podem virar um só do Senior: separe por vírgula.", "passo"),
        ("Se algum item não existe na sua empresa, deixe em branco.", "passo"),
        ("", ""),
        ("ONDE ESTÁ CADA COISA", "sub"),
        ("As abas estão separadas por assunto: Pessoa, Contrato, Afastamento...", "texto"),
        ("Procurando um campo específico? Use a aba \"Índice de campos\".", "texto"),
        ("", ""),
        ("CORES", "sub"),
        ("AMARELO — é para você preencher.", "texto"),
        ("", ""),
        ("Ao terminar, salve e devolva este mesmo arquivo.", "titulo"),
    ]
    linha = 2
    for txt, tipo in passos:
        c = wc.cell(row=linha, column=1, value=txt)
        if tipo == "titulo":
            c.font = Font(name=FONTE, size=14, bold=True, color=AZUL)
        elif tipo == "sub":
            c.font = Font(name=FONTE, size=11, bold=True, color="2E5A78")
        elif tipo == "passo":
            c.font = Font(name=FONTE, size=12)
        else:
            c.font = Font(name=FONTE, size=11, color="44586B")
        wc.row_dimensions[linha].height = 24
        linha += 1
    wb.move_sheet("Comece aqui", offset=-wb.index(wb["Comece aqui"]))
    wb.active = 0

    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue(), total_preencher


def gerar_codigos_colaborador(pessoas):
    """Planilha de uma linha por pessoa, para o cliente informar o NUMCAD.

    Sai separada da planilha de De/Para de proposito: aquela e por assunto, com
    dominios de algumas dezenas de codigos, e esta tem uma linha por
    colaborador -- 1.060 na massa de teste. Misturar as duas tornaria a primeira
    impraticavel.

    O CPF e a chave: e o unico identificador que existe dos dois lados. O nome e
    a matricula do eSocial vao junto so para o cliente reconhecer a pessoa.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, Protection

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Códigos do colaborador"
    ws.sheet_view.showGridLines = False
    for col, larg in zip("ABCDEF", (22, 16, 40, 18, 16, 24)):
        ws.column_dimensions[col].width = larg

    ws.merge_cells("A1:F1")
    c = ws.cell(row=1, column=1, value="  Códigos do colaborador")
    c.font = Font(name=FONTE, size=16, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=AZUL)
    c.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 34

    ws.merge_cells("A2:F2")
    c = ws.cell(row=2, column=1, value=(
        "  Preencha só a última coluna: o código que este colaborador terá no "
        "Senior. As demais vêm dos seus XMLs e servem para você reconhecer a "
        "pessoa. Não altere a coluna do CPF — é por ela que fazemos a ligação."))
    c.font = Font(name=FONTE, size=10, italic=True, color="6B7C8C")
    c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 30

    s = Side(style="thin", color="C6CFD8")
    borda = Border(left=s, right=s, top=s, bottom=s)
    titulos = ["CNPJ do estabelecimento", "CPF", "Nome",
               "Matrícula no eSocial", "Data de admissão",
               "Código no Senior"]
    for j, t in enumerate(titulos, start=1):
        c = ws.cell(row=4, column=j, value=t)
        c.font = Font(name=FONTE, size=10, bold=True)
        c.fill = PatternFill("solid", fgColor=CINZA)
        c.border = borda
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
    ws.row_dimensions[4].height = 28

    linha = 5
    for p in pessoas.values():
        for j, v in ((1, p.get("cnpj", "")), (2, p["cpf"]),
                     (3, p.get("nome", "")), (4, p.get("matricula", "")),
                     (5, p.get("admissao", ""))):
            cel = ws.cell(row=linha, column=j, value=v)
            cel.font = Font(name=FONTE, size=10)
            cel.border = borda
            cel.protection = Protection(locked=True)
        cel = ws.cell(row=linha, column=6)
        cel.border = borda
        cel.fill = PatternFill("solid", fgColor=AMARELO)
        cel.protection = Protection(locked=False)
        linha += 1

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = "A4:F%d" % (linha - 1)

    dados = io.BytesIO()
    wb.save(dados)
    return dados.getvalue(), len(pessoas)


def _aba_eventos_folha(wb, campo, rubricas, opcoes_senior, mascara, borda,
                       Font, PatternFill, Alignment, Protection, tprubr):
    """Aba propria para o De/Para dos eventos da folha (CODEVE).

    Duas partes, na ordem em que o cliente responde:

      1. as rubricas que apareceram no S-1010 dele, ja com descricao, tipo e
         incidencias -- ele so diz o codigo Senior e o codigo do sistema antigo;
      2. abaixo, a tabela de eventos do Senior inteira, para consulta e para os
         eventos que nunca foram ao eSocial, que ele acrescenta nas linhas em
         branco.

    Os tres codigos convivem porque sao coisas diferentes: no legado a hora
    normal pode ser 1, no eSocial foi a rubrica 100, e no Senior e o evento 200.
    A coluna que o extrator LE e a do eSocial, que e o que vem no XML; a do
    legado existe para o cliente se reconhecer.
    """
    # logo depois da aba de folha, que e onde o assunto esta
    titulo = "5.1 Eventos da folha"
    pos = (wb.sheetnames.index("5. Folha") + 1
           if "5. Folha" in wb.sheetnames else None)
    ws = wb.create_sheet(titulo[:31], pos)
    ws.sheet_view.showGridLines = False
    larguras = [(1, 16), (2, 34), (3, 14), (4, 40), (7, 20), (8, 16),
                (9, 10), (10, 10), (11, 10)]
    for col, larg in larguras:
        ws.column_dimensions[chr(64 + col)].width = larg
    for col in ("E", "F"):
        ws.column_dimensions[col].hidden = True

    def faixa(texto, sub):
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=11)
        c = ws.cell(row=1, column=1, value="  " + texto)
        c.font = Font(name=FONTE, size=16, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(vertical="center")
        ws.row_dimensions[1].height = 34
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=11)
        c = ws.cell(row=2, column=2 - 1, value="  " + sub)
        c.font = Font(name=FONTE, size=10, italic=True, color="6B7C8C")

    faixa("Eventos da folha",
          "Diga a que evento do Senior corresponde cada rubrica sua")

    def cabecalho(linha, titulos):
        for j, t in titulos:
            c = ws.cell(row=linha, column=j, value=t)
            c.font = Font(name=FONTE, size=10, bold=True)
            c.fill = PatternFill("solid", fgColor=CINZA)
            c.border = borda
            c.alignment = Alignment(horizontal="center", vertical="center",
                                    wrap_text=True)
        ws.row_dimensions[linha].height = 30

    linha = 4
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=11)
    c = ws.cell(row=linha, column=1, value="  As rubricas que aparecem nos seus XMLs")
    c.font = Font(name=FONTE, size=12, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="2E5A78")
    ws.row_dimensions[linha].height = 26
    linha += 1
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=11)
    c = ws.cell(row=linha, column=1, value=(
        "  Preencha as duas colunas amarelas. O tipo e as incidencias vem do "
        "seu S-1010 e servem para voce reconhecer a rubrica."))
    c.font = Font(name=FONTE, size=9, italic=True, color="6B7C8C")
    linha += 1

    titulos = [(1, _titulo_senior(mascara)), (2, "O que significa"),
               (3, "Código no eSocial"), (4, "Descrição no eSocial"),
               (7, "Código no seu sistema"), (8, "Tipo"),
               (9, "INSS"), (10, "IRRF"), (11, "FGTS")]
    cabecalho(linha, titulos)
    linha += 1

    total = 0
    for (_tab, codigo), r in sorted(rubricas.items(), key=lambda x: _ordem(x[0][1])):
        ws.cell(row=linha, column=3, value=codigo)
        ws.cell(row=linha, column=4, value=r["descricao"])
        ws.cell(row=linha, column=8, value=tprubr.get(r["tipo"], r["tipo"]))
        ws.cell(row=linha, column=9, value=r["inss"])
        ws.cell(row=linha, column=10, value=r["irrf"])
        ws.cell(row=linha, column=11, value=r["fgts"])
        for j in [1, 2, 3, 4, 7, 8, 9, 10, 11]:
            cel = ws.cell(row=linha, column=j)
            cel.font = Font(name=FONTE, size=10)
            cel.border = borda
            cel.alignment = Alignment(vertical="center", wrap_text=(j == 4))
            cel.protection = Protection(locked=(j not in (1, 7)))
        for j in (1, 7):
            ws.cell(row=linha, column=j).fill = PatternFill("solid", fgColor=AMARELO)
        ws.cell(row=linha, column=5, value=campo)
        ws.cell(row=linha, column=6, value="livre")
        total += 1
        linha += 1

    # espaco para o que nunca foi ao eSocial
    for _ in range(LINHAS_EM_BRANCO):
        for j in [1, 2, 3, 4, 7, 8, 9, 10, 11]:
            cel = ws.cell(row=linha, column=j)
            cel.font = Font(name=FONTE, size=10)
            cel.border = borda
        for j in (1, 3, 7):
            ws.cell(row=linha, column=j).fill = PatternFill("solid", fgColor=AMARELO)
        ws.cell(row=linha, column=5, value=campo)
        ws.cell(row=linha, column=6, value="livre")
        total += 1
        linha += 1
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=11)
    c = ws.cell(row=linha, column=1, value=(
        "  Evento que a sua folha usa mas nunca foi ao eSocial entra nas linhas "
        "em branco acima. Precisa de linha? Insira quantas quiser."))
    c.font = Font(name=FONTE, size=9, italic=True, color="6B7C8C")
    linha += 3

    # ---- consulta: a tabela de eventos do Senior ----
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=11)
    c = ws.cell(row=linha, column=1,
                value="  Eventos do Senior — só para consulta")
    c.font = Font(name=FONTE, size=12, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="6B7C8C")
    ws.row_dimensions[linha].height = 26
    linha += 1
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=11)
    c = ws.cell(row=linha, column=1, value=(
        "  Nao preencha aqui. Use esta lista para achar o codigo que voce "
        "escreve na coluna amarela acima."))
    c.font = Font(name=FONTE, size=9, italic=True, color="6B7C8C")
    linha += 1
    cabecalho(linha, [(1, "Código no Senior"), (2, "Descrição"),
                      (3, "Detalhe"), (4, "Tipo")])
    linha += 1
    for it in opcoes_senior:
        for j, v in ((1, it["codigo"]), (2, it.get("descricao", "")),
                     (3, it.get("detalhe", "")), (4, it.get("tipo", ""))):
            cel = ws.cell(row=linha, column=j, value=v)
            cel.font = Font(name=FONTE, size=10)
            cel.border = borda
            cel.alignment = Alignment(vertical="center", wrap_text=(j in (2, 3)))
        linha += 1

    ws.freeze_panes = "A7"
    _liberar_filtro(ws)
    return titulo, total


def _ordem(codigo):
    """Ordena codigo de rubrica como numero quando da, senao como texto."""
    try:
        return (0, int(codigo), "")
    except ValueError:
        return (1, 0, codigo)


def _titulo_senior(mascara):
    """Cabecalho da coluna do codigo Senior, com o formato quando houver."""
    # "formato do código Senior" por extenso: so '(Z[6])' ao lado de uma coluna
    # de CNPJ fazia parecer que o formato era o do valor do eSocial.
    return ("Código no Senior (formato do código Senior: %s)" % mascara
            if mascara else "Código no Senior")


def _bloco_empresa(ws, linha, reg, borda, descricao=None):
    """Mesmo formato dos campos sem dominio: o cliente lista o que usa."""
    from openpyxl.styles import Font, PatternFill, Alignment, Protection
    achou = sorted(reg.get("vistos", {}).items(), key=lambda x: -x[1])
    return _tabela_livre(ws, linha + 1, reg["campo"], achou,
                         len(achou) > LIMITE_VALORES, borda,
                         Font, PatternFill, Alignment, Protection, descricao,
                         reg.get("mascara", ""))


def _tabela_livre(ws, linha, campo, achou, muitos, borda,
                  Font, PatternFill, Alignment, Protection, descricao=None,
                  mascara=""):
    """Bloco de campo sem dominio fechado no Senior.

    Mesma ordem de colunas dos blocos com dominio: codigo Senior na esquerda,
    codigo do legado na direita. Aqui os dois lados sao do cliente -- nao ha
    dominio Senior publicado para consultar --, mas manter a posicao evita que
    ele troque as pontas ao passar de um bloco para outro.

    Havendo extracao, a coluna do legado ja vem com os codigos que aparecem no
    XML: e esse o adiantamento.
    """
    titulos = [_titulo_senior(mascara), "O que significa",
               "Como é no seu sistema", "Observação"]
    for j, t in enumerate(titulos, start=1):
        c = ws.cell(row=linha - 1, column=j, value=t)
        c.font = Font(name=FONTE, size=10, bold=True)
        c.fill = PatternFill("solid", fgColor=CINZA)
        c.border = borda
        c.alignment = Alignment(horizontal="center", vertical="center")

    if muitos:
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=4)
        c = ws.cell(row=linha, column=1, value=(
            "  Aparecem %d valores diferentes no seu XML — um por registro. "
            "A correspondência sai de consulta na sua base, não de digitação."
            % len(achou)))
        c.font = Font(name=FONTE, size=10, italic=True, color="6B7C8C")
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[linha].height = 30
        return linha + 2

    legados = [v for v, _ in achou]
    legados += [None] * max(0, LINHAS_EM_BRANCO - len(legados))

    descricao = descricao or {}
    for legado in legados:
        ws.cell(row=linha, column=3, value=legado)
        if legado is not None and descricao.get(legado):
            ws.cell(row=linha, column=4, value=descricao[legado])
        for j in range(1, 5):
            cel = ws.cell(row=linha, column=j)
            cel.font = Font(name=FONTE, size=10)
            cel.border = borda
            # o codigo Senior e sempre preenchido pelo cliente; o legado so
            # quando nao veio do XML dele
            cel.protection = Protection(locked=not (j in (1, 2, 4) or
                                                    (j == 3 and legado is None)))
        ws.cell(row=linha, column=1).fill = PatternFill("solid", fgColor=AMARELO)
        if legado is None:
            ws.cell(row=linha, column=3).fill = PatternFill("solid", fgColor=AMARELO)
        ws.cell(row=linha, column=5, value=campo)
        ws.cell(row=linha, column=6, value="livre")
        linha += 1
    return linha + 1


# ---------------------------------------------------------------------
# Leitura do arquivo devolvido pelo cliente
# ---------------------------------------------------------------------
def ler_preenchido(dados_xlsx):
    """Le a planilha devolvida e devolve {campo: {codigo_legado: codigo_senior}}.

    A planilha tem uma unica convencao: **codigo Senior na esquerda, codigo do
    legado na direita**. A traducao usada na extracao vai do legado para o
    Senior, entao a leitura inverte a linha -- sempre do mesmo jeito, em
    qualquer aba.

    O cliente pode listar varios codigos legados separados por virgula, quando
    mais de um vira o mesmo codigo Senior.
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(dados_xlsx), read_only=True, data_only=True)

    tabela = {}
    linhas_lidas = 0
    for ws in wb.worksheets:
        for linha in ws.iter_rows(min_col=1, max_col=6, values_only=True):
            if len(linha) < 6:
                continue
            campo, modo = linha[4], linha[5]
            if not campo or modo not in ("lista", "livre"):
                continue
            senior = str(linha[0]).strip() if linha[0] is not None else ""
            legado = str(linha[2]).strip() if linha[2] is not None else ""
            if not (senior and legado):
                continue

            # A celula oculta pode trazer mais de um campo, separados por
            # virgula: um bloco so atende BENREA, DEFFIS e FLEESO, que usam a
            # mesma lista. A resposta vale para todos -- gravar so o primeiro
            # deixava os outros dois sem traducao, saindo com o valor cru.
            for nome in str(campo).split(","):
                nome = nome.strip()
                if not nome:
                    continue
                alvo = tabela.setdefault(nome, {})
                for codigo in legado.replace(";", ",").split(","):
                    codigo = codigo.strip()
                    if codigo:
                        alvo[codigo] = senior
            linhas_lidas += 1

    wb.close()
    return tabela, linhas_lidas


def _liberar_filtro(ws):
    """Cria o filtro da linha acima do congelamento ate o fim, se nao houver.

    As abas saem sem protecao: protegidas, o Excel bloqueava filtro e
    classificacao.
    """
    from openpyxl.utils import get_column_letter
    if not ws.auto_filter.ref and ws.max_row > 1:
        topo = max(1, (ws.freeze_panes and int("".join(ch for ch in ws.freeze_panes if ch.isdigit())) or 2) - 1)
        ws.auto_filter.ref = "A%d:%s%d" % (topo, get_column_letter(ws.max_column),
                                          ws.max_row)
