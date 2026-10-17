# WBG Scorecard Explorer: one container serving the web app, chat API and MCP endpoint.
# Runs on Render (render.yaml), Hugging Face Spaces (Docker SDK) or anywhere Docker runs; uses $PORT (default 7860):
#   docker build -t scorecard . && docker run -p 7860:7860 -e ANTHROPIC_API_KEY=... scorecard
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=7860

# Hugging Face runs containers as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user . .

# Build the database from the committed raw API extracts (no network needed). The command fails the
# build if any data-quality check FAILs. The frontend is pre-built (frontend/dist), so no Node.js here.
RUN python -m pipeline --offline && chown -R user:user data

USER user
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
