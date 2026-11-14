# Development stand-in for `api` (P6): the project's dependencies, and nothing else.
# The code itself is mounted from ./src at run time (see docker-compose.yml), so editing it
# needs no rebuild. It is replaced by the real api image when P5 delivers it.
FROM python:3.11-slim

WORKDIR /app

# Just what pip needs to resolve the dependencies declared in pyproject.toml.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .