FROM docker.litellm.ai/berriai/litellm-database:main-stable

WORKDIR /app

COPY litellm_config.yaml /app/config.yaml

EXPOSE 4000

CMD ["--config", "/app/config.yaml", "--port", "4000", "--num_workers", "1"]
