# Biblioteca Analytics

Programa simples para recolher dados de navegação da **Biblioteca Virtual** e medir a
sua usabilidade: livros mais procurados, mais lidos, não encontrados, tempo de pesquisa
e tempo de leitura — por dia, semana e mês.

Só precisa de **Python 3.10+** (biblioteca padrão + SQLite). Não há nada para instalar.

```
biblioteca-analytics/
├── servidor.py          # recebe eventos, serve o painel e a API de métricas
├── analytics.py         # base de dados e cálculo das métricas
├── relatorio.py         # relatório na consola / exportação CSV, sem servidor
├── gerar_dados_demo.py  # dados fictícios para experimentar
├── static/
│   ├── tracker.js       # script a incluir nas páginas da biblioteca
│   ├── painel.html      # painel de métricas
│   └── demo.html        # biblioteca de demonstração
└── tests/
```

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

## Ligar à Biblioteca Virtual

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
| `BIBLIO_HOST` / `BIBLIO_PORTA` | `127.0.0.1` / `8080` | onde o servidor escuta (`0.0.0.0` para a rede) |

Em produção, coloque o servidor atrás de HTTPS (por exemplo Nginx) e defina `BIBLIO_TOKEN`.

## Privacidade

Não são recolhidos IP, nome, e-mail nem cookies. Cada navegador recebe um identificador
anónimo aleatório (guardado em `localStorage`) para contar utilizadores únicos.

## Testes

```bash
python -m unittest discover -s tests -v
```
