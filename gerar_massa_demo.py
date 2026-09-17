# -*- coding: utf-8 -*-
"""Gera uma massa de XMLs do eSocial 100% fictícia, para demo e testes.

Uso:  python gerar_massa_demo.py [pasta_destino] [--colaboradores N] [--semente S]
Padrao: exemplos/massa_demo, 25 colaboradores, semente 42.

Nenhum dado real: CPFs e CNPJs sao gerados com digito verificador valido, mas a
partir de numeros aleatorios; nomes saem de listas genericas.

Os eventos sao montados a partir dos proprios caminhos declarados em
parametros.json -- o mesmo principio do extrator: quando a planilha passa a
mapear uma tag nova, a massa de demo passa a conte-la sem mudar este arquivo.
"""
import argparse
import json
import os
import random
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import xml_reader

AQUI = os.path.dirname(os.path.abspath(__file__))

NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fabio", "Gabriela", "Heitor",
         "Isabela", "Joao", "Karina", "Lucas", "Mariana", "Nicolas", "Olivia",
         "Paulo", "Renata", "Samuel", "Tatiana", "Vitor"]
SOBRENOMES = ["Almeida", "Barbosa", "Cardoso", "Dias", "Ferreira", "Gomes",
              "Lima", "Martins", "Nunes", "Oliveira", "Pereira", "Rocha",
              "Santos", "Souza", "Teixeira"]
CARGOS = [("ANL01", "Analista Administrativo", "252105"),
          ("AUX01", "Auxiliar de Escritorio", "411005"),
          ("TEC01", "Tecnico de Informatica", "317110"),
          ("GER01", "Gerente Comercial", "142305")]
RUBRICAS = [("1000", "Salario Base"), ("1010", "Horas Extras 50%"),
            ("1020", "Adicional Noturno"), ("5000", "INSS"), ("5010", "IRRF"),
            ("6000", "Ferias")]
LOTACOES = ["ADM", "OPER", "COML"]

# Nos que se repetem dentro de um evento, com quantas instancias gerar.
REPETIDOS = {"dependente": 2, "itensRemun": 3, "detRubrFer": 2}

# Tags que o extrator le mas nao aparecem na planilha (eventos auxiliares).
CAMINHOS_EXTRA = [
    "evtTabRubrica/infoRubrica/inclusao/ideRubrica/codRubr",
    "evtTabRubrica/infoRubrica/inclusao/ideRubrica/ideTabRubr",
    "evtTabRubrica/infoRubrica/inclusao/ideRubrica/iniValid",
    "evtTabRubrica/infoRubrica/inclusao/dadosRubrica/dscRubr",
    "evtTabEstab/infoEstab/inclusao/ideEstab/tpInsc",
    "evtTabEstab/infoEstab/inclusao/ideEstab/nrInsc",
    "evtDeslig/infoDeslig/dtDeslig",
    "evtDeslig/infoDeslig/dtProjFimAPI",
    "evtAfastTemp/infoAfastamento/fimAfastamento/dtTermAfast",
    "evtRemun/ideTrabalhador/cpfTrab",
]


def _dv(base, pesos):
    s = sum(int(d) * p for d, p in zip(base, pesos)) % 11
    return "0" if s < 2 else str(11 - s)


def cpf(rng):
    b = "".join(str(rng.randint(0, 9)) for _ in range(9))
    b += _dv(b, range(10, 1, -1))
    return b + _dv(b, range(11, 1, -1))


def cnpj(raiz, filial):
    b = raiz + "%04d" % filial
    b += _dv(b, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return b + _dv(b, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])


def caminhos_por_raiz(parametros):
    """tag raiz do evento -> lista de caminhos (sem a raiz)."""
    todos = set(CAMINHOS_EXTRA)
    for mod in parametros["modulos"].values():
        for campo in mod["campos"]:
            for alt in xml_reader.alternativas(campo.get("caminho", "")):
                todos.update(p.strip() for p in alt.split("+"))
        for bloco in mod.get("exige_bloco") or []:
            todos.add(bloco)
    por_raiz = {}
    for c in todos:
        partes = c.split("/")
        if partes[0].startswith("evt") and len(partes) > 1:
            por_raiz.setdefault(partes[0], []).append(partes[1:])
    # Caminho que e prefixo de outro aponta para um bloco, nao para uma folha:
    # gerar texto nele produziria '<dependente>907<cpfDep>...'.
    for raiz, lista in por_raiz.items():
        por_raiz[raiz] = [c for c in lista
                          if not any(len(o) > len(c) and o[:len(c)] == c for o in lista)]
    return por_raiz


