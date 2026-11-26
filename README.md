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

Todas as métricas podem ser vistas para **hoje, 7, 30, 90 dias, 12 meses ou datas à escolha**,
agrupadas por **dia, semana (começa à segunda) ou mês**.

**Leitura para usabilidade:** taxa de sucesso a descer ou tempo de pesquisa a subir indicam
dificuldade em encontrar livros; muitas pesquisas sem resultados indicam falhas no acervo ou
na pesquisa (erros ortográficos, sinónimos); posição média do clique alta indica má ordenação.

## Relatórios sem o painel

```bash
python relatorio.py --periodo 7d --agrupar dia
python relatorio.py --periodo 12m --agrupar mes --csv relatorios/   # um CSV por tabela (abre no Excel)
python relatorio.py --inicio 2026-01-01 --fim 2026-03-31 --agrupar semana --json
```

No painel, cada tabela tem um botão **Exportar CSV**. API: `GET /api/metricas?periodo=30d&agrupar=semana`
e `GET /api/exportar?tabela=mais_lidos&periodo=30d`.

## Configuração (variáveis de ambiente)

| Variável | Por omissão | Para quê |
|---|---|---|
| `BIBLIO_BD` | `biblioteca_analytics.db` | ficheiro da base de dados |
| `BIBLIO_TOKEN` | — | se definido, o painel exige `?token=...` |
| `BIBLIO_ORIGENS` | `*` | domínios autorizados a enviar eventos |
| `BIBLIO_FUSO` | `1` | fuso horário (horas) para separar dias — Angola = UTC+1 |
| `BIBLIO_HOST` / `BIBLIO_PORTA` | `127.0.0.1` / `8080` | onde o servidor escuta (`0.0.0.0` para a rede) |

Em produção, coloque o servidor atrás de HTTPS (por exemplo Nginx) e defina `BIBLIO_TOKEN`.

## Privacidade

Não são recolhidos IP, nome, e-mail nem cookies. Cada navegador recebe um identificador
anónimo aleatório (guardado em `localStorage`) para contar utilizadores únicos.

## Testes

```bash
python -m unittest discover -s tests -v
```
