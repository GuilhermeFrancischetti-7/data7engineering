# Extrator eSocial → Senior HCM

[![testes](https://github.com/GuilhermeFrancischetti-7/data7engineering/actions/workflows/testes.yml/badge.svg)](https://github.com/GuilhermeFrancischetti-7/data7engineering/actions/workflows/testes.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Streamlit](https://img.shields.io/badge/streamlit-1.61-red)
![Licença](https://img.shields.io/badge/licen%C3%A7a-MIT-green)

> **English summary** — A Streamlit app that reads Brazilian eSocial XML events
> (payroll, hiring, leave, termination…) and converts them into the 48 import
> layouts of Senior HCM, for HR data migrations. The field mapping lives in a
> spreadsheet, not in code; ambiguous values become explicit *pending items*
> instead of plausible-but-wrong data. Tested on a real migration of ~650k XMLs
> and ~8k employees. Ships with a synthetic data generator so anyone can run it —
> [live demo](https://extrator-esocial-senior-hcm.streamlit.app).

![Demonstração: dos XMLs do eSocial aos 48 layouts Senior](docs/demo.gif)

**Demo online:** https://extrator-esocial-senior-hcm.streamlit.app · **Autor:** [Guilherme Francischetti](https://www.linkedin.com/in/guilhermefrancischetti)

---

## O problema

Toda empresa brasileira envia ao governo, pelo eSocial, o histórico completo dos
seus colaboradores em XML: admissão, alterações, afastamentos, folha, férias,
rescisão. Quando ela troca de sistema de RH, esses XMLs são a fonte mais
confiável para migrar os dados — mas o sistema novo não lê XML: espera dezenas
de arquivos posicionais com regras próprias de formato, códigos e chaves.

A solução anterior era um programa em Progress ABL que lia o XML **por posição
de caractere**: quebrava a cada variação de envelope e exigia código novo para
cada campo.

## A solução

Um app em Python/Streamlit que conduz a migração em seis etapas:

1. escolher o tipo de migração;
2. gerar a planilha de De/Para que o cliente preenche;
3. escolher os layouts de destino;
4. ler os XMLs (pasta, upload, ZIP dentro de ZIP ou uma leitura salva);
5. carregar o De/Para preenchido;
6. gerar os **48 layouts** Senior (561 campos) + relatório de pendências.

Quem abre pela primeira vez não fica perdido: um guia de 9 passos e uma trilha de
treino conduzem o caminho inteiro com dados fictícios.

```mermaid
flowchart LR
    X[XMLs eSocial<br/>pasta · ZIP · lote] --> R[xml_reader<br/>localiza eventos,<br/>deduplica por Id]
    P[Planilha de parâmetro<br/>.xlsx] --> G[gerar_parametros] --> J[parametros.json]
    J --> R
    J --> W[writer<br/>regras nomeadas,<br/>junções por CPF]
    R --> W
    D[depara<br/>cliente → domínio → cru] --> W
    W --> T[48 TXT Senior<br/>+ pendências.csv]
    W --> C[complementar.xlsx<br/>o que o cliente completa]
```

## Resultados no piloto real

| | |
|---|---|
| Volume processado | ~650 mil XMLs, ~8 mil colaboradores |
| Memória | 79 MB de XML lidos com **49 MB de pico** — o pico acompanha o maior arquivo, não a massa |
| Planilha complementar (40 mil linhas) | **78 s → 19 s** gravando em `write_only` com estilos registrados uma vez |
| Cobertura | 48 layouts, 561 campos, validados layout a layout com consultoria Senior |

## Decisões de design

- **O mapeamento vive na planilha, não no código.** Cada campo declara evento,
  caminho no XML, ação (`DIRETO`, `DEPARA_CLIENTE`, `REGRA`, `FIXO`…) e regra.
  `gerar_parametros.py` converte para um `parametros.json` versionado, então o
  diff mostra exatamente o que mudou no mapeamento entre versões. Código novo só
  entra para *mecanismos* genéricos.
- **Coluna vazia com pendência é melhor que dado plausível e errado.** Quando não
  há fonte confiável, o campo sai vazio e vai para `_pendencias.csv` com motivo.
  Exemplo: eventos como S-2230 só trazem a raiz do CNPJ; em vez de usar a raiz
  (válida, mas da granularidade errada), a filial é resolvida por junção pelo CPF
  com os eventos que a carregam.
- **Leitor genérico, sem código por evento.** A tag raiz de cada evento é deduzida
  dos caminhos da planilha; caminhos alternativos (`a | b`) cobrem o mesmo dado
  em eventos diferentes; nós repetidos (dependentes, rubricas) são descobertos
  sozinhos.
- **De/Para com precedência explícita:** tabela do cliente → tabela do cliente
  válida para todos os layouts → domínio oficial do eSocial → valor cru +
  pendência.
- **Robustez de entrada:** ZIP aninhado até 3 níveis, lotes com vários eventos,
  eventos duplicados descartados pelo `Id` do recibo, flags homônimas
  (`<evtRemun>S</evtRemun>` do S-1299) que não viram eventos fantasmas.
- **Leitura salva:** a massa já parseada vira um `.leitura` (zip com JSONL) e é
  reaberta sem varrer centenas de milhares de arquivos de novo.

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python gerar_massa_demo.py    # cria exemplos/massa_demo com XMLs fictícios
streamlit run app.py
```

O **Guia do App** abre sozinho na primeira tela: 9 passos com um GIF cada,
gravados do app de verdade. No fim dele, o **treino guiado** acompanha o
processo inteiro pela barra lateral, com a massa fictícia de `demo/xmls` — as
tarefas se marcam sozinhas conforme você faz cada etapa na tela.

Na etapa 4, escolha **Pasta no disco** e informe `demo/xmls` — ou baixe o ZIP
pelo botão da trilha e envie por upload.

## Testes

```bash
pip install pytest
pytest -q testes/test_extrator.py      # invariantes nos 48 layouts
python testes/validar_layouts.py       # relatório por layout
python testes/teste_ui.py              # percorre a interface inteira sem navegador
```

As invariantes: nenhum layout lança exceção, nenhuma linha duplicada, toda linha
tem o número de campos do layout, e a massa de demonstração não carrega dado
pessoal. Referência atual sobre `demo/xmls`: **48 layouts, 139 linhas, 0 erros**.
Rodam no GitHub Actions a cada push.

## Massa fictícia e GIFs do guia

Nada de dado real entra aqui. `testes/gerar_demo.py` escreve em `demo/xmls` os
XMLs de uma empresa inventada — 8 pessoas, dois estabelecimentos, cargos,
rubricas e folha —, com o mesmo envelope dos arquivos baixados do eSocial. São
33 XMLs que exercitam os 48 layouts.

`testes/gravar_guia.py` sobe um Streamlit numa porta própria, percorre a tela
com Playwright usando essa massa e grava os GIFs de `demo/guia`. Os GIFs são o
app real, não desenho, e o caminho que aparece neles é fictício — regrave quando
a tela mudar:

```bash
pip install playwright && playwright install chromium
python testes/gravar_guia.py
```

Um teste garante a regra: a massa versionada não pode conter CPF fora da faixa
de exemplo.

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | Interface Streamlit: 6 etapas, guia e treino guiado |
| `xml_reader.py` | Varre pasta/ZIP, identifica eventos, resolve caminhos, salva leituras |
| `writer.py` | Monta as linhas de cada layout; regras nomeadas em `REGRAS_IMPLEMENTADAS` |
| `depara.py` | Tabelas De/Para e precedência |
| `modelo_depara.py` | Gera a planilha de De/Para para o cliente |
| `complementar.py` | Planilha dos campos que o eSocial não tem e o cliente completa |
| `gerar_parametros.py` | Planilha de parâmetro → `parametros.json` |
| `gerar_dominios_esocial.py` | Tabelas de domínio oficiais do eSocial |
| `testes/gerar_demo.py` | Gera a massa de XMLs fictícia de `demo/xmls` |
| `testes/gravar_guia.py` | Grava os GIFs do guia percorrendo o app com Playwright |
| `demo/` | Massa fictícia e GIFs do guia |
| `parametro/` | Planilha de parâmetro (fonte da verdade do mapeamento) |
| `testes/` | pytest, validação de layouts e teste de UI |

## Stack

Python 3.12 · Streamlit · pandas · openpyxl · ElementTree · pytest · GitHub Actions

## Licença

MIT — veja [LICENSE](LICENSE). Os leiautes do eSocial e da Senior são
especificações públicas dos respectivos órgãos/fornecedores.
