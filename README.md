# Biblioteca Analytics

Programa simples para recolher dados de navegação da **Biblioteca Virtual** e medir a
sua usabilidade: livros mais procurados, mais lidos, não encontrados, tempo de pesquisa
e tempo de leitura — por dia, semana e mês.

Só precisa de **Python 3.10+** (biblioteca padrão + SQLite). Não há nada para instalar.

> **Biblioteca na Perlego?** Não é possível pôr scripts dentro do site da Perlego, por isso há
> duas fontes de dados que se completam — ver [Perlego](#perlego):
> 1. a **extensão de navegador** `extensao-perlego/`, instalada nos computadores da biblioteca
>    (pesquisas, não encontrados, tempos de pesquisa e leitura, por computador);
> 2. os **relatórios oficiais COUNTER** da Perlego, importados no painel
>    (livros mais lidos de toda a instituição, incluindo acessos de casa).

```
biblioteca-analytics/
├── servidor.py          # recebe eventos, serve o painel e a API de métricas
├── analytics.py         # base de dados e cálculo das métricas
├── relatorio.py         # relatório na consola / exportação CSV, sem servidor
├── relatorio_mensal.py  # relatório mensal em PDF enviado por e-mail (Brevo ou SMTP)
├── importar_counter.py  # importa relatórios COUNTER (Perlego) em XLSX/CSV/TSV
├── extensao-perlego/    # extensão Chrome/Edge para os computadores da biblioteca
├── instalacao/          # instalador para servidor Ubuntu/Debian (HTTPS, serviço, cópias)
├── gerar_dados_demo.py  # dados fictícios para experimentar
├── static/
│   ├── tracker.js       # script a incluir nas páginas da biblioteca
│   ├── painel.html      # painel de métricas
│   └── demo.html        # biblioteca de demonstração
└── tests/
```

## Instalar num servidor na internet (produção)

Para os computadores da biblioteca e o seu PC estarem em redes diferentes, siga o
**[guia de instalação](instalacao/GUIA-INSTALACAO.md)**: um comando instala tudo num servidor
Ubuntu/Debian, com HTTPS, arranque automático, chaves de acesso e cópias de segurança diárias.

## Experimentar em 1 minuto

```bash
cd biblioteca-analytics
python gerar_dados_demo.py          # 90 dias de dados fictícios
python servidor.py                  # abre http://127.0.0.1:8080
```

- `http://127.0.0.1:8080/` — painel de métricas
- `http://127.0.0.1:8080/demo` — biblioteca de demonstração: pesquise, abra livros, leia,
  peça livros inexistentes e veja os números mudar no painel.

Para começar com dados reais, apague `biblioteca_analytics.db` antes de pôr o servidor em produção.

## Perlego

Na Perlego cada leitor entra com a **sua conta individual**. Nem a extensão nem o servidor leem
nomes, e-mails ou dados da conta; e a própria Perlego também não dá dados por utilizador aos
administradores. As métricas são, por isso, por computador e por instituição — não por pessoa.

| Pergunta | Extensão nos PCs | Relatórios COUNTER |
|---|---|---|
| Livros mais lidos / abertos | ✓ (só nos PCs da biblioteca) | ✓ (toda a instituição) |
| Tempo de leitura | ✓ | — |
| Termos pesquisados, pesquisas sem resultados | ✓ | — |
| Tempo de pesquisa, posição do clique, taxa de sucesso | ✓ | — |
| Por computador, ativo agora | ✓ | — |
| Acessos de casa / telemóvel / app | — | ✓ |
| Precisa de | instalar a extensão em cada PC | conta de **administrador** Perlego |

### 1. Extensão para os computadores da biblioteca (Chrome ou Edge)

Instalação em cada computador:

1. Copie a pasta `extensao-perlego/` para o computador (ex.: `C:\BibliotecaAnalytics\extensao-perlego`).
2. Abra `chrome://extensions` (ou `edge://extensions`), ative **Modo de programador** e clique
   **Carregar sem compactação** → escolha a pasta.
3. Nos detalhes da extensão abra **Opções da extensão** e preencha:
   - **Endereço do servidor de métricas**, ex.: `http://192.168.1.10:8080`;
   - **Nome deste computador**, ex.: `PC-01` (ou deixe vazio e use `postos.json` por IP).
   A página de opções mostra se o servidor está contactável e quantos eventos estão à espera.
4. No primeiro computador, ligue o **Modo diagnóstico** e faça uma pesquisa, abra e leia um livro:
   no canto da página aparece o que a extensão deteta. Se algo não for detetado, ajuste os
   endereços em *Endereços da Perlego (avançado)* e desligue o diagnóstico no fim.

O que a extensão regista: pesquisas (termo, nº de resultados, tempo a escrever), clique num
resultado (posição e tempo até escolher), livros abertos (id e título), tempo de leitura ativa
no leitor (separador visível + interação nos últimos 2 min) e um sinal de presença por minuto.
Os eventos ficam guardados no navegador se o servidor estiver em baixo e são enviados depois.

**Importante — a confirmar no vosso site:** a extensão reconhece as páginas pelo endereço
(`/search` para resultados, `/book/<id>` para um livro, `/reader/` para o leitor) e conta os
resultados pelos links para livros na página. O endereço da pesquisa foi confirmado; os do livro
e do leitor não puderam ser confirmados com uma conta real, e a Perlego pode mudar o site.
Por isso o passo 4 (diagnóstico) é essencial.

Para muitos computadores, o administrador de TI pode fixar a configuração por política do navegador
(`chrome.storage.managed`, esquema em `extensao-perlego/schema.json`): os campos definidos por
política ficam bloqueados na página de opções.

Limites: só regista o uso no Chrome/Edge com a extensão; não vê a app da Perlego, telemóveis nem
acessos de casa (para isso servem os relatórios COUNTER).

### 2. Relatórios oficiais COUNTER da Perlego

Quem tem conta de **administrador** da instituição na Perlego descarrega os relatórios em
**Organisation Subscription Manager → Analytics** (relatórios COUNTER, de preferência o **TR_B1**
com detalhe mensal). Se ninguém na instituição tem esse acesso, peça-o ao gestor de conta da
Perlego; o acesso por API também é pedido ao suporte.

Importe o ficheiro (XLSX, CSV ou TSV) no painel, no cartão *Perlego — relatórios oficiais*,
botão **Importar relatório…**, ou na consola:

```bash
python importar_counter.py TR_B1_2026.xlsx
```

Reimportar o mesmo mês substitui os valores (não duplica). O painel mostra os títulos mais
abertos e a evolução mensal (`Unique_Title_Requests` e `Total_Item_Requests`).

## Ligar a um site próprio (sem ser Perlego)

Se a biblioteca tiver também um site/catálogo próprio, pode usar o `tracker.js` diretamente:

1. Inclua o script em todas as páginas da biblioteca:

   ```html
   <script src="https://SERVIDOR-METRICAS/tracker.js" defer></script>
   ```

2. Marque a caixa de pesquisa para medir o tempo de escrita: `<input data-ba-pesquisa ...>`

3. Chame as funções nos pontos certos do código da biblioteca:

   | Momento | Chamada |
   |---|---|
   | Pesquisa submetida (já sabe quantos resultados há) | `BibliotecaAnalytics.pesquisa(termo, numResultados)` |
   | Utilizador clica num resultado | `BibliotecaAnalytics.cliqueResultado(idLivro, titulo, posicao)` |
   | Abre a ficha de um livro | `BibliotecaAnalytics.vistaLivro(idLivro, titulo)` |
   | Abre o leitor / começa a ler | `BibliotecaAnalytics.iniciarLeitura(idLivro, titulo)` |
   | Fecha o leitor | `BibliotecaAnalytics.terminarLeitura()` |
   | Pede um livro que não existe, ou link para livro inexistente | `BibliotecaAnalytics.naoEncontrado(termoOuTitulo)` |

   O `static/demo.html` é um exemplo completo de integração.

## Vários computadores da biblioteca

(Com a Perlego, o nome do computador é definido nas opções da extensão, ou por IP — opção B abaixo.)

O programa identifica cada computador (posto) da biblioteca e mostra, no painel:

- **quais computadores estão ativos agora** (deram sinal no último minuto ou dois) e há quanto tempo cada um está parado;
- **horas de uso**, sessões, pesquisas, taxa de sucesso, livros não encontrados e minutos de leitura **por computador**;
- um **filtro "Computador"**: todas as métricas e gráficos passam a referir-se só a esse computador
  (ou clique numa linha da tabela *Computadores*);
- os acessos de fora da biblioteca (p. ex. de casa) aparecem como **"Não identificado"**.

Cada página aberta envia um sinal de presença por minuto. As horas de uso só contam com a página
visível e alguém a usar o computador (rato, teclado, toque) nos últimos 5 minutos.

Há duas formas de dar nome aos computadores — use a que for mais prática:

**A. Pelo navegador (não precisa de mexer no servidor).** Em cada computador, abra uma vez qualquer
página da biblioteca com `?ba_posto=NOME` no fim do endereço, por exemplo
`https://biblioteca.exemplo.ao/?ba_posto=PC-01`. O nome fica guardado nesse navegador.
Se os computadores apagam os dados do navegador ao reiniciar (Deep Freeze, modo quiosque, etc.),
ponha esse endereço como **página inicial** do navegador, ou use a opção B.

**B. Pelo endereço IP (recomendado quando os computadores têm IP fixo na rede da biblioteca).**
Copie `postos.exemplo.json` para `postos.json` e escreva o IP e o nome de cada computador:

```json
{ "192.168.1.21": "Sala de leitura - PC 01", "192.168.1.22": "Sala de leitura - PC 02" }
```

O servidor relê o ficheiro sozinho quando ele muda. Só funciona se o servidor de métricas estiver
na mesma rede que os computadores (vê o IP interno). Se estiver atrás de um proxy (Nginx), defina
`BIBLIO_CONFIAR_PROXY=1`. O IP serve só para encontrar o nome; não é guardado.

O nome enviado pelo navegador (opção A) tem prioridade sobre o do IP.

Se a biblioteca e o servidor estiverem em domínios diferentes, defina
`BIBLIO_ORIGENS=https://biblioteca.exemplo.ao` para limitar quem pode enviar eventos.

## O que é medido

| Métrica | Como é calculada |
|---|---|
| **Livros mais procurados** | aberturas da ficha + cliques vindos da pesquisa; e os **termos** mais pesquisados (agrupados sem maiúsculas/acentos) |
| **Livros mais lidos** | soma do tempo de leitura ativa por livro, e nº de leitores |
| **Não encontrados** | pesquisas com 0 resultados + pedidos explícitos — lista do que falta no acervo |
| **Tempo de pesquisa** | começar a escrever → submeter (escrever) e submeter → clicar num resultado (escolher) |
| **Tempo de leitura** | só conta com o separador visível e interação nos últimos 2 min; enviado em blocos de 1 min |
| **Taxa de sucesso da pesquisa** | % de pesquisas que levaram a abrir um resultado |
| **Taxa de abandono** | % de pesquisas com resultados em que ninguém clicou (resultados pouco relevantes) |
| **Posição média do clique** | perto de 1 = a ordenação dos resultados é boa |
| Sessões, utilizadores, duração da sessão, pesquisas por sessão, atividade por hora | — |
| **Por computador** | estado (ativo/inativo), última atividade, horas de uso e todas as métricas acima filtradas por computador |

Todas as métricas podem ser vistas para **hoje, 7, 30, 90 dias, 12 meses ou datas à escolha**,
agrupadas por **dia, semana (começa à segunda) ou mês**.

**Leitura para usabilidade:** taxa de sucesso a descer ou tempo de pesquisa a subir indicam
dificuldade em encontrar livros; muitas pesquisas sem resultados indicam falhas no acervo ou
na pesquisa (erros ortográficos, sinónimos); posição média do clique alta indica má ordenação.

## Relatório mensal em PDF por e-mail

No servidor, `sudo bash instalacao/configurar-email.sh` agenda o envio no dia 1 de cada mês
(ver o [guia](instalacao/GUIA-INSTALACAO.md#7-relatório-mensal-em-pdf-por-e-mail)).
Para gerar um PDF à mão: `python relatorio_mensal.py --mes 2026-10 --so-pdf outubro.pdf`
(precisa do pacote `reportlab`).

## Relatórios sem o painel

```bash
python relatorio.py --periodo 7d --agrupar dia
python relatorio.py --periodo 12m --agrupar mes --csv relatorios/   # um CSV por tabela (abre no Excel)
python relatorio.py --periodo 30d --posto PC-01                    # só um computador
python relatorio.py --inicio 2026-01-01 --fim 2026-03-31 --agrupar semana --json
```

No painel, cada tabela tem um botão **Exportar CSV**. API: `GET /api/metricas?periodo=30d&agrupar=semana`
`GET /api/exportar?tabela=mais_lidos&periodo=30d` e `GET /api/postos`. Todos aceitam `&posto=PC-01`.

## Configuração (variáveis de ambiente)

| Variável | Por omissão | Para quê |
|---|---|---|
| `BIBLIO_BD` | `biblioteca_analytics.db` | ficheiro da base de dados |
| `BIBLIO_TOKEN` | — | se definido, o painel exige `?token=...` |
| `BIBLIO_ORIGENS` | `*` | domínios autorizados a enviar eventos |
| `BIBLIO_FUSO` | `1` | fuso horário (horas) para separar dias — Angola = UTC+1 |
| `BIBLIO_POSTOS` | `postos.json` | lista IP → nome dos computadores |
| `BIBLIO_CONFIAR_PROXY` | — | `1` para ler o IP do cabeçalho `X-Forwarded-For` |
| `BIBLIO_CHAVE_RECOLHA` | — | se definida, só aceita eventos com esta chave (opções da extensão, ou `data-chave` no `tracker.js`) |
| `BIBLIO_DEMO` | `1` | `0` desliga a página `/demo` |
| `BIBLIO_HOST` / `BIBLIO_PORTA` | `127.0.0.1` / `8080` | onde o servidor escuta (`0.0.0.0` para a rede) |

Em produção, coloque o servidor atrás de HTTPS (por exemplo Nginx) e defina `BIBLIO_TOKEN`.

## Privacidade

Não são recolhidos IP, nome, e-mail nem cookies. Cada navegador recebe um identificador
anónimo aleatório (guardado em `localStorage`) para contar utilizadores únicos.

## Testes

```bash
python -m unittest discover -s tests -v
```
