# Stand-in for a Guidewire ClaimCenter tenant. NOT Guidewire software; for demos and tests only.
FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" python-multipart
COPY mock_claimcenter/claimcenter_mock.py .
COPY samples/policies.json /app/policies.json
ENV PORT=8090 POLICY_SEED_FILE=/app/policies.json
EXPOSE 8090
CMD ["sh", "-c", "uvicorn claimcenter_mock:app --host 0.0.0.0 --port ${PORT}"]
