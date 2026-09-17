# -*- coding: utf-8 -*-
"""Invariantes do extrator sobre a massa sintetica (roda com pytest)."""
import collections
import json
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import depara  # noqa: E402
import gerar_massa_demo  # noqa: E402
import writer  # noqa: E402
import xml_reader  # noqa: E402


@pytest.fixture(scope="session")
def parametros():
    with open(os.path.join(RAIZ, "parametros.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def documentos(parametros, tmp_path_factory):
    pasta = tmp_path_factory.mktemp("massa")
    gerar_massa_demo.gerar(str(pasta), colaboradores=20, semente=7)
    docs, _, _, _ = xml_reader.carregar_documentos(parametros=parametros,
                                                   pasta=str(pasta), recursivo=True)
    return docs


def test_parametro_cobre_48_layouts(parametros):
    assert len(parametros["modulos"]) == 48


def test_todo_xml_gerado_e_reconhecido(documentos):
    assert documentos
    assert all(d.evento.startswith("S-") for d in documentos)


def test_cpf_sintetico_tem_digito_valido():
    import random
    cpf = gerar_massa_demo.cpf(random.Random(1))
    assert len(cpf) == 11 and cpf == cpf[:9] + gerar_massa_demo._dv(cpf[:9], range(10, 1, -1)) + cpf[10]


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
