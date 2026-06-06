FROM docker.litellm.ai/berriai/litellm-database:main-stable

WORKDIR /app

COPY litellm_config.yaml /app/config.yaml
COPY lm-studio.key* /app/

EXPOSE 4000

CMD ["--config", "/app/config.yaml", "--port", "4000", "--num_workers", "1", "--skip_default_auth"]
