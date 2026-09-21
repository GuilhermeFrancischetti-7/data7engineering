# -*- coding: utf-8 -*-
"""Gera a massa de demonstracao do guia: XMLs FICTICIOS, sem dado pessoal.

Uso:  py testes/gerar_demo.py

Escreve em demo/xmls/<evento>/. Empresa, pessoas, CPF, PIS, enderecos e valores
sao inventados -- nada vem da cliente piloto nem de qualquer cliente. Serve para quem
abre o app pela primeira vez rodar o processo inteiro sem precisar de massa real
(e sem esbarrar na LGPD).

A estrutura dos eventos segue o leiaute v2.4/v2.5 que o extrator ja le, com o
mesmo envelope dos XMLs baixados do eSocial. Nao e assinado: assinatura nao e
lida pelo extrator.
"""
import os
import sys

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(PASTA, "demo", "xmls")

CNPJ_MATRIZ = "11222333000181"
CNPJ_FILIAL = "11222333000262"
RAZAO = "Aurora Servicos Empresariais LTDA"
SIND = "33444555000199"

# (cpf, nome, nascimento, sexo, cargo, salario, admissao, matricula, cidade, bairro, cep)
PESSOAS = [
    ("10000000001", "ANA BEATRIZ SOARES",   "1988-03-12", "F", "001", "4500.00", "2019-02-01", "M0001", "3550308", "Pinheiros",   "05422010"),
    ("10000000002", "BRUNO CARDOSO LIMA",   "1992-07-25", "M", "002", "3200.00", "2020-06-15", "M0002", "3550308", "Pinheiros",   "05422010"),
    ("10000000003", "CARLA MENDES ROCHA",   "1985-11-03", "F", "003", "7800.00", "2018-01-08", "M0003", "3304557", "Tijuca",      "20511000"),
    ("10000000004", "DIEGO ALVES PINTO",    "1995-05-19", "M", "002", "3200.00", "2021-03-01", "M0004", "3304557", "Tijuca",      "20511000"),
    ("10000000005", "ELISA FONSECA DIAS",   "1990-09-30", "F", "004", "2600.00", "2022-08-22", "M0005", "3550308", "Santana",     "02012000"),
    ("10000000006", "FABIO NUNES TEIXEIRA", "1979-12-07", "M", "001", "5100.00", "2017-05-02", "M0006", "4106902", "Batel",       "80420090"),
    ("10000000007", "GISELE ARAUJO COSTA",  "1998-04-14", "F", "004", "2600.00", "2023-01-16", "M0007", "4106902", "Batel",       "80420090"),
    ("10000000008", "HENRIQUE SILVA BRAGA", "1983-08-21", "M", "003", "8300.00", "2016-09-12", "M0008", "3550308", "Santana",     "02012000"),
]
CARGOS = [("001", "ANALISTA ADMINISTRATIVO", "252105"),
          ("002", "ASSISTENTE DE OPERACOES", "411005"),
          ("003", "GERENTE DE PROJETOS", "142310"),
          ("004", "AUXILIAR DE SERVICOS GERAIS", "514320")]
RUBRICAS = [("101", "SALARIO BASE", "1"), ("201", "INSS", "9"), ("202", "IRRF", "9")]

ENVELOPE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<eSocial xmlns="http://www.esocial.gov.br/schema/download/retornoProcessamento/v1_0_0">'
    '<retornoProcessamentoDownload><evento>'
    '<eSocial xmlns="http://www.esocial.gov.br/schema/evt/%s/v02_05_00">%s</eSocial>'
    '</evento></retornoProcessamentoDownload></eSocial>')

IDE_EVENTO = ("<ideEvento><indRetif>1</indRetif><tpAmb>1</tpAmb>"
              "<procEmi>1</procEmi><verProc>DEMO</verProc></ideEvento>")
IDE_EMPREGADOR = ("<ideEmpregador><tpInsc>1</tpInsc><nrInsc>%s</nrInsc></ideEmpregador>"
                  % CNPJ_MATRIZ[:8])


def _id(seq):
    """Id do recibo: o extrator usa isso para descartar evento repetido."""
    return "ID1%s%019d" % (CNPJ_MATRIZ, seq)


