# -*- coding: utf-8 -*-
r"""Gera os 48 layouts direto pelo writer e confere as invariantes.

Uso:  py testes/validar_layouts.py [pasta_com_xmls] [codigo ...]
Ex.:  py testes/validar_layouts.py
      py testes/validar_layouts.py "C:\...\Amostra_Demo" 1004 1015

Invariantes (o que foi exigido nas reunioes e nao pode regredir):
  - nenhum layout lanca excecao
  - nenhum layout tem duas linhas exatamente iguais
Sem pasta, usa exemplos/massa_demo (gerada por gerar_massa_demo.py). Mudou o numero? Explique o porque antes de seguir.
"""
import collections, io, json, os, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(P); sys.path.insert(0, P)

import depara, writer, xml_reader

args = sys.argv[1:]
pasta = (args.pop(0) if args and not args[0].isdigit() else
         os.environ.get("EXTRATOR_MASSA",
                        os.path.join(P, "exemplos", "massa_demo")))
PAR = json.load(open("parametros.json", encoding="utf-8"))
alvo = args or sorted(PAR["modulos"])

docs, _, _, _ = xml_reader.carregar_documentos(parametros=PAR, pasta=pasta,
                                               recursivo=True)
print("massa:", pasta, "| documentos:", len(docs))
tab = depara.Tabelas(PAR)
total = erros = dup = 0
for cod in alvo:
    try:
        linhas, pend, diag = writer.montar_modulo(cod, PAR, docs, tab,
                                                  deduplicar=True)
    except Exception as e:
        erros += 1
        print("%s ERRO %s: %s" % (cod, type(e).__name__, e))
        continue
    total += len(linhas)
    repetidas = sum(1 for v in collections.Counter(map(tuple, linhas)).values()
                    if v > 1)
    dup += bool(repetidas)
    print("%s %-30s %5d linhas %4d pendencias%s" % (
        cod, PAR["modulos"][cod]["nome"][:30], len(linhas), len(pend),
        "  << %d LINHAS IDENTICAS" % repetidas if repetidas else ""))
    if len(alvo) <= 3:
        campos = [c["campo"] for c in PAR["modulos"][cod]["campos"]]
        print("   " + ";".join(campos))
        for l in linhas[:30]:
            print("   " + ";".join(l))
print("\n%d layouts | %d linhas | %d erros | %d com linha duplicada"
      % (len(alvo), total, erros, dup))
sys.exit(1 if (erros or dup) else 0)