class Gerador:
    def __init__(self, parametros, rng):
        self.rng = rng
        self.mapa = xml_reader.mapa_tag_evento(parametros)
        self.caminhos = caminhos_por_raiz(parametros)
        self.raiz_cnpj = "%08d" % rng.randint(10000000, 99999999)
        self.filiais = [cnpj(self.raiz_cnpj, 1), cnpj(self.raiz_cnpj, 2)]
        self.seq = 0

    # ---- valores -------------------------------------------------------
    def data(self, inicio=2015, fim=2024):
        d = date(inicio, 1, 1) + timedelta(days=self.rng.randint(0, 365 * (fim - inicio)))
        return d.isoformat()

    def valor(self, tag, trilha, ctx, i):
        r = self.rng
        pais = set(trilha)
        if tag in ("cpfTrab", "cpfBenef"):
            return ctx["cpf"]
        if tag == "cpfDep":
            return ctx["deps"][i % len(ctx["deps"])]["cpf"]
        if tag == "nmDep":
            return ctx["deps"][i % len(ctx["deps"])]["nome"]
        if tag in ("cpfSupervisor",):
            return cpf(r)
        if tag == "nrInsc":
            if "ideEmpregador" in pais:
                return self.raiz_cnpj
            return ctx.get("estab", self.filiais[0])
        if tag.startswith("cnpj"):
            return cnpj("%08d" % r.randint(10000000, 99999999), 1)
        if tag == "tpInsc":
            return "1"
        if tag == "matricula":
            return ctx.get("matricula", "")
        if tag == "nmTrab":
            return ctx.get("nome", "")
        if tag in ("nmRazao",):
            return "EMPRESA DEMONSTRACAO LTDA"
        if tag in ("codCargo",):
            return ctx["cargo"][0]
        if tag in ("nmCargo",):
            return ctx["cargo"][1]
        if tag in ("codCBO", "CBOCargo"):
            return ctx["cargo"][2]
        if tag == "codLotacao":
            return ctx.get("lotacao", LOTACOES[0])
        if tag == "codRubr":
            return ctx.get("rubrica", RUBRICAS[i % len(RUBRICAS)])[0]
        if tag == "dscRubr":
            return ctx.get("rubrica", RUBRICAS[0])[1]
        if tag == "ideTabRubr":
            return "TAB01"
        if tag == "codCateg":
            return ctx.get("categ", "101")
        if tag in ("iniValid", "perApur"):
            return "2024-%02d" % r.randint(1, 12)
        if tag == "dtNascto":
            return self.data(1965, 2003)
        if tag == "dtAdm":
            return ctx.get("dtAdm", self.data())
        if tag.startswith("dt"):
            return self.data(2020, 2025)
        if tag.startswith("vr") or tag == "vlrBolsa":
            return "%.2f" % r.uniform(150, 9000)
        if tag in ("qtdRubr", "fatorRubr", "qtDias", "qtdDiasAfast"):
            return str(r.randint(1, 30))
        if tag == "sexo":
            return r.choice("MF")
        if tag in ("racaCor", "estCiv", "tpAdmissao", "indAdmissao", "tpContr",
                   "undSalFixo", "opcFGTS", "indApuracao", "incTrab"):
            return "1"
        if tag == "grauInstr":
            return "07"
        if tag in ("paisNac", "paisNascto"):
            return "105"
        if tag in ("defFisica", "defVisual", "reabReadap", "depIRRF", "depSF"):
            return "N"
        if tag == "tpDep":
            return "03"
        if tag == "nisTrab":
            return "".join(str(r.randint(0, 9)) for _ in range(11))
        if tag == "codMotAfast":
            return r.choice(["01", "03", "15"])
        if tag == "mtvDeslig":
            return "02"
        if tag == "cep":
            return "%08d" % r.randint(1000000, 99999999)
        if tag in ("uf", "ufCtps", "ufCnh", "ufOC"):
            return "SC"
        if tag == "codMunic":
            return "4202404"
        if tag == "tpLograd":
            return "R"
        if tag == "dscLograd":
            return "Rua das Flores"
        if tag == "nrLograd":
            return str(r.randint(1, 2000))
        if tag == "bairro":
            return "Centro"
        if tag.startswith("fone"):
            return "479%08d" % r.randint(0, 99999999)
        if tag == "emailPrinc":
            return ctx.get("nome", "contato").split()[0].lower() + "@exemplo.com"
        if tag == "codCID":
            return "J11"
        if tag == "cnaePrep":
            return "6201501"
        if tag.startswith("nm"):
            return "%s %s" % (r.choice(NOMES), r.choice(SOBRENOMES))
        return str(r.randint(1, 999))

    # ---- montagem ------------------------------------------------------
    def evento(self, raiz, ctx):
        self.seq += 1
        env = ET.Element("eSocial")
        no = ET.SubElement(env, raiz, Id="ID1%s%020d" % (self.raiz_cnpj + "000000", self.seq))
        for partes in sorted(self.caminhos.get(raiz, [])):
            self._inserir(no, partes, [raiz], ctx)
        return env

    def _inserir(self, pai, partes, trilha, ctx):
        tag = partes[0]
        existentes = [e for e in pai if e.tag == tag]
        if len(partes) == 1:
            if not existentes:
                ET.SubElement(pai, tag).text = self.valor(tag, trilha, ctx, 0)
            return
        if not existentes:
            n = REPETIDOS.get(tag, 1)
            existentes = [ET.SubElement(pai, tag) for _ in range(n)]
        for i, filho in enumerate(existentes):
            sub = dict(ctx)
            if tag == "itensRemun" or tag == "detRubrFer":
                sub["rubrica"] = RUBRICAS[i % len(RUBRICAS)]
            if tag == "dependente":
                sub["dep_i"] = i
            self._inserir_folha(filho, partes[1:], trilha + [tag], sub, i)

    def _inserir_folha(self, pai, partes, trilha, ctx, i):
        if len(partes) == 1:
            tag = partes[0]
            if not any(e.tag == tag for e in pai):
                ET.SubElement(pai, tag).text = self.valor(tag, trilha, ctx, ctx.get("dep_i", i))
            return
        self._inserir(pai, partes, trilha, ctx)


