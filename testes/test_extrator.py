# -*- coding: utf-8 -*-
"""Invariantes do extrator sobre a massa fictícia de `demo/xmls` (pytest)."""
import collections
import json
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import depara  # noqa: E402
import gerar_demo  # noqa: E402  (testes/ está no sys.path do pytest)
import writer  # noqa: E402
import xml_reader  # noqa: E402

MASSA = os.path.join(RAIZ, "demo", "xmls")


@pytest.fixture(scope="session")
def parametros():
    with open(os.path.join(RAIZ, "parametros.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def documentos(parametros):
    # A massa é versionada; se faltar, é porque alguém apagou demo/xmls.
    if not os.path.isdir(MASSA):
        gerar_demo.gerar()
    docs, _, _, _ = xml_reader.carregar_documentos(parametros=parametros,
                                                   pasta=MASSA, recursivo=True)
    return docs


def test_parametro_cobre_48_layouts(parametros):
    assert len(parametros["modulos"]) == 48


def test_todo_xml_da_demo_e_reconhecido(documentos):
    assert len(documentos) >= 30
    assert all(d.evento.startswith("S-") for d in documentos)


def test_massa_de_demo_nao_tem_dado_de_cliente():
    """A demo é fictícia por contrato: CPF real nunca entra no repositório."""
    for raiz, _, arquivos in os.walk(MASSA):
        for nome in arquivos:
            texto = open(os.path.join(raiz, nome), encoding="utf-8").read()
            # Os CPFs da demo são a faixa 100000000xx, reservada ao exemplo.
            for marca in ("<cpfTrab>", "<cpfBenef>", "<cpfDep>"):
                for pedaco in texto.split(marca)[1:]:
                    assert pedaco[:3] == "100", pedaco[:11]


def test_caminhos_alternativos():
    assert xml_reader.alternativas("a/b | c/d") == ["a/b", "c/d"]
    assert xml_reader.alternativas("") == []


def test_flag_homonima_nao_vira_evento():
    xml = "<eSocial><infoFech><evtRemun>S</evtRemun></infoFech></eSocial>"
    assert xml_reader.ler_xml(xml, "x.xml", {"evtRemun": "S-1200"}) == []


@pytest.mark.parametrize("codigo", [str(c) for c in range(1000, 1056)])
def test_layout_sem_erro_e_sem_linha_duplicada(codigo, parametros, documentos):
    if codigo not in parametros["modulos"]:
        pytest.skip("layout inexistente")
    linhas, _, _ = writer.montar_modulo(codigo, parametros, documentos,
                                        depara.Tabelas(parametros), deduplicar=True)
    campos = parametros["modulos"][codigo]["campos"]
    assert all(len(l) == len(campos) for l in linhas)
    assert not [k for k, v in collections.Counter(map(tuple, linhas)).items() if v > 1]