def gravar(evento, schema, corpo, seq):
    """Um XML por evento, na pasta do evento -- como a massa real vem."""
    pasta = os.path.join(DESTINO, evento)
    os.makedirs(pasta, exist_ok=True)
    nome = "%s.%s.xml" % (_id(seq), evento)
    with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:
        f.write(ENVELOPE % (schema, corpo))


def gerar():
    seq = 0

    def proximo():
        nonlocal seq
        seq += 1
        return seq

    # ---- S-1000: o empregador
    n = proximo()
    gravar("S-1000", "evtInfoEmpregador",
           '<evtInfoEmpregador Id="%s">%s%s<infoEmpregador><inclusao>'
           '<idePeriodo><iniValid>2018-01</iniValid></idePeriodo>'
           '<infoCadastro><nmRazao>%s</nmRazao><classTrib>01</classTrib>'
           '<natJurid>2062</natJurid><indCoop>0</indCoop><indConstr>0</indConstr>'
           '<indDesFolha>0</indDesFolha><indOptRegEletron>1</indOptRegEletron>'
           '<contato><nmCtt>MARIA DEMONSTRACAO</nmCtt><cpfCtt>10000000009</cpfCtt>'
           '<foneFixo>1133334444</foneFixo><foneCel>11988887777</foneCel>'
           '<email>contato@aurora-demo.com.br</email></contato>'
           '</infoCadastro></inclusao></infoEmpregador></evtInfoEmpregador>'
           % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, RAZAO), n)

    # ---- S-1005: matriz e filial
    for cnpj in (CNPJ_MATRIZ, CNPJ_FILIAL):
        n = proximo()
        gravar("S-1005", "evtTabEstab",
               '<evtTabEstab Id="%s">%s%s<infoEstab><inclusao>'
               '<ideEstab><tpInsc>1</tpInsc><nrInsc>%s</nrInsc>'
               '<iniValid>2018-01</iniValid></ideEstab>'
               '<dadosEstab><cnaePrep>8211300</cnaePrep>'
               '<aliqGilrat><aliqRat>1</aliqRat><fap>1.00</fap>'
               '<aliqRatAjust>1.00</aliqRatAjust></aliqGilrat>'
               '<infoTrab><regPt>S</regPt></infoTrab>'
               '</dadosEstab></inclusao></infoEstab></evtTabEstab>'
               % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, cnpj), n)

    # ---- S-1020: lotacao
    n = proximo()
    gravar("S-1020", "evtTabLotacao",
           '<evtTabLotacao Id="%s">%s%s<infoLotacao><inclusao>'
           '<ideLotacao><codLotacao>LOT01</codLotacao>'
           '<iniValid>2018-01</iniValid></ideLotacao>'
           '<dadosLotacao><tpLotacao>01</tpLotacao><tpInsc>1</tpInsc>'
           '<nrInsc>%s</nrInsc><fpasLotacao><fpas>515</fpas>'
           '<codTercs>0079</codTercs></fpasLotacao></dadosLotacao>'
           '</inclusao></infoLotacao></evtTabLotacao>'
           % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, CNPJ_MATRIZ), n)

    # ---- S-1030: cargos
    for codigo, nome, cbo in CARGOS:
        n = proximo()
        gravar("S-1030", "evtTabCargo",
               '<evtTabCargo Id="%s">%s%s<infoCargo><inclusao>'
               '<ideCargo><codCargo>%s</codCargo><iniValid>2018-01</iniValid></ideCargo>'
               '<dadosCargo><nmCargo>%s</nmCargo><codCBO>%s</codCBO></dadosCargo>'
               '</inclusao></infoCargo></evtTabCargo>'
               % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, codigo, nome, cbo), n)

    # ---- S-1010: rubricas da folha
    for codigo, descricao, natureza in RUBRICAS:
        n = proximo()
        gravar("S-1010", "evtTabRubrica",
               '<evtTabRubrica Id="%s">%s%s<infoRubrica><inclusao>'
               '<ideRubrica><codRubr>%s</codRubr><ideTabRubr>DEMO</ideTabRubr>'
               '<iniValid>2018-01</iniValid></ideRubrica>'
               '<dadosRubrica><dscRubr>%s</dscRubr><natRubr>%s</natRubr>'
               '<tpRubr>1</tpRubr><codIncCP>11</codIncCP><codIncIRRF>11</codIncIRRF>'
               '</dadosRubrica></inclusao></infoRubrica></evtTabRubrica>'
               % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, codigo, descricao, natureza), n)

    # ---- S-2200: admissoes
    for i, p in enumerate(PESSOAS):
        cpf, nome, nascto, sexo, cargo, salario, admissao, matricula, cidade, bairro, cep = p
        estab = CNPJ_MATRIZ if i % 2 == 0 else CNPJ_FILIAL
        dependente = ("<dependente><tpDep>03</tpDep><nmDep>LUCAS %s</nmDep>"
                      "<dtNascto>2015-04-10</dtNascto><depIRRF>S</depIRRF>"
                      "<depSF>S</depSF><incTrab>N</incTrab></dependente>"
                      % nome.split()[0]) if i < 3 else ""
        n = proximo()
        gravar("S-2200", "evtAdmissao",
               '<evtAdmissao Id="%s">%s%s<trabalhador>'
               '<cpfTrab>%s</cpfTrab><nisTrab>2%s</nisTrab><nmTrab>%s</nmTrab>'
               '<sexo>%s</sexo><racaCor>1</racaCor><estCiv>1</estCiv>'
               '<grauInstr>07</grauInstr><indPriEmpr>N</indPriEmpr>'
               '<nascimento><dtNascto>%s</dtNascto><codMunic>%s</codMunic>'
               '<paisNascto>105</paisNascto><paisNac>105</paisNac>'
               '<nmMae>MARIA %s</nmMae></nascimento>'
               '<endereco><brasil><tpLograd>R</tpLograd>'
               '<dscLograd>DAS FLORES</dscLograd><nrLograd>%d</nrLograd>'
               '<bairro>%s</bairro><cep>%s</cep><codMunic>%s</codMunic>'
               '<uf>%s</uf></brasil></endereco>%s</trabalhador>'
               '<vinculo><matricula>%s</matricula><tpRegTrab>1</tpRegTrab>'
               '<tpRegPrev>1</tpRegPrev><cadIni>N</cadIni>'
               '<infoRegimeTrab><infoCeletista><dtAdm>%s</dtAdm>'
               '<tpAdmissao>1</tpAdmissao><indAdmissao>1</indAdmissao>'
               '<tpRegJor>1</tpRegJor><natAtividade>1</natAtividade>'
               '<dtBase>5</dtBase><cnpjSindCategProf>%s</cnpjSindCategProf>'
               '</infoCeletista></infoRegimeTrab>'
               '<infoContrato><codCargo>%s</codCargo><codCateg>101</codCateg>'
               '<remuneracao><vrSalFx>%s</vrSalFx><undSalFixo>5</undSalFixo>'
               '</remuneracao><duracao><tpContr>1</tpContr></duracao>'
               '<localTrabalho><localTrabGeral><tpInsc>1</tpInsc>'
               '<nrInsc>%s</nrInsc></localTrabGeral></localTrabalho>'
               '<horContratual><qtdHrsSem>44.00</qtdHrsSem><tpJornada>9</tpJornada>'
               '<tmpParc>0</tmpParc></horContratual>'
               '<filiacaoSindical><cnpjSindTrab>%s</cnpjSindTrab></filiacaoSindical>'
               '</infoContrato></vinculo></evtAdmissao>'
               % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, cpf, cpf, nome, sexo, nascto,
                  cidade, nome.split()[-1], 100 + i * 7, bairro, cep, cidade,
                  {"3550308": "SP", "3304557": "RJ", "4106902": "PR"}[cidade],
                  dependente, matricula, admissao, SIND, cargo, salario, estab, SIND), n)

    # ---- S-2206: alteracao de cargo e salario (2 pessoas)
    for i, p in enumerate(PESSOAS[:2]):
        cpf, nome, _, _, cargo, salario, _, matricula = p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]
        novo_cargo = "003"
        novo_salario = "%.2f" % (float(salario) * 1.15)
        n = proximo()
        gravar("S-2206", "evtAltContratual",
               '<evtAltContratual Id="%s">%s%s'
               '<ideVinculo><cpfTrab>%s</cpfTrab><matricula>%s</matricula></ideVinculo>'
               '<altContratual><dtAlteracao>2023-04-01</dtAlteracao>'
               '<vinculo><tpRegPrev>1</tpRegPrev></vinculo>'
               '<infoRegimeTrab><infoCeletista><tpRegJor>1</tpRegJor>'
               '<natAtividade>1</natAtividade><dtBase>5</dtBase>'
               '<cnpjSindCategProf>%s</cnpjSindCategProf></infoCeletista>'
               '</infoRegimeTrab>'
               '<infoContrato><codCargo>%s</codCargo><codCateg>101</codCateg>'
               '<remuneracao><vrSalFx>%s</vrSalFx><undSalFixo>5</undSalFixo>'
               '</remuneracao><duracao><tpContr>1</tpContr></duracao>'
               '<localTrabalho><localTrabGeral><tpInsc>1</tpInsc><nrInsc>%s</nrInsc>'
               '</localTrabGeral></localTrabalho>'
               '<horContratual><qtdHrsSem>44.00</qtdHrsSem><tpJornada>9</tpJornada>'
               '<tmpParc>0</tmpParc></horContratual></infoContrato></altContratual>'
               '</evtAltContratual>'
               % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, cpf, matricula, SIND,
                  novo_cargo, novo_salario, CNPJ_MATRIZ), n)

    # ---- S-2205: mudanca de endereco
    p = PESSOAS[2]
    n = proximo()
    gravar("S-2205", "evtAltCadastral",
           '<evtAltCadastral Id="%s">%s%s'
           '<ideTrabalhador><cpfTrab>%s</cpfTrab></ideTrabalhador>'
           '<alteracao><dtAlteracao>2023-02-10</dtAlteracao><dadosTrabalhador>'
           '<nmTrab>%s</nmTrab><sexo>F</sexo><racaCor>1</racaCor><estCiv>2</estCiv>'
           '<grauInstr>09</grauInstr>'
           '<nascimento><dtNascto>%s</dtNascto><codMunic>3304557</codMunic>'
           '<paisNascto>105</paisNascto><paisNac>105</paisNac></nascimento>'
           '<endereco><brasil><tpLograd>AV</tpLograd><dscLograd>DAS ACACIAS</dscLograd>'
           '<nrLograd>2000</nrLograd><bairro>Copacabana</bairro><cep>22041001</cep>'
           '<codMunic>3304557</codMunic><uf>RJ</uf></brasil></endereco>'
           '</dadosTrabalhador></alteracao></evtAltCadastral>'
           % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, p[0], p[1], p[2]), n)

    # ---- S-2230: afastamento (doenca) e ferias
    afastamentos = [(PESSOAS[3][0], PESSOAS[3][7], "03", "2023-05-02", "2023-05-20"),
                    (PESSOAS[0][0], PESSOAS[0][7], "15", "2023-07-03", "2023-08-01"),
                    (PESSOAS[5][0], PESSOAS[5][7], "15", "2023-09-04", "2023-10-03")]
    for cpf, matricula, motivo, inicio, fim in afastamentos:
        n = proximo()
        gravar("S-2230", "evtAfastTemp",
               '<evtAfastTemp Id="%s">%s%s'
               '<ideVinculo><cpfTrab>%s</cpfTrab><matricula>%s</matricula></ideVinculo>'
               '<infoAfastamento><iniAfastamento><dtIniAfast>%s</dtIniAfast>'
               '<codMotAfast>%s</codMotAfast></iniAfastamento>'
               '<fimAfastamento><dtTermAfast>%s</dtTermAfast></fimAfastamento>'
               '</infoAfastamento></evtAfastTemp>'
               % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, cpf, matricula, inicio,
                  motivo, fim), n)

    # ---- S-2299: desligamento
    p = PESSOAS[6]
    n = proximo()
    gravar("S-2299", "evtDeslig",
           '<evtDeslig Id="%s">%s%s'
           '<ideVinculo><cpfTrab>%s</cpfTrab><matricula>%s</matricula></ideVinculo>'
           '<infoDeslig><mtvDeslig>02</mtvDeslig><dtDeslig>2023-11-30</dtDeslig>'
           '<dtAvPrv>2023-11-01</dtAvPrv><indPagtoAPI>N</indPagtoAPI>'
           '<pensAlim>0</pensAlim><indCumprParc>0</indCumprParc>'
           '<verbasResc><dmDev><ideDmDev>RESC01</ideDmDev>'
           '<infoPerApur><ideEstabLot><tpInsc>1</tpInsc><nrInsc>%s</nrInsc>'
           '<codLotacao>LOT01</codLotacao><detVerbas><codRubr>101</codRubr>'
           '<ideTabRubr>DEMO</ideTabRubr><vrRubr>2600.00</vrRubr></detVerbas>'
           '</ideEstabLot></infoPerApur></dmDev></verbasResc>'
           '</infoDeslig></evtDeslig>'
           % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, p[0], p[7], CNPJ_MATRIZ), n)

    # ---- S-1200: folha mensal de 3 pessoas
    for p in PESSOAS[:3]:
        for competencia in ("2023-10", "2023-11"):
            n = proximo()
            gravar("S-1200", "evtRemun",
                   '<evtRemun Id="%s"><ideEvento><indRetif>1</indRetif>'
                   '<indApuracao>1</indApuracao><perApur>%s</perApur><tpAmb>1</tpAmb>'
                   '<procEmi>1</procEmi><verProc>DEMO</verProc></ideEvento>%s'
                   '<ideTrabalhador><cpfTrab>%s</cpfTrab></ideTrabalhador>'
                   '<dmDev><ideDmDev>FOLHA%s</ideDmDev><codCateg>101</codCateg>'
                   '<infoPerApur><ideEstabLot><tpInsc>1</tpInsc><nrInsc>%s</nrInsc>'
                   '<codLotacao>LOT01</codLotacao>'
                   '<remunPerApur><matricula>%s</matricula>'
                   '<itensRemun><codRubr>101</codRubr><ideTabRubr>DEMO</ideTabRubr>'
                   '<vrRubr>%s</vrRubr></itensRemun>'
                   '<itensRemun><codRubr>201</codRubr><ideTabRubr>DEMO</ideTabRubr>'
                   '<vrRubr>%.2f</vrRubr></itensRemun>'
                   '</remunPerApur></ideEstabLot></infoPerApur></dmDev></evtRemun>'
                   % (_id(n), competencia, IDE_EMPREGADOR, p[0],
                      competencia.replace("-", ""), CNPJ_MATRIZ, p[7], p[5],
                      float(p[5]) * 0.09), n)

    # ---- S-2300: estagiaria (trabalhador sem vinculo)
    n = proximo()
    gravar("S-2300", "evtTSVInicio",
           '<evtTSVInicio Id="%s">%s%s<trabalhador>'
           '<cpfTrab>10000000010</cpfTrab><nmTrab>IARA DEMONSTRACAO SANTOS</nmTrab>'
           '<sexo>F</sexo><racaCor>1</racaCor><grauInstr>08</grauInstr>'
           '<nascimento><dtNascto>2002-06-18</dtNascto><codMunic>3550308</codMunic>'
           '<paisNascto>105</paisNascto><paisNac>105</paisNac></nascimento>'
           '<endereco><brasil><tpLograd>R</tpLograd><dscLograd>DAS PALMEIRAS</dscLograd>'
           '<nrLograd>45</nrLograd><bairro>Pinheiros</bairro><cep>05422010</cep>'
           '<codMunic>3550308</codMunic><uf>SP</uf></brasil></endereco></trabalhador>'
           '<infoTSVInicio><cadIni>N</cadIni><codCateg>901</codCateg>'
           '<dtInicio>2023-03-01</dtInicio>'
           '<infoComplementares><cargoFuncao><codCargo>004</codCargo></cargoFuncao>'
           '<remuneracao><vrSalFx>1400.00</vrSalFx><undSalFixo>5</undSalFixo>'
           '</remuneracao><infoEstagiario><natEstagio>N</natEstagio>'
           '<nivEstagio>3</nivEstagio><fimPrevisto>2024-02-29</fimPrevisto>'
           '<instEnsino><cnpjInstEnsino>44555666000177</cnpjInstEnsino>'
           '<nmRazao>FACULDADE DEMONSTRACAO</nmRazao><dscLograd>R DO SABER</dscLograd>'
           '<nrLograd>10</nrLograd><bairro>Centro</bairro><cep>01001000</cep>'
           '<codMunic>3550308</codMunic><uf>SP</uf></instEnsino>'
           '</infoEstagiario><localTrabGeral><tpInsc>1</tpInsc><nrInsc>%s</nrInsc>'
           '</localTrabGeral></infoComplementares></infoTSVInicio></evtTSVInicio>'
           % (_id(n), IDE_EVENTO, IDE_EMPREGADOR, CNPJ_MATRIZ), n)

    return seq


if __name__ == "__main__":
    total = gerar()
    print("%d XML(s) ficticio(s) em %s" % (total, DESTINO))
    sys.exit(0)