def gerar(destino, colaboradores=25, semente=42):
    rng = random.Random(semente)
    with open(os.path.join(AQUI, "parametros.json"), encoding="utf-8") as f:
        par = json.load(f)
    g = Gerador(par, rng)
    raiz_evento = {v: k for k, v in g.mapa.items()}
    arquivos = []

    def gravar(codigo, arvore):
        pasta = os.path.join(destino, codigo)
        os.makedirs(pasta, exist_ok=True)
        nome = os.path.join(pasta, "%s_%05d.xml" % (codigo, g.seq))
        ET.ElementTree(arvore).write(nome, encoding="utf-8", xml_declaration=True)
        arquivos.append(nome)

    base = {"cargo": CARGOS[0], "estab": g.filiais[0]}
    gravar("S-1000", g.evento(raiz_evento["S-1000"], base))
    for est in g.filiais:
        gravar("S-1005", g.evento(raiz_evento["S-1005"], dict(base, estab=est)))
    for rub in RUBRICAS:
        gravar("S-1010", g.evento(raiz_evento["S-1010"], dict(base, rubrica=rub)))
    for lot in LOTACOES:
        gravar("S-1020", g.evento(raiz_evento["S-1020"], dict(base, lotacao=lot)))
    for cargo in CARGOS:
        gravar("S-1030", g.evento(raiz_evento["S-1030"], dict(base, cargo=cargo)))

    for n in range(colaboradores):
        estagiario = n % 8 == 7
        ctx = {
            "cpf": cpf(rng),
            "nome": "%s %s %s" % (rng.choice(NOMES), rng.choice(SOBRENOMES), rng.choice(SOBRENOMES)),
            "matricula": "M%05d" % (n + 1),
            "cargo": rng.choice(CARGOS),
            "lotacao": rng.choice(LOTACOES),
            "estab": rng.choice(g.filiais),
            "categ": "901" if estagiario else "101",
            "dtAdm": g.data(2015, 2023),
            "deps": [{"cpf": cpf(rng), "nome": "%s %s" % (rng.choice(NOMES), rng.choice(SOBRENOMES))}
                     for _ in range(2)],
        }
        if estagiario:
            gravar("S-2300", g.evento(raiz_evento["S-2300"], ctx))
            if rng.random() < .5:
                gravar("S-2306", g.evento(raiz_evento["S-2306"], ctx))
            continue
        gravar("S-2200", g.evento(raiz_evento["S-2200"], ctx))
        if rng.random() < .4:
            gravar("S-2205", g.evento(raiz_evento["S-2205"], ctx))
        if rng.random() < .5:
            gravar("S-2206", g.evento(raiz_evento["S-2206"], dict(ctx, cargo=rng.choice(CARGOS))))
        if rng.random() < .3:
            gravar("S-2230", g.evento(raiz_evento["S-2230"], ctx))
        for _ in range(2):
            gravar("S-1200", g.evento(raiz_evento["S-1200"], ctx))
        gravar("S-1210", g.evento(raiz_evento["S-1210"], ctx))
        if rng.random() < .15:
            gravar("S-2299", g.evento(raiz_evento["S-2299"], ctx))
    return arquivos


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("destino", nargs="?", default=os.path.join(AQUI, "exemplos", "massa_demo"))
    ap.add_argument("--colaboradores", type=int, default=25)
    ap.add_argument("--semente", type=int, default=42)
    a = ap.parse_args()
    feitos = gerar(a.destino, a.colaboradores, a.semente)
    print("%d XMLs gerados em %s" % (len(feitos), a.destino))
