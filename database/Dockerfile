# Imagem oficial e publica do PostgreSQL.
FROM postgres:16

# Todo arquivo .sql colocado aqui roda sozinho quando o banco nasce, em
# ordem alfabetica: primeiro as tabelas, depois os dados de exemplo.
COPY database.sql /docker-entrypoint-initdb.d/01.sql
COPY seed.sql /docker-entrypoint-initdb.d/02.sql
