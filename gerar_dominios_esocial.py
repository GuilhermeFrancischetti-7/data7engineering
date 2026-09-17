"""Leiaute oficial do eSocial (gov.br) -> dominios_esocial.json e
tabelas_esocial.json.

Guarda, para cada campo do leiaute, os "Valores validos" que a propria
documentacao lista (estCiv 1 = Solteiro, tpContr 2 = Prazo determinado...).
Complementa o tabelas_esocial.json, que so tem as tabelas numeradas (01, 07,
18...): a maior parte dos codigos do XML nao esta em tabela nenhuma, esta na
descricao do campo.

A chave e o id que a pagina da a cada linha: evento sem "S-" + caminho sem a
raiz, com "_" (2200_trabalhador_estCiv). O modelo_depara monta a mesma chave a
partir do caminho da planilha de parametro.

Uso:  py gerar_dominios_esocial.py [leiaute.html tabelas.html]
Sem arquivos, baixa as duas paginas do leiaute S-1.3.
"""
import html
import json
import os
import re
import sys
import urllib.request

BASE = ("https://www.gov.br/esocial/pt-br/documentacao-tecnica/"
        "leiautes-esocial-v-1.3/")
FONTE = BASE + "index.html"
FONTE_TABELAS = BASE + "tabelas.html"
PASTA = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(PASTA, "dominios_esocial.json")
DESTINO_TABELAS = os.path.join(PASTA, "tabelas_esocial.json")

LINHA = re.compile(
    r'<td class="seletor"[^>]*\bid="(\d{4}_[^"]+)"[^>]*></td>(.*?)</tr>', re.S)
CELULA = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
VALOR = re.compile(r"<strong>([^<]{1,12})</strong>\s*-\s*(.*?)(?=<br|$)", re.S)


def limpo(s):
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def extrair(pagina):
    dominios = {}
    for ident, resto in LINHA.findall(pagina):
        cel = CELULA.findall(resto)
        if len(cel) < 8:
            continue
        texto = cel[-1]
        # campo que so remete a tabela numerada ("codigo valido e existente
        # na Tabela 01"): guarda o numero, a descricao vem do tabelas_esocial
        ref = re.search(r"existente na\s*<a[^>]*>\s*Tabela (\d{2})", texto)
        if "Valores válidos:" not in texto:
            if ref:
                dominios[ident] = {"evento": "S-" + ident[:4],
                                   "tag": limpo(cel[0]),
                                   "descricao": limpo(texto.split("<br", 1)[0]),
                                   "tabela": ref.group(1), "valores": []}
            continue
        # os valores vem logo depois do rotulo e acabam na proxima secao
        # (Validacao, Evento de origem...), que tambem vem em <strong>
        trecho = texto.split("Valores válidos:", 1)[1]
        trecho = re.split(r"<strong>[^<]*:</strong>", trecho)[0]
        valores = []
        for codigo, desc in VALOR.findall(trecho):
            codigo, desc = limpo(codigo), limpo(desc)
            if codigo and desc:
                valores.append({"codigo": codigo, "descricao": desc})
        if not valores:
            continue          # ex.: lista de UFs em texto corrido
        dominios[ident] = {
            "evento": "S-" + ident[:4],
            "tag": limpo(cel[0]),
            "descricao": limpo(texto.split("<br", 1)[0]),
            "valores": valores,
        }
    return dominios


def ler(arquivo, url):
    if arquivo:
        with open(arquivo, encoding="utf-8") as f:
            return f.read()
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode("utf-8")


def tabelas(pagina):
    """Tabelas numeradas (01 Categorias, 18 Motivos de afastamento...).

    A coluna GRUPO usa rowspan: a primeira linha do grupo tem uma celula a
    mais. Sem repetir o valor nas linhas seguintes, o codigo cai na coluna do
    grupo -- foi assim que a tabela 01 ficou com 39 categorias sem numero.
    Descricao: a coluna NOME, quando existe (03), senao a DESCRICAO.
    """
    out = {}
    for num, corpo in re.findall(r'<table id="(\d{2})"[^>]*>(.*?)</table>', pagina, re.S):
        nome = limpo(re.search(r"<th[^>]*>(.*?)</th>", corpo, re.S).group(1))
        nome = re.sub(r"^Tabela \d+ - ", "", nome)
        linhas = re.findall(r"<tr[^>]*>(.*?)</tr>", corpo, re.S)
        cab = None; itens = []; pend = []   # pend: [restantes, valor] por coluna
        for ln in linhas:
            cel = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", ln, re.S)
            txt = [limpo(c) for _, c in cel]
            if cab is None:
                if any(t.upper().startswith("CÓDIGO") for t in txt):
                    cab = [t.upper() for t in txt]; pend = [[0, ""] for _ in cab]
                continue
            row = []; it = iter(cel)
            for j in range(len(cab)):
                if pend[j][0] > 0:
                    row.append(pend[j][1]); pend[j][0] -= 1; continue
                a, c = next(it, ("", ""))
                v = limpo(c); row.append(v)
                m = re.search(r'rowspan="(\d+)"', a)
                if m: pend[j] = [int(m.group(1)) - 1, v]
            ic = next(j for j, h in enumerate(cab) if h.startswith("CÓDIGO"))
            idd = next((j for j, h in enumerate(cab) if h.startswith("NOME")),
                       next((j for j, h in enumerate(cab) if h.startswith("DESCRI")), ic + 1))
            if row[ic] and all(i["codigo"] != row[ic] for i in itens):
                itens.append({"codigo": row[ic], "descricao": row[idd] if idd < len(row) else ""})
        out[num] = {"nome": nome, "itens": itens}
    return out


def main():
    args = sys.argv[1:] + [None, None]
    pagina = ler(args[0], FONTE)
    tabs = {k: v for k, v in tabelas(ler(args[1], FONTE_TABELAS)).items()
            if v["itens"]}
    with open(DESTINO_TABELAS, "w", encoding="utf-8") as f:
        json.dump(tabs, f, ensure_ascii=False, indent=1)
    print("tabelas:", {k: len(v["itens"]) for k, v in tabs.items()})
    dominios = extrair(pagina)
    with open(DESTINO, "w", encoding="utf-8") as f:
        json.dump({"fonte": FONTE, "campos": dominios}, f,
                  ensure_ascii=False, indent=1)
    print("campos com valores validos:", len(dominios))
    return 0


if __name__ == "__main__":
    sys.exit(main())
