"""Gera um PB sintético com erros propositais, para teste do analisador.

Erros plantados (esperados no relatório):
  numeração  : salto 5.1 -> 5.3; item 6.1 duplicado; subitem órfão 3.2.1; sem seção 7
  tabelas    : linha 2 com Qtd x Unitário != Total; linha TOTAL não fecha
  valores    : valor por extenso divergente do numeral
  ortografia : "a nível de", "afim de", "à partir", palavra repetida, "frizar"
  checklist  : sem declaração de sustentabilidade, sem matriz de riscos, sem DDI
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DESTINO = Path(__file__).with_name("PB_exemplo_com_erros.pdf")

base = getSampleStyleSheet()
h = ParagraphStyle("h", parent=base["Heading2"], fontSize=11, spaceBefore=10)
c = ParagraphStyle("c", parent=base["BodyText"], fontSize=9.5, leading=13)

f = []
A = lambda t, s=c: f.append(Paragraph(t, s))  # noqa: E731

A("PROJETO BÁSICO Nº 123/2026 — CONTRATAÇÃO DE SERVIÇOS DE SUPORTE TÉCNICO",
  ParagraphStyle("t", parent=base["Title"], fontSize=13))
f.append(Spacer(1, 8))

A("1. OBJETO", h)
A("1.1. Contratação de empresa especializada na prestação de serviços de suporte técnico "
  "a equipamentos de rede, com fornecimento de peças, para as unidades do SERPRO.")
A("1.2. A presente contratação decorre do Documento de Oficialização da Demanda "
  "DOD nº 45/2026 e do Estudo Técnico Preliminar ETP nº 45/2026.")

A("2. ESPECIFICAÇÃO DO OBJETO A SER CONTRATADO", h)
A("2.1. Os serviços serão prestados nas localidades de Brasília/DF (CEP 70070-350) e "
  "São Paulo/SP, mediante abertura de chamados técnicos.")
A("2.2. O prazo de execução dos serviços será de 12 (doze) meses.")
A("2.3. O recebimento provisório ocorrerá em até 5 (cinco) dias úteis e o recebimento "
  "definitivo em até 15 (quinze) dias, contados da conclusão de cada chamado.")
A("2.4. A contratada deverá deverá disponibilizar materiais acessórios nas quantidades "
  "previstas por localidade.")

A("3. NÍVEIS DE SERVIÇO E SANCIONAMENTOS", h)
A("3.1. O regime de atendimento será 24x7, com horário de atendimento ininterrupto.")
A("3.2.1. O tempo máximo para início do atendimento dos chamados é de 4 (quatro) horas.")
A("3.3. Aplica-se multa de 0,5% por hora de atraso, a nível de cada chamado em aberto.")

A("4. ESPECIFICAÇÃO DE VALORES E FORMA DE PAGAMENTO", h)
A("4.1. O valor total estimado da contratação é de R$ 486.000,00 (quatrocentos e oitenta "
  "mil reais).")
A("4.2. O pagamento será mensal, mediante apresentação de nota fiscal, conforme a tabela "
  "abaixo:")

dados = [
    ["Item", "Descrição", "Quantidade", "Valor Unitário", "Valor Total"],
    ["1", "Suporte técnico mensal — Brasília", "12", "R$ 22.000,00", "R$ 264.000,00"],
    ["2", "Suporte técnico mensal — São Paulo", "12", "R$ 15.000,00", "R$ 190.000,00"],
    ["3", "Banco de horas de atendimento", "500", "R$ 120,00", "R$ 60.000,00"],
    ["", "TOTAL", "", "", "R$ 486.000,00"],
]
t = Table(dados, colWidths=[1.3 * cm, 6.4 * cm, 2.4 * cm, 3.2 * cm, 3.4 * cm])
t.setStyle(TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9D9D9")),
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
]))
f.append(Spacer(1, 6))
f.append(t)
f.append(Spacer(1, 6))
A("4.3. O faturamento será realizado mensalmente, a partir do mês subsequente à "
  "assinatura do contrato.")

A("5. JUSTIFICATIVA DA CONTRATAÇÃO", h)
A("5.1. A contratação é necessária afim de manter a disponibilidade da infraestrutura de "
  "rede das unidades, vinculada ao Planejamento Estratégico e ao PDTI vigentes.")
A("5.3. As quantidades foram dimensionadas com base no histórico de chamados dos últimos "
  "24 meses, conforme memória de cálculo constante do ETP.")
A("5.4. A não contratação acarretará indisponibilidade dos serviços de rede, com impacto "
  "direto nos contratos de receita. Cumpre frizar que não há corpo técnico próprio "
  "disponível.")
A("5.5. Os DODs constantes da seção ITENS/DEMANDA VINCULADAS estão previstos no Plano de "
  "Contratações 2026.")
A("5.6. Para esta contratação foi observada a política de integridade de acordo com o "
  "art. 32, inc. V, da Lei nº 13.303/2016.")

A("6. SELEÇÃO DO FORNECEDOR", h)
A("6.1. A contratação será realizada por licitação, na modalidade pregão eletrônico, "
  "com fundamentação legal no art. 28 da Lei nº 13.303/2016 e na Norma LA 008.")
A("6.1. O critério de julgamento será o de menor preço global.")
A("6.2. Serão exigidos os critérios de habilitação previstos no edital, incluindo "
  "Atestado de Capacidade Técnica de acordo com Cláusula editalícia padrão do SERPRO.")
A("6.3. Não se aplica nesse tipo de contratação a permissão de consórcio.")
A("6.4. Declara-se que os serviços objeto desta contratação são serviços comuns.")

A("8. GESTÃO CONTRATUAL", h)
A("8.1. O prazo de vigência do contrato será de 12 (doze) meses, contados a partir da "
  "data de assinatura, podendo ser prorrogado até o limite de 60 (sessenta) meses.")
A("8.2. Os serviços são contínuos e prestados sem dedicação exclusiva de mão de obra.")
A("8.3. À partir do término da vigência, os equipamentos serão devolvidos.")

SimpleDocTemplate(str(DESTINO), pagesize=A4,
                  leftMargin=2 * cm, rightMargin=2 * cm,
                  topMargin=2 * cm, bottomMargin=2 * cm).build(f)
print(DESTINO)
